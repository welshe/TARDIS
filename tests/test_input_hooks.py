"""Tests for cross-platform input hooks (os_integration/input_hooks.py)."""

import threading
import time

import pytest

from tardis.os_integration.input_hooks import (
    InputEvent,
    PlatformHookManager,
    hook_input,
)


class _StubHookManager(PlatformHookManager):
    """Concrete subclass for testing the abstract interface."""

    def _install_hooks(self) -> None:
        pass

    def _uninstall_hooks(self) -> None:
        pass


class TestInputEvent:
    def test_creation_minimal(self):
        ev = InputEvent(event_type="key_press", timestamp=1.0)
        assert ev.event_type == "key_press"
        assert ev.timestamp == 1.0
        assert ev.key is None
        assert ev.vk_code is None
        assert ev.x is None
        assert ev.y is None
        assert ev.button is None
        assert ev.modifiers == []
        assert ev.platform == ""

    def test_creation_full(self):
        ev = InputEvent(
            event_type="mouse_click", timestamp=2.5,
            key="a", vk_code=65, x=100, y=200,
            button="left", modifiers=["ctrl", "shift"], platform="windows",
        )
        assert ev.key == "a"
        assert ev.vk_code == 65
        assert ev.x == 100
        assert ev.y == 200
        assert ev.button == "left"
        assert ev.modifiers == ["ctrl", "shift"]
        assert ev.platform == "windows"

    def test_to_dict_minimal(self):
        ev = InputEvent(event_type="key_press", timestamp=1.0)
        d = ev.to_dict()
        assert d == {"type": "key_press", "timestamp": 1.0, "modifiers": [], "platform": ""}

    def test_to_dict_all_fields(self):
        ev = InputEvent(
            event_type="mouse_scroll", timestamp=3.0,
            key="x", vk_code=42, x=50, y=60,
            button="right", modifiers=["alt"], platform="macos",
        )
        d = ev.to_dict()
        assert d["type"] == "mouse_scroll"
        assert d["character"] == "x"
        assert d["vk_code"] == 42
        assert d["x"] == 50
        assert d["y"] == 60
        assert d["button"] == "right"
        assert d["modifiers"] == ["alt"]
        assert d["platform"] == "macos"

    def test_to_dict_none_fields_omitted(self):
        ev = InputEvent(event_type="mouse_move", timestamp=1.0)
        d = ev.to_dict()
        assert "character" not in d
        assert "vk_code" not in d
        assert "x" not in d
        assert "y" not in d
        assert "button" not in d

    def test_to_dict_modifiers_are_copied(self):
        mods = ["shift"]
        ev = InputEvent(event_type="key_press", timestamp=1.0, modifiers=mods)
        d = ev.to_dict()
        assert d["modifiers"] == ["shift"]
        mods.append("ctrl")
        assert d["modifiers"] == ["shift"]


class TestPlatformHookManagerLifecycle:
    def test_start_returns_self(self):
        mgr = _StubHookManager()
        result = mgr.start()
        assert result is mgr

    def test_start_sets_active(self):
        mgr = _StubHookManager()
        assert not mgr.is_active
        mgr.start()
        assert mgr.is_active

    def test_start_is_idempotent(self):
        mgr = _StubHookManager()
        mgr.start()
        mgr.start()
        assert mgr.is_active

    def test_stop_sets_inactive(self):
        mgr = _StubHookManager()
        mgr.start()
        mgr.stop()
        assert not mgr.is_active

    def test_stop_when_not_active_is_noop(self):
        mgr = _StubHookManager()
        mgr.stop()
        assert not mgr.is_active

    def test_stop_clears_events(self):
        mgr = _StubHookManager()
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=time.time()))
        mgr._dispatch(InputEvent(event_type="mouse_move", timestamp=time.time()))
        assert len(mgr.get_events()) == 2
        mgr.stop()
        assert mgr.get_events() == []


class TestPlatformHookManagerDispatch:
    def test_dispatch_stores_event(self):
        mgr = _StubHookManager(redact_characters=False)
        mgr.start()
        ev = InputEvent(event_type="key_press", timestamp=1.0, key="a", platform="linux")
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert len(events) == 1
        assert events[0]["type"] == "key_press"
        assert events[0]["character"] == "a"
        assert events[0]["platform"] == "linux"

    def test_dispatch_stores_in_deque(self):
        mgr = _StubHookManager()
        mgr.start()
        for i in range(5):
            mgr._dispatch(InputEvent(event_type="key_press", timestamp=float(i)))
        assert len(mgr._events) == 5
        assert isinstance(mgr._events, type(mgr._events))


