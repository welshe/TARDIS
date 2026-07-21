"""Tests for the deterministic replay engine (replay/engine.py)."""

import pytest

from tardis.models import Step, StepType, Trace
from tardis.replay.engine import ReplayEngine, _count_nodes


def _make_trace_with_steps(tmp_path, trace_id="replay_test_01", success=True):
    from tardis.store.sqlite_store import Store

    store = Store()
    store.conn.execute("DELETE FROM steps WHERE trace_id=?", (trace_id,))
    store.conn.execute("DELETE FROM traces WHERE id=?", (trace_id,))
    store.conn.commit()
    trace = Trace(id=trace_id, success=success)

    trace.add_step(
        Step(trace_id=trace.id, index=0, type=StepType.llm_call,
             input={"kwargs": {"messages": [{"role": "user", "content": "hello"}]}},
             output={"content": "hi there"}, duration_ms=120,
             token_count={"total_tokens": 50}, cost_usd=0.001,
             model_name="gpt-4o", hash="hash_a")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=1, type=StepType.tool_call,
             input={"name": "search", "query": "test"},
             output={"results": ["r1", "r2"]}, duration_ms=80, hash="hash_b")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=2, type=StepType.dom_snapshot,
             input={"url": "http://example.com"},
             output={"elements": {"tag": "div", "children": [
                 {"tag": "span"}, {"tag": "p", "children": [{"tag": "a"}]},
             ]}},
             metadata={"method": "cdp"}, hash="hash_c")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=3, type=StepType.error,
             input={}, output={"error": "timeout"},
             hash="hash_d", success=False, error_type="timeout")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=4, type=StepType.thought,
             input={"thought": "analyzing"}, output={"thought": "done"},
             hash="hash_e")
    )

    store.save_trace(trace)
    return trace


