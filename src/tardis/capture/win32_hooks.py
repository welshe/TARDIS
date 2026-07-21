"""
Low-level Win32 keyboard and mouse hooks via SetWindowsHookEx.
Captures raw OS-level input events for deterministic replay of
computer-use agent interactions.

This is the key differentiator — most open-source computer-use agent
frameworks only log API calls. TARDIS logs exactly what keys were
pressed and where the mouse moved/clicked at the OS level.

SECURITY NOTICE: This captures system-wide keyboard and mouse input,
including passwords and sensitive text. Requires explicit opt-in.
PII redaction is available but not guaranteed to catch all cases.
Never enable in production without user consent.
"""

import ctypes
import ctypes.wintypes
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E

VK_NAMES = {
    0x01: "LButton",
    0x02: "RButton",
    0x03: "Cancel",
    0x04: "MButton",
    0x08: "Backspace",
    0x09: "Tab",
    0x0C: "Clear",
    0x0D: "Enter",
    0x10: "Shift",
    0x11: "Ctrl",
    0x12: "Alt",
    0x13: "Pause",
    0x14: "CapsLock",
    0x1B: "Escape",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2D: "Insert",
    0x2E: "Delete",
    0x5B: "LWin",
    0x5C: "RWin",
    0x5D: "Apps",
    0x6A: "Multiply",
    0x6B: "Add",
    0x6D: "Subtract",
    0x6E: "Decimal",
    0x6F: "Divide",
    0x70: "F1",
    0x71: "F2",
    0x72: "F3",
    0x73: "F4",
    0x74: "F5",
    0x75: "F6",
    0x76: "F7",
    0x77: "F8",
    0x78: "F9",
    0x79: "F10",
    0x7A: "F11",
    0x7B: "F12",
    0x90: "NumLock",
    0x91: "ScrollLock",
    0xA0: "LShift",
    0xA1: "RShift",
    0xA2: "LCtrl",
    0xA3: "RCtrl",
    0xA4: "LAlt",
    0xA5: "RAlt",
}

MOUSE_EVENT_NAMES = {
    WM_LBUTTONDOWN: "left_down",
    WM_LBUTTONUP: "left_up",
    WM_RBUTTONDOWN: "right_down",
    WM_RBUTTONUP: "right_up",
    WM_MBUTTONDOWN: "middle_down",
    WM_MBUTTONUP: "middle_up",
    WM_MOUSEMOVE: "move",
    WM_MOUSEWHEEL: "wheel_vertical",
    WM_MOUSEHWHEEL: "wheel_horizontal",
}

# Windows-specific constants - initialized lazily to avoid import errors on non-Windows
KERNEL32 = None
USER32 = None


def _init_win32():
    """Initialize Windows DLLs. Only call on Windows."""
    global KERNEL32, USER32
    if KERNEL32 is None:
        KERNEL32 = ctypes.windll.kernel32
        USER32 = ctypes.windll.user32
    return KERNEL32, USER32


HINSTANCE = ctypes.wintypes.HINSTANCE
LPARAM = ctypes.wintypes.LPARAM
WPARAM = ctypes.wintypes.WPARAM
LRESULT = LPARAM
ULONG_PTR = ctypes.c_size_t

