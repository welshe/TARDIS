"""Tests for Win32 keyboard/mouse hooks (capture/win32_hooks.py)."""

import sys

import pytest

from tardis.capture.win32_hooks import (
    MOUSE_EVENT_NAMES,
    VK_NAMES,
    _mouse_event_name,
    _vk_to_name,
)

# The module also defines constants and ctypes structures that are always importable
# but Win32HookManager itself requires Windows.


class TestVKNames:
    def test_known_key(self):
        assert _vk_to_name(0x0D) == "Enter"
        assert _vk_to_name(0x1B) == "Escape"
        assert _vk_to_name(0x20) == "Space"
        assert _vk_to_name(0x70) == "F1"

    def test_unknown_key(self):
        name = _vk_to_name(0x999)
        assert "VK_" in name


class TestMouseEventName:
    def test_known_event(self):
        assert _mouse_event_name(0x0200) == "move"
        assert _mouse_event_name(0x0201) == "left_down"

    def test_unknown_event(self):
        name = _mouse_event_name(0x9999)
        assert "mouse_" in name


class TestWin32HookManager:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_init(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager()
        assert mgr._buffer.maxlen == 10000

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_custom_buffer_size(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager(buffer_size=500)
        assert mgr._buffer.maxlen == 500

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_get_events_empty(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager()
        events = mgr.get_events()
        assert events == []

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_get_recent(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager()
        events = mgr.get_recent(10)
        assert events == []

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_dispatch_stores_event(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager()
        event = {"type": "key_down", "vk_code": 0x41, "character": "a"}
        mgr._dispatch(event)
        events = mgr.get_events()
        assert len(events) == 1

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_dispatch_redact_characters(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager(redact_characters=True)
        event = {"type": "key_down", "character": "s", "vk_code": 0x53}
        mgr._dispatch(event)
        events = mgr.get_events()
        assert events[0]["character"] == "*"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_dispatch_redact_vk_codes(self):
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager(redact_vk_codes=True)
        event = {"type": "key_down", "vk_code": 0x41, "scan_code": 30}
        mgr._dispatch(event)
        events = mgr.get_events()
        assert events[0]["vk_code"] == 0
        assert events[0]["scan_code"] == 0

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_dispatch_calls_callback(self):
        captured = []
        from tardis.capture.win32_hooks import Win32HookManager

        mgr = Win32HookManager(on_event=lambda e: captured.append(e))
        mgr._dispatch({"type": "key_down"})
        assert len(captured) == 1

    def test_raises_on_non_windows(self):
        if sys.platform != "win32":
            from tardis.capture.win32_hooks import Win32HookManager

            with pytest.raises(RuntimeError, match="only available on Windows"):
                Win32HookManager()


class TestConstants:
    def test_vk_names_has_common_keys(self):
        assert 0x0D in VK_NAMES  # Enter
        assert 0x1B in VK_NAMES  # Escape
        assert 0x20 in VK_NAMES  # Space

    def test_mouse_event_names_has_common(self):
        assert 0x0201 in MOUSE_EVENT_NAMES  # left_down
        assert 0x0200 in MOUSE_EVENT_NAMES  # move
