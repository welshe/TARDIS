
import pytest
from rich.console import Console

from tardis.diff.viewer import (
    DiffEntry,
    DiffReport,
    TraceDiffer,
    TraceDiffViewer,
)
from tardis.models import Step, StepType, Trace


def _make_trace(trace_id="diff_a", steps=3, base_hash="hash"):
    trace = Trace(id=trace_id)
    for i in range(steps):
        trace.add_step(
            Step(
                trace_id=trace.id, index=i, type=StepType.llm_call,
                input={"msg": f"input_{i}"}, output={"res": f"output_{i}"},
                hash=f"{base_hash}_{i}", duration_ms=i * 100,
                token_count={"total_tokens": i * 10},
            )
        )
    return trace


class TestDiffEntry:
    def test_creation(self):
        entry = DiffEntry(
            index=0, step_type="llm_call",
            left_hash="a", right_hash="b",
            left_output={"a": 1}, right_output={"b": 2},
            left_input={"x": 1}, right_input={"y": 2},
            duration_diff_ms=50, token_diff={"total_tokens": 10},
        )
        assert entry.index == 0
        assert entry.left_hash == "a"
        assert entry.right_hash == "b"
        assert entry.duration_diff_ms == 50

    def test_defaults(self):
        entry = DiffEntry(index=0, step_type="llm_call", left_hash=None, right_hash=None,
                          left_output=None, right_output=None,
                          left_input=None, right_input=None,
                          duration_diff_ms=None)
        assert entry.token_diff == {}


class TestDiffReport:
    def test_creation(self):
        report = DiffReport(
            trace_id_a="a", trace_id_b="b",
            total_steps_a=5, total_steps_b=5,
            divergent_steps=[], only_in_a=[], only_in_b=[],
            cost_diff=0.0, token_diff_total=0, duration_diff_total=0.0,
            structural_match=True,
        )
        assert report.structural_match is True
        assert report.trace_id_a == "a"

    def test_diverged_report(self):
        entry = DiffEntry(index=0, step_type="llm_call",
                          left_hash="a", right_hash="b",
                          left_output={}, right_output={},
                          left_input={}, right_input={},
                          duration_diff_ms=0)
        report = DiffReport(
            trace_id_a="a", trace_id_b="b",
            total_steps_a=3, total_steps_b=3,
            divergent_steps=[entry], only_in_a=[], only_in_b=[],
            cost_diff=0.1, token_diff_total=50, duration_diff_total=2.0,
            structural_match=False,
        )
        assert report.structural_match is False
        assert len(report.divergent_steps) == 1


class TestTraceDiffer:
    def test_identical_traces(self):
        a = _make_trace("identical_a", steps=3)
        b = _make_trace("identical_b", steps=3)
        differ = TraceDiffer()
        report = differ.diff_objects(a, b)
        assert report.structural_match is True
        assert len(report.divergent_steps) == 0

    def test_divergent_hashes(self):
        a = _make_trace("div_a", steps=3, base_hash="hash_a")
        b = _make_trace("div_b", steps=3, base_hash="hash_b")
        differ = TraceDiffer()
        report = differ.diff_objects(a, b)
        assert report.structural_match is False
        assert len(report.divergent_steps) == 3

    def test_different_step_counts(self):
        a = _make_trace("len_a", steps=5, base_hash="h")
        b = _make_trace("len_b", steps=3, base_hash="h")
        differ = TraceDiffer()
        report = differ.diff_objects(a, b)
        assert report.structural_match is False
        assert len(report.only_in_a) == 2
        assert len(report.only_in_b) == 0

    def test_cost_and_token_diff(self):
        a = _make_trace("cost_a", steps=2, base_hash="h")
        b = _make_trace("cost_b", steps=2, base_hash="h")
        a.total_cost_usd = 1.0
        a.total_tokens = 100
        b.total_cost_usd = 0.5
        b.total_tokens = 60
        differ = TraceDiffer()
        report = differ.diff_objects(a, b)
        assert report.cost_diff == 0.5
        assert report.token_diff_total == 40

    def test_trace_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        differ = TraceDiffer()
        with pytest.raises(ValueError, match="not found"):
            differ.diff("nonexistent_a", "nonexistent_b")

    def test_stored_trace_lookup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.sqlite_store import Store
        store = Store()

        trace_a = Trace(id="stored_a")
        trace_a.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                              input={}, output={}, hash="a"))
        store.save_trace(trace_a)

        trace_b = Trace(id="stored_b")
        trace_b.add_step(Step(trace_id="t", index=0, type=StepType.llm_call,
                              input={}, output={}, hash="b"))
        store.save_trace(trace_b)

        differ = TraceDiffer()
        report = differ.diff("stored_a", "stored_b")
        assert report.structural_match is False
        assert len(report.divergent_steps) == 1


