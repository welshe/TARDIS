"""
Low-level Win32 keyboard and mouse hooks via SetWindowsHookEx.
Captures raw OS-level input events for deterministic replay of
computer-use agent interactions.

This is the key differentiator — most open-source computer-use agent
frameworks only log API calls. TARDIS logs exactly what keys were
pressed and where the mouse moved/clicked at the OS level.
"""
import ctypes
import ctypes.wintypes
import threading
import time
import sys
from typing import Optional, Callable, Any
from collections import deque

from ..models import StepType

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
    0x01: "LButton", 0x02: "RButton", 0x03: "Cancel", 0x04: "MButton",
    0x08: "Backspace", 0x09: "Tab", 0x0C: "Clear", 0x0D: "Enter",
    0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause",
    0x14: "CapsLock", 0x1B: "Escape", 0x20: "Space", 0x21: "PageUp",
    0x22: "PageDown", 0x23: "End", 0x24: "Home", 0x25: "Left",
    0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2C: "PrintScreen",
    0x2D: "Insert", 0x2E: "Delete", 0x5B: "LWin", 0x5C: "RWin",
    0x5D: "Apps", 0x6A: "Multiply", 0x6B: "Add", 0x6D: "Subtract",
    0x6E: "Decimal", 0x6F: "Divide", 0x70: "F1", 0x71: "F2",
    0x72: "F3", 0x73: "F4", 0x74: "F5", 0x75: "F6", 0x76: "F7",
    0x77: "F8", 0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0x90: "NumLock", 0x91: "ScrollLock", 0xA0: "LShift",
    0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl", 0xA4: "LAlt",
    0xA5: "RAlt",
}

MOUSE_EVENT_NAMES = {
    WM_LBUTTONDOWN: "left_down", WM_LBUTTONUP: "left_up",
    WM_RBUTTONDOWN: "right_down", WM_RBUTTONUP: "right_up",
    WM_MBUTTONDOWN: "middle_down", WM_MBUTTONUP: "middle_up",
    WM_MOUSEMOVE: "move", WM_MOUSEWHEEL: "wheel_vertical",
    WM_MOUSEHWHEEL: "wheel_horizontal",
}

KERNEL32 = ctypes.windll.kernel32
USER32 = ctypes.windll.user32

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

def _vk_to_char(vk_code: int, shift: bool = False) -> Optional[str]:
    buf = ctypes.create_unicode_buffer(16)
    sc = ctypes.windll.user32.MapVirtualKeyW(vk_code, 0)
    result = ctypes.windll.user32.ToUnicode(vk_code, sc, None, buf, 16, 0)
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
        on_event: Optional[Callable[[dict], Any]] = None,
        buffer_size: int = 10000,
    ):
        if sys.platform != "win32":
            raise RuntimeError("Win32HookManager is only available on Windows")

        self.on_event = on_event
        self._buffer: deque = deque(maxlen=buffer_size)
        self._keyboard_hook: Optional[int] = None
        self._mouse_hook: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._keyboard_proc = HOOKPROC(self._low_level_keyboard_proc)
        self._mouse_proc = HOOKPROC(self._low_level_mouse_proc)

    def start(self) -> "Win32HookManager":
        if self._running.is_set():
            return self
        self._running.set()
        self._thread = threading.Thread(target=self._message_loop, daemon=True, name="tardis-win32-hooks")
        self._thread.start()
        return self

    def stop(self):
        if not self._running.is_set():
            return
        self._running.clear()
        if self._keyboard_hook:
            USER32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = None
        if self._mouse_hook:
            USER32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
        USER32.PostThreadMessageW(KERNEL32.GetCurrentThreadId(), 0x0012, 0, 0)  # WM_QUIT

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
        with self._lock:
            self._buffer.append(event)
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _message_loop(self):
        thread_id = KERNEL32.GetCurrentThreadId()

        self._keyboard_hook = USER32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._keyboard_proc,
            HINSTANCE(0),
            0,
        )
        self._mouse_hook = USER32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._mouse_proc,
            HINSTANCE(0),
            0,
        )

        if not self._keyboard_hook:
            raise OSError(f"SetWindowsHookEx(WH_KEYBOARD_LL) failed: {KERNEL32.GetLastError()}")
        if not self._mouse_hook:
            raise OSError(f"SetWindowsHookEx(WH_MOUSE_LL) failed: {KERNEL32.GetLastError()}")

        msg = MSG()
        p_msg = ctypes.pointer(msg)

        while self._running.is_set():
            ret = USER32.GetMessageW(p_msg, None, 0, 0)
            if ret in (0, -1):
                break
            USER32.TranslateMessage(p_msg)
            USER32.DispatchMessageW(p_msg)

        if self._keyboard_hook:
            USER32.UnhookWindowsHookEx(self._keyboard_hook)
        if self._mouse_hook:
            USER32.UnhookWindowsHookEx(self._mouse_hook)

    def _low_level_keyboard_proc(self, nCode: int, wParam: WPARAM, lParam: LPARAM) -> LRESULT:
        if nCode >= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            flags = kb.flags
            is_extended = bool(flags & 0x01)
            was_down = bool(flags & 0x80)
            is_injected = bool(flags & 0x10)

            event_type = "key_down" if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN) else "key_up"
            vk_name = _vk_to_name(kb.vkCode)

            shift_state = USER32.GetAsyncKeyState(0x10) & 0x8000
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

        return USER32.CallNextHookEx(0, nCode, wParam, lParam)

    def _low_level_mouse_proc(self, nCode: int, wParam: WPARAM, lParam: LPARAM) -> LRESULT:
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

        return USER32.CallNextHookEx(0, nCode, wParam, lParam)


def hook_keyboard_and_mouse(
    recorder=None,
    buffer_size: int = 10000,
) -> Win32HookManager:
    """
    Convenience factory that starts Win32 keyboard + mouse hooks and integrates
    with the TARDIS recorder.

    Pass a Recorder instance and all captured events are automatically logged
    as raw_input Steps. Returns the manager so you can stop it later.
    """
    mgr = Win32HookManager(buffer_size=buffer_size)

    if recorder is not None:
        def _log(event):
            from ..models import Step, StepType
            recorder.log(
                StepType.raw_input,
                input={"hook": "win32"},
                output=event,
                metadata={"source": "win32_hook", "event_type": event.get("type")},
            )

        mgr.on_event = _log

    mgr.start()
    return mgr