class TestReplayEngine:
    def test_init_loads_trace(self, tmp_path):
        tid = "replay_init_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        assert engine.trace.id == tid
        assert len(engine.trace.steps) == 5

    def test_init_raises_on_missing_trace(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            ReplayEngine("nonexistent_id")

    def test_replay_returns_trace(self, tmp_path, capsys):
        tid = "replay_replay_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        result = engine.replay()
        assert result.id == tid
        captured = capsys.readouterr()
        assert "TARDIS REPLAY" in captured.out
        assert "END REPLAY" in captured.out

    def test_replay_range(self, tmp_path, capsys):
        tid = "replay_range_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.replay(from_idx=1, to_idx=3)
        captured = capsys.readouterr()
        assert "steps 1 -> 3" in captured.out

    def test_replay_edit_injection(self, tmp_path, capsys):
        tid = "replay_edit_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.replay(from_idx=0, to_idx=1, edit_tool_output={"injected": True})
        assert 0 in engine.edit_injections

    def test_add_remove_breakpoint(self, tmp_path):
        tid = "replay_bp_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.add_breakpoint(2)
        assert 2 in engine.breakpoints
        engine.remove_breakpoint(2)
        assert 2 not in engine.breakpoints

    def test_remove_breakpoint_noop(self, tmp_path):
        tid = "replay_bpnoop_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.remove_breakpoint(999)

    def test_analyze_patterns(self, tmp_path, capsys):
        tid = "replay_pat_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.analyze_patterns()
        captured = capsys.readouterr()
        assert "PATTERN ANALYSIS" in captured.out
        assert "LLM Calls:" in captured.out

    def test_diff_same_trace(self, tmp_path, capsys):
        tid = "replay_diff_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        divergences = engine.diff(tid)
        assert divergences == []

    def test_inspect_step(self, tmp_path, capsys):
        tid = "replay_inspect_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine._inspect_step(engine.trace.steps[0])
        captured = capsys.readouterr()
        assert "INSPECTING STEP" in captured.out

    def test_replay_state_accumulates(self, tmp_path, capsys):
        tid = "replay_state_01"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.replay()
        captured = capsys.readouterr()
        assert "Replayed 5 steps" in captured.out

    def test_diff_reports_divergent_hashes(self, tmp_path, capsys):
        from tardis.store.sqlite_store import Store

        tid_a = "replay_div_a"
        tid_b = "replay_div_b"
        store = Store()
        for tid in (tid_a, tid_b):
            store.conn.execute("DELETE FROM steps WHERE trace_id=?", (tid,))
            store.conn.execute("DELETE FROM traces WHERE id=?", (tid,))
        store.conn.commit()

        trace_a = Trace(id=tid_a, success=True)
        trace_a.add_step(Step(trace_id=tid_a, index=0, type=StepType.llm_call,
                              input={}, output={}, hash="hash_a"))
        trace_a.add_step(Step(trace_id=tid_a, index=1, type=StepType.tool_call,
                              input={}, output={}, hash="hash_b"))
        store.save_trace(trace_a)

        trace_b = Trace(id=tid_b, success=False)
        trace_b.add_step(Step(trace_id=tid_b, index=0, type=StepType.llm_call,
                              input={}, output={}, hash="hash_x"))
        trace_b.add_step(Step(trace_id=tid_b, index=1, type=StepType.tool_call,
                              input={}, output={}, hash="hash_y"))
        store.save_trace(trace_b)

        engine = ReplayEngine(tid_a)
        divergences = engine.diff(tid_b)
        assert len(divergences) > 0
        assert divergences[0][0] == 0

    def test_replay_empty_trace(self, tmp_path, capsys):
        tid = "replay_empty"
        from tardis.store.sqlite_store import Store
        store = Store()
        store.conn.execute("DELETE FROM steps WHERE trace_id=?", (tid,))
        store.conn.execute("DELETE FROM traces WHERE id=?", (tid,))
        store.conn.commit()
        trace = Trace(id=tid, success=True)
        store.save_trace(trace)
        engine = ReplayEngine(tid)
        engine.replay()
        captured = capsys.readouterr()
        assert "Total steps: 0" in captured.out

    def test_replay_with_all_llm_costs(self, tmp_path, capsys):
        tid = "replay_costs"
        from tardis.store.sqlite_store import Store
        store = Store()
        store.conn.execute("DELETE FROM steps WHERE trace_id=?", (tid,))
        store.conn.execute("DELETE FROM traces WHERE id=?", (tid,))
        store.conn.commit()
        trace = Trace(id=tid, success=True)
        for i in range(4):
            trace.add_step(
                Step(trace_id=tid, index=i, type=StepType.llm_call,
                     input={}, output={}, hash=f"h{i}",
                     cost_usd=0.01 * (i + 1),
                     token_count={"total_tokens": 100 * (i + 1)},
                     model_name="gpt-4o")
            )
        store.save_trace(trace)
        engine = ReplayEngine(tid)
        engine.replay()
        captured = capsys.readouterr()
        assert "Total cost:" in captured.out
        assert "Model: gpt-4o" in captured.out

    def test_analyze_patterns_errors(self, tmp_path, capsys):
        tid = "replay_pat_err"
        _make_trace_with_steps(tmp_path, trace_id=tid, success=False)
        engine = ReplayEngine(tid)
        engine.analyze_patterns()
        captured = capsys.readouterr()
        assert "Tool calls:" in captured.out

    def test_multiple_edit_injections(self, tmp_path, capsys):
        tid = "replay_multi_edit"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.replay(from_idx=0, to_idx=2, edit_tool_output={"injected": True})
        engine.replay(from_idx=2, to_idx=4, edit_tool_output={"injected": True})
        assert 0 in engine.edit_injections
        assert 2 in engine.edit_injections

    def test_count_nodes_deeply_nested(self):
        tree = {"tag": "div", "children": [
            {"tag": "span", "children": [
                {"tag": "a", "children": [
                    {"tag": "span"}
                ]}
            ]},
            {"tag": "p"},
        ]}
        assert _count_nodes(tree) == 5

    def test_count_nodes_non_dict_children(self):
        tree = {"tag": "div", "children": [{"tag": "span"}, "text", 123]}
        assert _count_nodes(tree) == 2

    def test_inspect_step_shows_metadata(self, tmp_path, capsys):
        tid = "replay_inspect_meta"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        step = engine.trace.steps[2]
        engine._inspect_step(step)
        captured = capsys.readouterr()
        assert "INSPECTING STEP" in captured.out
        assert "cdp" in captured.out

    def test_replay_breakpoint_with_input(self, tmp_path, capsys, monkeypatch):
        tid = "replay_bp_input"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.add_breakpoint(2)
        monkeypatch.setattr("builtins.input", lambda _: "q")
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": staticmethod(lambda: True)})())
        engine.replay()
        captured = capsys.readouterr()
        assert "BREAKPOINT at step 2" in captured.out

    def test_replay_breakpoint_inspect(self, tmp_path, capsys, monkeypatch):
        tid = "replay_bp_inspect"
        _make_trace_with_steps(tmp_path, trace_id=tid)
        engine = ReplayEngine(tid)
        engine.add_breakpoint(2)
        inputs = iter(["i", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": staticmethod(lambda: True)})())
        engine.replay()
        captured = capsys.readouterr()
        assert "INSPECTING STEP 2" in captured.out


class TestCountNodes:
    def test_empty(self):
        assert _count_nodes(None) == 0
        assert _count_nodes({}) == 0

    def test_single_node(self):
        assert _count_nodes({"tag": "div"}) == 1

    def test_nested(self):
        tree = {
            "tag": "div",
            "children": [
                {"tag": "span"},
                {"tag": "p", "children": [{"tag": "a"}]},
            ],
        }
        assert _count_nodes(tree) == 4

    def test_none_children(self):
        assert _count_nodes({"tag": "div", "children": None}) == 1