class TestTraceDiffViewer:
    def test_render_identical(self):
        report = DiffReport(
            trace_id_a="a", trace_id_b="b",
            total_steps_a=2, total_steps_b=2,
            divergent_steps=[], only_in_a=[], only_in_b=[],
            cost_diff=0, token_diff_total=0, duration_diff_total=0,
            structural_match=True,
        )
        console = Console(width=120, force_terminal=True, color_system=None)
        viewer = TraceDiffViewer(console=console)
        viewer.render(report)

    def test_render_divergent(self):
        entry = DiffEntry(index=1, step_type="tool_call",
                          left_hash="h1", right_hash="h2",
                          left_output={"x": 1}, right_output={"y": 2},
                          left_input={}, right_input={},
                          duration_diff_ms=100, token_diff={"total": 10})
        report = DiffReport(
            trace_id_a="a", trace_id_b="b",
            total_steps_a=3, total_steps_b=3,
            divergent_steps=[entry], only_in_a=[], only_in_b=[],
            cost_diff=0.5, token_diff_total=50, duration_diff_total=1.0,
            structural_match=False,
        )
        console = Console(width=120, force_terminal=True, color_system=None)
        viewer = TraceDiffViewer(console=console)
        viewer.render(report)

    def test_render_side_only(self):
        report = DiffReport(
            trace_id_a="a", trace_id_b="b",
            total_steps_a=5, total_steps_b=3,
            divergent_steps=[], only_in_a=[3, 4], only_in_b=[],
            cost_diff=0, token_diff_total=0, duration_diff_total=0,
            structural_match=False,
        )
        console = Console(width=120, force_terminal=True, color_system=None)
        viewer = TraceDiffViewer(console=console)
        viewer.render(report)

    def test_render_html(self):
        entry = DiffEntry(index=0, step_type="llm_call",
                          left_hash="a", right_hash="b",
                          left_output={}, right_output={},
                          left_input={}, right_input={},
                          duration_diff_ms=None)
        report = DiffReport(
            trace_id_a="a", trace_id_b="b",
            total_steps_a=3, total_steps_b=3,
            divergent_steps=[entry], only_in_a=[], only_in_b=[],
            cost_diff=0, token_diff_total=0, duration_diff_total=0,
            structural_match=False,
        )
        viewer = TraceDiffViewer()
        html = viewer.render_html(report)
        assert "Trace Diff" in html
        assert "a vs b" in html


class TestDiffTracesFunction:
    def test_diff_traces_returns_report(self):
        a = _make_trace("func_a", steps=2, base_hash="a")
        b = _make_trace("func_b", steps=2, base_hash="b")
        differ = TraceDiffer()
        report = differ.diff_objects(a, b)
        assert isinstance(report, DiffReport)

    def test_diff_traces_html(self):
        a = _make_trace("html_a", steps=2, base_hash="a")
        b = _make_trace("html_b", steps=2, base_hash="b")
        differ = TraceDiffer()
        report = differ.diff_objects(a, b)
        viewer = TraceDiffViewer()
        html = viewer.render_html(report)
        assert isinstance(html, str)
        assert "Trace Diff" in html