HOOKPROC = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.wintypes.UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", ctypes.wintypes.DWORD),
        ("pt", POINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


def _vk_to_name(vk_code: int) -> str:
    return VK_NAMES.get(vk_code, f"VK_{vk_code:#04x}")


def _vk_to_char(vk_code: int, shift: bool = False) -> str | None:
    buf = ctypes.create_unicode_buffer(16)
    _, user32 = _init_win32()
    sc = user32.MapVirtualKeyW(vk_code, 0)
    # ToUnicode requires a 256-byte keyboard state array; pass a zeroed buffer
    # so the current keyboard layout's default mapping is used without
    # interference from leftover modifier state.
    kb_state = (ctypes.c_char * 256)()
    result = user32.ToUnicode(vk_code, sc, kb_state, buf, 16, 0)
    if result > 0:
        return buf.value
    return None


def _mouse_event_name(msg: int) -> str:
    return MOUSE_EVENT_NAMES.get(msg, f"mouse_{msg:#06x}")


class Win32HookManager:
    """
    Manages low-level Win32 keyboard and mouse hooks.

    Runs a dedicated thread with a Windows message pump. All keyboard and
    mouse events are captured at the OS level before they reach any
    application. This provides ground-truth input logging for computer-use
    agents — you can see exactly what keys the agent pressed and exactly
    where the mouse moved and clicked.

    Usage:
        mgr = Win32HookManager(on_event=recorder.log)
        mgr.start()
        # ... agent runs ...
        mgr.stop()
    """

    def __init__(
        self,
        on_event: Callable[[dict], Any] | None = None,
        buffer_size: int = 10000,
        redact_characters: bool = False,
        redact_vk_codes: bool = False,
    ):
        if sys.platform != "win32":
            raise RuntimeError("Win32HookManager is only available on Windows")

        self.on_event = on_event
        self._buffer: deque = deque(maxlen=buffer_size)
        self._keyboard_hook: int | None = None
        self._mouse_hook: int | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._keyboard_proc = HOOKPROC(self._low_level_keyboard_proc)
        self._mouse_proc = HOOKPROC(self._low_level_mouse_proc)
        self._hook_thread_id: int | None = None
        self._redact_characters = redact_characters
        self._redact_vk_codes = redact_vk_codes

    def start(self) -> "Win32HookManager":
        if self._running.is_set():
            return self
        self._running.set()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._message_loop, daemon=True, name="tardis-win32-hooks"
        )
        self._thread.start()
        # Give the thread up to 2 seconds to install the hooks; if it failed,
        # surface the error instead of reporting success with broken state.
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._startup_error is not None:
            self._running.clear()
            raise self._startup_error
        return self

    def stop(self):
        if not self._running.is_set():
            return
        self._running.clear()
        k32, u32 = _init_win32()
        if self._keyboard_hook:
            u32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = None
        if self._mouse_hook:
            u32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        # Post WM_QUIT to the hook thread's message queue (not the calling thread)
        if self._hook_thread_id is not None:
            u32.PostThreadMessageW(self._hook_thread_id, 0x0012, 0, 0)  # WM_QUIT
        # Zero the event buffer to prevent leaked key positions after stop
        with self._lock:
            self._buffer.clear()

    def get_events(self, clear: bool = False) -> list[dict]:
        with self._lock:
            events = list(self._buffer)
            if clear:
                self._buffer.clear()
        return events

    def get_recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            buf = list(self._buffer)
            return buf[-n:] if len(buf) > n else buf

    def _dispatch(self, event: dict):
        if event.get("type", "").startswith("key_"):
            needs_copy = (
                self._redact_characters
                and "character" in event
                and event["character"] is not None
            ) or self._redact_vk_codes
            if needs_copy:
                event = dict(event)
            if (
                self._redact_characters
                and "character" in event
                and event["character"] is not None
            ):
                event["character"] = "*"
            if self._redact_vk_codes:
                event["vk_code"] = 0
                event["scan_code"] = 0
                event["vk_name"] = "VK_REDACTED"
        with self._lock:
            self._buffer.append(event)
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _message_loop(self):
        k32, u32 = _init_win32()
        # Store the hook thread ID for proper WM_QUIT posting in stop()
        self._hook_thread_id = k32.GetCurrentThreadId()

        try:
            self._keyboard_hook = u32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._keyboard_proc,
                HINSTANCE(0),
                0,
            )
            self._mouse_hook = u32.SetWindowsHookExW(
                WH_MOUSE_LL,
                self._mouse_proc,
                HINSTANCE(0),
                0,
            )

            if not self._keyboard_hook:
                raise OSError(
                    f"SetWindowsHookEx(WH_KEYBOARD_LL) failed: {k32.GetLastError()}"
                )
            if not self._mouse_hook:
                raise OSError(
                    f"SetWindowsHookEx(WH_MOUSE_LL) failed: {k32.GetLastError()}"
                )
        except OSError as exc:
            # Surface installation failure to start() instead of leaving the
            # manager in a broken, hooks-never-installed state.
            self._startup_error = exc
            self._running.clear()
            return

        msg = MSG()
        p_msg = ctypes.pointer(msg)

        while self._running.is_set():
            ret = u32.GetMessageW(p_msg, None, 0, 0)
            if ret in (0, -1):
                break
            u32.TranslateMessage(p_msg)
            u32.DispatchMessageW(p_msg)

        if self._keyboard_hook:
            u32.UnhookWindowsHookEx(self._keyboard_hook)
        if self._mouse_hook:
            u32.UnhookWindowsHookEx(self._mouse_hook)

    def _low_level_keyboard_proc(
        self, nCode: int, wParam: WPARAM, lParam: LPARAM  # noqa: N803
    ) -> LRESULT:
        if nCode >= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            flags = kb.flags
            is_extended = bool(flags & 0x01)
            was_down = bool(flags & 0x80)
            is_injected = bool(flags & 0x10)

            event_type = (
                "key_down" if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN) else "key_up"
            )
            vk_name = _vk_to_name(kb.vkCode)

            _, user32 = _init_win32()
            shift_state = user32.GetAsyncKeyState(0x10) & 0x8000
            char_val = None
            if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                char_val = _vk_to_char(kb.vkCode, bool(shift_state))

            event = {
                "type": event_type,
                "vk_code": kb.vkCode,
                "vk_name": vk_name,
                "scan_code": kb.scanCode,
                "character": char_val,
                "is_extended": is_extended,
                "was_down": was_down,
                "is_injected": is_injected,
                "timestamp": time.time(),
            }
            self._dispatch(event)

        _, user32 = _init_win32()
        return user32.CallNextHookEx(0, nCode, wParam, lParam)

    def _low_level_mouse_proc(
        self, nCode: int, wParam: WPARAM, lParam: LPARAM  # noqa: N803
    ) -> LRESULT:
        if nCode >= 0:
            ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            is_injected = bool(ms.flags & 0x01)

            event = {
                "type": _mouse_event_name(wParam),
                "x": ms.pt.x,
                "y": ms.pt.y,
                "mouse_data": ms.mouseData,
                "is_injected": is_injected,
                "timestamp": time.time(),
            }

            if wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                delta = ctypes.c_short(ms.mouseData >> 16).value
                event["wheel_delta"] = delta

            self._dispatch(event)

        _, user32 = _init_win32()
        return user32.CallNextHookEx(0, nCode, wParam, lParam)


def hook_keyboard_and_mouse(
    recorder=None,
    buffer_size: int = 10000,
    redact_characters: bool = True,
    redact_vk_codes: bool = False,
) -> Win32HookManager:
    """
    Convenience factory that starts Win32 keyboard + mouse hooks and integrates
    with the TARDIS recorder.

    Pass a Recorder instance and all captured events are automatically logged
    as raw_input Steps. Returns the manager so you can stop it later.

    Args:
        redact_characters: If True, keyboard character output is replaced with
            '*' before storage. Key names and virtual codes are preserved.
            Default True to prevent password leakage.
        redact_vk_codes: If True, vk_code and scan_code are zeroed to prevent
            password reconstruction from key positions. Default False.
    """
    mgr = Win32HookManager(
        buffer_size=buffer_size,
        redact_characters=redact_characters,
        redact_vk_codes=redact_vk_codes,
    )

    if recorder is not None:

        def _log(event):
            from ..models import StepType

            recorder.log(
                StepType.raw_input,
                input={"hook": "win32"},
                output=event,
                metadata={"source": "win32_hook", "event_type": event.get("type")},
            )

        mgr.on_event = _log

    mgr.start()
    return mgr
