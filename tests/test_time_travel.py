"""Tests for the deterministic time-travel replay engine."""

import json
import os
import time

from tardis.replay.time_travel import (
    ReplayEvent,
    SystemState,
    TimeTravelReplay,
    TimeTravelTracer,
    _redact_env_vars,
    create_replay_engine,
)


class TestRedactEnvVars:
    def test_redacts_known_keys(self):
        env = {"OPENAI_API_KEY": "sk-123", "NORMAL_VAR": "ok"}
        result = _redact_env_vars(env)
        assert result["OPENAI_API_KEY"] == "***REDACTED***"
        assert result["NORMAL_VAR"] == "ok"

    def test_redacts_secret_pattern(self):
        env = {"MY_SECRET_TOKEN": "abc", "APP_NAME": "tardis"}
        result = _redact_env_vars(env)
        assert result["MY_SECRET_TOKEN"] == "***REDACTED***"
        assert result["APP_NAME"] == "tardis"

    def test_redacts_password_pattern(self):
        env = {"DB_PASSWORD": "pass123", "HOST": "localhost"}
        result = _redact_env_vars(env)
        assert result["DB_PASSWORD"] == "***REDACTED***"
        assert result["HOST"] == "localhost"

    def test_empty_dict(self):
        assert _redact_env_vars({}) == {}


class TestSystemState:
    def test_to_dict(self):
        state = SystemState(
            timestamp=1.0,
            step_id="s1",
            trace_id="t1",
            pid=123,
            thread_id=456,
            memory_hash="abc",
            open_files=["f1.txt"],
            cwd="/tmp",
        )
        d = state.to_dict()
        assert d["pid"] == 123
        assert d["memory_hash"] == "abc"
        assert d["open_files"] == ["f1.txt"]

    def test_defaults(self):
        state = SystemState(
            timestamp=0,
            step_id="s",
            trace_id="t",
            pid=0,
            thread_id=None,
            memory_hash="x",
        )
        assert state.env_vars == {}
        assert state.network_connections == []


class TestReplayEvent:
    def test_checksum_auto_computed(self):
        event = ReplayEvent(
            event_type="test",
            timestamp=1.0,
            step_id="s1",
            data={"key": "value"},
        )
        assert event.checksum is not None
        assert len(event.checksum) == 16

    def test_checksum_deterministic(self):
        e1 = ReplayEvent(event_type="t", timestamp=1.0, step_id="s", data={"a": 1})
        e2 = ReplayEvent(event_type="t", timestamp=1.0, step_id="s", data={"a": 1})
        assert e1.checksum == e2.checksum

    def test_checksum_preserved_if_provided(self):
        event = ReplayEvent(
            event_type="t",
            timestamp=1.0,
            step_id="s",
            data={},
            checksum="custom123",
        )
        assert event.checksum == "custom123"


def _write_trace_file(storage_dir, trace_id, events):
    """Helper to write a trace JSONL file."""
    trace_file = storage_dir / f"{trace_id}.jsonl"
    with open(trace_file, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return trace_file


class TestTimeTravelTracer:
    def test_init_creates_dir(self, tmp_path):
        storage = tmp_path / "replay"
        TimeTravelTracer(backend="userspace", storage_dir=str(storage))
        assert storage.exists()

    def test_record_event_when_not_running(self, tmp_path):
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(tmp_path / "r"))
        tracer.record_event("test", {"a": 1}, "step_0")
        assert len(tracer.events) == 0

    def test_record_event_when_running(self, tmp_path):
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(tmp_path / "r"))
        tracer.running = True
        tracer.record_event("test", {"a": 1}, "step_0")
        assert len(tracer.events) == 1
        assert tracer.events[0].event_type == "test"

    def test_stop_returns_events(self, tmp_path):
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(tmp_path / "r"))
        tracer.running = True
        tracer.record_event("evt1", {}, "s1")
        events = tracer.stop()
        assert len(events) == 1
        assert not tracer.running

    def test_save_trace(self, tmp_path):
        storage = tmp_path / "replay"
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(storage))
        tracer.running = True
        tracer.record_event("click", {"x": 100}, "s1")
        tracer.record_event("type", {"char": "a"}, "s2")
        path = tracer.save_trace("trace_abc")
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_verify_integrity_valid(self, tmp_path):
        storage = tmp_path / "replay"
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(storage))
        tracer.running = True
        tracer.record_event("click", {"x": 1}, "s1")
        tracer.save_trace("trace_verify")
        ok, errors = tracer.verify_integrity("trace_verify")
        assert ok
        assert errors == []

    def test_verify_integrity_missing_file(self, tmp_path):
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(tmp_path / "r"))
        ok, errors = tracer.verify_integrity("nonexistent")
        assert not ok
        assert "not found" in errors[0]

    def test_verify_integrity_tampered(self, tmp_path):
        storage = tmp_path / "replay"
        storage.mkdir(parents=True, exist_ok=True)
        tracer = TimeTravelTracer(backend="userspace", storage_dir=str(storage))
        trace_file = storage / "trace_tamper.jsonl"
        event = ReplayEvent(
            event_type="test", timestamp=1.0, step_id="s1", data={"a": 1}
        )
        with open(trace_file, "w") as f:
            entry = {
                "event_type": "test",
                "timestamp": 1.0,
                "step_id": "s1",
                "data": {"a": 1},
                "checksum": event.checksum,
            }
            f.write(json.dumps(entry) + "\n")
            # Tamper the data line
            entry["data"]["a"] = 999
            f.write(json.dumps(entry) + "\n")
        ok, errors = tracer.verify_integrity("trace_tamper")
        assert not ok
        assert len(errors) >= 1


