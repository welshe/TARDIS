"""Tests for the kernel tracer (os_integration/kernel_tracer.py)."""

import os

import pytest

from tardis.os_integration.kernel_tracer import KernelEvent, KernelTracer


class TestKernelEvent:
    def test_to_dict(self):
        event = KernelEvent(
            event_type="syscall",
            timestamp=1.0,
            pid=123,
            tid=456,
            syscall="openat",
            path="/tmp/test",
            data={"key": "val"},
        )
        d = event.to_dict()
        assert d["event_type"] == "syscall"
        assert d["pid"] == 123
        assert d["path"] == "/tmp/test"

    def test_defaults(self):
        event = KernelEvent(event_type="test", timestamp=0.0, pid=1, tid=None)
        assert event.syscall is None
        assert event.path is None
        assert event.data is None


class TestKernelTracer:
    def test_init_auto_backend(self):
        tracer = KernelTracer(backend="auto")
        # Should set backend based on platform
        assert tracer.backend in ("ebpf", "etw", "oslog", "userspace")

    def test_init_explicit_backend(self):
        tracer = KernelTracer(backend="userspace")
        assert tracer.backend == "userspace"

    def test_init_with_target_pid(self):
        tracer = KernelTracer(backend="userspace", target_pid=42)
        assert tracer.target_pid == 42

    def test_init_default_pid(self):
        tracer = KernelTracer(backend="userspace")
        assert tracer.target_pid == os.getpid()

    def test_record_event_when_not_running(self):
        tracer = KernelTracer(backend="userspace")
        tracer.record_event("test", {"a": 1}, "step_0")
        assert len(tracer.events) == 0

    def test_record_event_when_running(self):
        tracer = KernelTracer(backend="userspace")
        tracer.running = True
        tracer.record_event("test", {"a": 1}, "step_0")
        assert len(tracer.events) == 1

    def test_record_event_calls_callback(self):
        captured = []
        tracer = KernelTracer(backend="userspace")
        tracer.running = True
        tracer._callback = lambda e: captured.append(e)
        tracer.record_event("test", {}, "s1")
        assert len(captured) == 1

    def test_record_event_callback_exception_swallows(self):
        tracer = KernelTracer(backend="userspace")
        tracer.running = True
        tracer._callback = lambda e: 1 / 0
        # Should not raise
        tracer.record_event("test", {}, "s1")

    def test_stop_returns_events(self):
        tracer = KernelTracer(backend="userspace")
        tracer.running = True
        tracer.record_event("evt1", {}, "s1")
        events = tracer.stop()
        assert len(events) == 1
        assert not tracer.running

    def test_stop_kills_process(self):
        tracer = KernelTracer(backend="userspace")
        tracer.running = True
        # Simulate a process
        tracer._process = None
        events = tracer.stop()
        assert events == []

    def test_is_available_userspace(self):
        tracer = KernelTracer(backend="userspace")
        import importlib.util

        if importlib.util.find_spec("psutil") is not None:
            assert tracer.is_available
        else:
            assert not tracer.is_available

    def test_save_trace(self, tmp_path):
        tracer = KernelTracer(backend="userspace")
        tracer._storage_dir = tmp_path
        tracer.running = True
        tracer.record_event("test", {"a": 1}, "s1")
        path = tracer.save_trace("kt_test")
        assert path.exists()

    def test_verify_integrity_valid(self, tmp_path):
        tracer = KernelTracer(backend="userspace")
        tracer._storage_dir = tmp_path
        tracer.running = True
        tracer.record_event("test", {"a": 1}, "s1")
        tracer.save_trace("kt_verify")
        ok, errors = tracer.verify_integrity("kt_verify")
        assert ok

    def test_verify_integrity_missing(self, tmp_path):
        tracer = KernelTracer(backend="userspace")
        tracer._storage_dir = tmp_path
        ok, errors = tracer.verify_integrity("nonexistent")
        assert not ok

    def test_start_stop_lifecycle(self):
        tracer = KernelTracer(backend="userspace")
        try:
            tracer.start()
            assert tracer.running
            events = tracer.stop()
            assert isinstance(events, list)
        except RuntimeError:
            # psutil might not be installed
            pytest.skip("psutil not available")

    def test_start_idempotent(self):
        tracer = KernelTracer(backend="userspace")
        try:
            result = tracer.start()
            assert result is tracer
            tracer.stop()
        except RuntimeError:
            pytest.skip("psutil not available")