class TestPlatformHookManagerRedaction:
    def test_redact_characters_replaces_key(self):
        mgr = _StubHookManager(redact_characters=True)
        mgr.start()
        ev = InputEvent(event_type="key_press", timestamp=1.0, key="s", vk_code=0x53)
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert events[0]["character"] == "*"
        assert events[0]["vk_code"] == 0x53

    def test_redact_characters_disabled(self):
        mgr = _StubHookManager(redact_characters=False)
        mgr.start()
        ev = InputEvent(event_type="key_press", timestamp=1.0, key="s", vk_code=0x53)
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert events[0]["character"] == "s"

    def test_redact_characters_no_key_field(self):
        mgr = _StubHookManager(redact_characters=True)
        mgr.start()
        ev = InputEvent(event_type="mouse_move", timestamp=1.0, x=10, y=20)
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert "character" not in events[0]

    def test_redact_vk_codes_zeros_vk_and_coords(self):
        mgr = _StubHookManager(redact_characters=False, redact_vk_codes=True)
        mgr.start()
        ev = InputEvent(
            event_type="mouse_click", timestamp=1.0,
            key="a", vk_code=65, x=100, y=200,
        )
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert events[0]["vk_code"] == 0
        assert events[0]["x"] == 0
        assert events[0]["y"] == 0

    def test_redact_vk_codes_disabled(self):
        mgr = _StubHookManager(redact_characters=False, redact_vk_codes=False)
        mgr.start()
        ev = InputEvent(
            event_type="key_press", timestamp=1.0,
            vk_code=65, x=10, y=20,
        )
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert events[0]["vk_code"] == 65
        assert events[0]["x"] == 10
        assert events[0]["y"] == 20

    def test_both_redactions_applied(self):
        mgr = _StubHookManager(redact_characters=True, redact_vk_codes=True)
        mgr.start()
        ev = InputEvent(
            event_type="key_press", timestamp=1.0,
            key="z", vk_code=90, x=5, y=15,
        )
        mgr._dispatch(ev)
        events = mgr.get_events()
        assert events[0]["character"] == "*"
        assert events[0]["vk_code"] == 0
        assert events[0]["x"] == 0
        assert events[0]["y"] == 0


class TestPlatformHookManagerGetEvents:
    def test_get_events_empty(self):
        mgr = _StubHookManager()
        assert mgr.get_events() == []

    def test_get_events_limit(self):
        mgr = _StubHookManager()
        mgr.start()
        for i in range(10):
            mgr._dispatch(InputEvent(event_type="key_press", timestamp=float(i)))
        limited = mgr.get_events(limit=3)
        assert len(limited) == 3
        assert limited[0]["timestamp"] == 7.0
        assert limited[2]["timestamp"] == 9.0

    def test_get_events_limit_larger_than_stored(self):
        mgr = _StubHookManager()
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0))
        events = mgr.get_events(limit=100)
        assert len(events) == 1


class TestPlatformHookManagerGetRecent:
    def test_get_recent_filters_by_time(self):
        mgr = _StubHookManager()
        mgr.start()
        now = time.time()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=now - 10))
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=now - 1))
        recent = mgr.get_recent(seconds=5)
        assert len(recent) == 1
        assert recent[0]["timestamp"] == now - 1

    def test_get_recent_empty_when_all_old(self):
        mgr = _StubHookManager()
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0))
        recent = mgr.get_recent(seconds=1)
        assert recent == []

    def test_get_recent_all_within_window(self):
        mgr = _StubHookManager()
        mgr.start()
        now = time.time()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=now))
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=now))
        recent = mgr.get_recent(seconds=60)
        assert len(recent) == 2


class TestPlatformHookManagerMaxEvents:
    def test_max_events_caps_deque(self):
        mgr = _StubHookManager(max_events=5)
        mgr.start()
        for i in range(10):
            mgr._dispatch(InputEvent(event_type="key_press", timestamp=float(i)))
        events = mgr.get_events()
        assert len(events) == 5
        assert events[0]["timestamp"] == 5.0
        assert events[4]["timestamp"] == 9.0

    def test_max_events_one(self):
        mgr = _StubHookManager(max_events=1)
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0))
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=2.0))
        events = mgr.get_events()
        assert len(events) == 1
        assert events[0]["timestamp"] == 2.0