class TestTimeTravelReplay:
    def _make_trace(self, storage_dir, trace_id="tr1", count=5):
        storage_dir.mkdir(parents=True, exist_ok=True)
        events = []
        for i in range(count):
            state = SystemState(
                timestamp=time.time() + i,
                step_id=f"s{i}",
                trace_id=trace_id,
                pid=100,
                thread_id=None,
                memory_hash=f"hash_{i}",
                open_files=[f"file_{i}.txt"],
                cwd="/tmp",
            )
            ev = ReplayEvent(
                event_type=f"event_{i}",
                timestamp=time.time() + i,
                step_id=f"s{i}",
                data={"index": i},
                system_state=state,
            )
            events.append(
                {
                    "event_type": ev.event_type,
                    "timestamp": ev.timestamp,
                    "step_id": ev.step_id,
                    "data": ev.data,
                    "checksum": ev.checksum,
                    "system_state": state.to_dict(),
                }
            )
        _write_trace_file(storage_dir, trace_id, events)
        return events

    def test_load_trace(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        assert replay.load_trace("tr1")
        assert len(replay.loaded_events) == 5

    def test_load_nonexistent(self, tmp_path):
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        assert not replay.load_trace("missing")

    def test_step_forward(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        ev = replay.step_forward()
        assert ev is not None
        assert ev.event_type == "event_0"
        assert replay.current_position == 1

    def test_step_forward_at_end(self, tmp_path):
        self._make_trace(tmp_path, count=2)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        replay.step_forward()
        replay.step_forward()
        assert replay.step_forward() is None

    def test_step_backward(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        replay.step_forward()
        replay.step_forward()
        ev = replay.step_backward()
        assert ev is not None
        assert replay.current_position == 1

    def test_step_backward_at_start(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        assert replay.step_backward() is None

    def test_rewind_to(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        assert replay.rewind_to(3)
        assert replay.current_position == 3

    def test_rewind_to_invalid(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        assert not replay.rewind_to(-1)
        assert not replay.rewind_to(100)

    def test_breakpoints(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        replay.add_breakpoint(2)
        assert 2 in replay.breakpoints
        assert replay.breakpoints == [2]

    def test_run_to_breakpoint(self, tmp_path):
        self._make_trace(tmp_path, count=5)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        replay.add_breakpoint(3)
        result = replay.run_to_breakpoint()
        assert result is not None
        pos, event = result
        assert pos == 3

    def test_run_to_breakpoint_none(self, tmp_path):
        self._make_trace(tmp_path, count=3)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        result = replay.run_to_breakpoint()
        assert result is None

    def test_get_current_state(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        state = replay.get_current_state()
        assert state is not None
        assert state["position"] == 0
        assert state["total_events"] == 5

    def test_get_current_state_empty(self, tmp_path):
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        assert replay.get_current_state() is None

    def test_diff_states_identical(self, tmp_path):
        self._make_trace(tmp_path, count=3)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        diff = replay.diff_states(0, 0)
        assert diff["identical"] is True

    def test_diff_states_different_memory(self, tmp_path):
        self._make_trace(tmp_path, count=3)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        diff = replay.diff_states(0, 1)
        # hash_0 != hash_1 so memory_changed should be True
        assert "memory_changed" in diff["differences"]

    def test_diff_states_out_of_range(self, tmp_path):
        self._make_trace(tmp_path, count=2)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        diff = replay.diff_states(0, 99)
        assert "error" in diff

    def test_export_replay_script(self, tmp_path):
        self._make_trace(tmp_path)
        replay = TimeTravelReplay(storage_dir=str(tmp_path))
        replay.load_trace("tr1")
        out_path = str(tmp_path / "replay_script.py")
        replay.export_replay_script(out_path)
        assert os.path.exists(out_path)
        content = open(out_path).read()
        assert "def replay_trace():" in content


class TestConvenienceFunctions:
    def test_create_replay_engine(self, tmp_path):
        engine = create_replay_engine()
        assert isinstance(engine, TimeTravelReplay)

    def test_create_replay_engine_with_trace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        TestTimeTravelReplay()._make_trace(tmp_path / ".tardis" / "replay")
        engine = create_replay_engine(trace_id="tr1")
        assert len(engine.loaded_events) == 5