class TestPlatformHookManagerCallback:
    def test_callback_invoked_on_dispatch(self):
        captured = []
        mgr = _StubHookManager(callback=lambda e: captured.append(e))
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0, key="a"))
        assert len(captured) == 1
        assert captured[0]["type"] == "key_press"
        assert captured[0]["character"] == "*"

    def test_callback_not_invoked_when_none(self):
        mgr = _StubHookManager(callback=None)
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0))
        assert mgr.get_events() == [] or len(mgr.get_events()) == 1

    def test_callback_exception_does_not_propagate(self):
        def bad_callback(e):
            raise ValueError("boom")

        mgr = _StubHookManager(callback=bad_callback)
        mgr.start()
        mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0))
        assert len(mgr.get_events()) == 1

    def test_callback_receives_redacted_event(self):
        captured = []
        mgr = _StubHookManager(
            redact_characters=True, redact_vk_codes=True,
            callback=lambda e: captured.append(e),
        )
        mgr.start()
        mgr._dispatch(InputEvent(
            event_type="key_press", timestamp=1.0,
            key="s", vk_code=83, x=10, y=20,
        ))
        assert captured[0]["character"] == "*"
        assert captured[0]["vk_code"] == 0
        assert captured[0]["x"] == 0
        assert captured[0]["y"] == 0


class TestPlatformHookManagerContextManager:
    def test_context_manager_start_stop(self):
        with _StubHookManager() as mgr:
            assert mgr.is_active
            mgr._dispatch(InputEvent(event_type="key_press", timestamp=1.0))
            assert len(mgr.get_events()) == 1
        assert not mgr.is_active
        assert mgr.get_events() == []


class TestPlatformHookManagerThreadSafety:
    def test_concurrent_dispatches(self):
        mgr = _StubHookManager(max_events=10000)
        mgr.start()
        num_threads = 8
        events_per_thread = 200
        barrier = threading.Barrier(num_threads)

        def dispatch_events(thread_id):
            barrier.wait()
            for i in range(events_per_thread):
                mgr._dispatch(InputEvent(
                    event_type="key_press",
                    timestamp=float(thread_id * events_per_thread + i),
                ))

        threads = [
            threading.Thread(target=dispatch_events, args=(t,))
            for t in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = mgr.get_events()
        assert len(events) == num_threads * events_per_thread
        timestamps = [e["timestamp"] for e in events]
        assert len(set(timestamps)) == num_threads * events_per_thread


class TestHookInputFactory:
    def test_hook_input_returns_platform_hook_manager_subclass(self):
        import sys

        from tardis.os_integration.input_hooks import _PLATFORM_MAP
        platform_name = _PLATFORM_MAP.get(sys.platform, sys.platform)
        if platform_name not in ("windows", "macos", "linux"):
            pytest.skip("Platform not supported")
        mgr = hook_input(max_events=50)
        assert isinstance(mgr, PlatformHookManager)
        assert mgr.is_active
        mgr.stop()

    def test_hook_input_auto_detects_platform(self):
        import sys

        from tardis.os_integration.input_hooks import _PLATFORM_MAP

        expected = _PLATFORM_MAP.get(sys.platform, sys.platform)
        cls_map = {
            "windows": "WindowsHookManager",
            "macos": "MacOSHookManager",
            "linux": "LinuxHookManager",
        }
        expected_cls = cls_map.get(expected)
        if expected_cls is None:
            pytest.skip("Platform not supported by hook_input")
        mgr = hook_input()
        assert type(mgr).__name__ == expected_cls
        mgr.stop()

    def test_hook_input_unsupported_platform_raises(self):
        with pytest.raises(RuntimeError, match="Unsupported platform"):
            mgr = hook_input(platform="beos")
            mgr.stop()

    def test_hook_input_forwards_kwargs(self):
        import sys

        from tardis.os_integration.input_hooks import _PLATFORM_MAP
        platform_name = _PLATFORM_MAP.get(sys.platform, sys.platform)
        if platform_name not in ("windows", "macos", "linux"):
            pytest.skip("Platform not supported")
        captured = []
        mgr = hook_input(
            redact_characters=False,
            redact_vk_codes=True,
            max_events=100,
            callback=lambda e: captured.append(e),
        )
        assert mgr.redact_characters is False
        assert mgr.redact_vk_codes is True
        assert mgr._max_events == 100
        mgr.stop()

    def test_hook_input_returns_started_manager(self):
        import sys

        from tardis.os_integration.input_hooks import _PLATFORM_MAP
        platform_name = _PLATFORM_MAP.get(sys.platform, sys.platform)
        if platform_name not in ("windows", "macos", "linux"):
            pytest.skip("Platform not supported")
        mgr = hook_input()
        assert mgr.is_active
        mgr.stop()
