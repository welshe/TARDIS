from __future__ import annotations

import abc
import ctypes
import ctypes.util
import logging
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)
_PLATFORM_MAP = {"win32": "windows", "darwin": "macos", "linux": "linux"}


@dataclass
class InputEvent:
    event_type: str
    timestamp: float
    key: str | None = None
    vk_code: int | None = None
    x: int | None = None
    y: int | None = None
    button: str | None = None
    modifiers: list[str] = field(default_factory=list)
    platform: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": self.event_type,
            "timestamp": self.timestamp,
            "modifiers": list(self.modifiers),
            "platform": self.platform,
        }
        if self.key is not None:
            d["character"] = self.key
        if self.vk_code is not None:
            d["vk_code"] = self.vk_code
        if self.x is not None:
            d["x"] = self.x
        if self.y is not None:
            d["y"] = self.y
        if self.button is not None:
            d["button"] = self.button
        return d


class PlatformHookManager(abc.ABC):
    def __init__(
        self,
        recorder: Any = None,
        redact_characters: bool = True,
        redact_vk_codes: bool = False,
        callback: Callable[[dict], Any] | None = None,
        max_events: int = 10000,
    ):
        self.recorder = recorder
        self.redact_characters = redact_characters
        self.redact_vk_codes = redact_vk_codes
        # Validate max_events to prevent deque crash on negative/zero values
        if not isinstance(max_events, int) or max_events < 1:
            raise ValueError(f"max_events must be a positive integer, got {max_events!r}")
        if max_events > 1_000_000:
            raise ValueError(f"max_events too large ({max_events}), max is 1_000_000")
        self._events: deque[dict] = deque(maxlen=max_events)
        self._lock = threading.RLock()
        self._active = False
        self._max_events = max_events
        self._callback = callback

    @abc.abstractmethod
    def _install_hooks(self) -> None: ...

    @abc.abstractmethod
    def _uninstall_hooks(self) -> None: ...

    def start(self) -> PlatformHookManager:
        if self._active:
            return self
        self._install_hooks()
        self._active = True
        return self

    def stop(self) -> None:
        if not self._active:
            return
        self._uninstall_hooks()
        self._active = False
        with self._lock:
            self._events.clear()

    @property
    def is_active(self) -> bool:
        return self._active

    def get_events(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            events = list(self._events)
        return events[-limit:] if limit is not None else events

    def get_recent(self, seconds: float) -> list[dict]:
        cutoff = time.time() - seconds
        with self._lock:
            return [e for e in self._events if e.get("timestamp", 0) >= cutoff]

    def _dispatch(self, event: InputEvent) -> None:
        d = event.to_dict()
        needs_copy = (
            (self.redact_characters and d.get("character") is not None)
            or self.redact_vk_codes
        )
        if needs_copy:
            d = dict(d)
        if self.redact_characters and d.get("character") is not None:
            d["character"] = "*"
        if self.redact_vk_codes:
            d["vk_code"] = 0
            d["x"] = 0
            d["y"] = 0
        with self._lock:
            self._events.append(d)
        if self._callback is not None:
            try:
                self._callback(d)
            except Exception:
                pass
        if self.recorder is not None:
            try:
                from ..models import StepType
                self.recorder.log(
                    StepType.raw_input,
                    input={"hook": event.platform},
                    output=d,
                    metadata={"source": f"{event.platform}_hook", "event_type": event.event_type},
                )
            except Exception:
                pass

    def __enter__(self) -> PlatformHookManager:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


class WindowsHookManager(PlatformHookManager):
    def _install_hooks(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsHookManager is only available on Windows")
        from ..capture.win32_hooks import Win32HookManager
        self._inner = Win32HookManager(
            on_event=self._on_win32_event,
            buffer_size=self._max_events,
            redact_characters=self.redact_characters,
            redact_vk_codes=self.redact_vk_codes,
        )
        self._inner.start()

    def _uninstall_hooks(self) -> None:
        inner = getattr(self, "_inner", None)
        if inner is not None:
            inner.stop()

    def _on_win32_event(self, event: dict) -> None:
        raw = event.get("type", "")
        mapped = {
            "key_down": "key_press", "key_up": "key_release",
            "left_down": "mouse_click", "right_down": "mouse_click",
            "middle_down": "mouse_click", "move": "mouse_move",
            "wheel_vertical": "mouse_scroll", "wheel_horizontal": "mouse_scroll",
        }.get(raw, raw)
        button = None
        if "left" in raw:
            button = "left"
        elif "right" in raw:
            button = "right"
        elif "middle" in raw:
            button = "middle"
        self._dispatch(InputEvent(
            event_type=mapped, timestamp=event.get("timestamp", time.time()),
            key=event.get("character"), vk_code=event.get("vk_code"),
            x=event.get("x"), y=event.get("y"), button=button,
            modifiers=_win32_modifiers(event.get("vk_code")),
            platform="windows",
        ))


def _win32_modifiers(vk: int | None) -> list[str]:
    if vk is None:
        return []
    mods: list[str] = []
    if vk in (0x10, 0xA0, 0xA1):
        mods.append("shift")
    if vk in (0x11, 0xA2, 0xA3):
        mods.append("ctrl")
    if vk in (0x12, 0xA4, 0xA5):
        mods.append("alt")
    if vk in (0x5B, 0x5C):
        mods.append("meta")
    return mods


_MAC_CG_MODIFIER_MAP = {0x00010000: "shift", 0x00040000: "ctrl", 0x00080000: "alt", 0x00100000: "meta"}


def _mac_modifiers_from_flags(flags: int) -> list[str]:
    return [name for bit, name in _MAC_CG_MODIFIER_MAP.items() if flags & bit]


_MAC_KEYCODE_MAP: dict[int, str] = {
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
    8: "c", 9: "v", 10: "[", 11: "]", 30: "1", 31: "2", 32: "3",
    33: "4", 34: "6", 35: "5", 36: "enter", 39: "'", 41: ";",
    42: "\\", 43: ",", 44: "/", 45: "n", 46: "m", 48: "tab",
    49: "space", 50: "left_shift", 51: "backspace", 53: "escape",
    54: "right_shift", 55: "ctrl", 56: "alt", 58: "caps_lock",
    96: "f5", 97: "f6", 98: "f7", 99: "f3", 100: "f8", 101: "f9",
    103: "f11", 109: "f10", 111: "f12", 113: "f4", 118: "f2",
    119: "f1", 120: "left", 121: "right", 122: "down", 123: "up",
}


def _mac_cg_loc(_cg: Any, event: Any) -> tuple[int | None, int | None]:
    loc = _cg.CGEventGetLocation(event)
    return (int(loc.x) if hasattr(loc, "x") else None, int(loc.y) if hasattr(loc, "y") else None)


def _load_quartz() -> Any:
    try:
        import Quartz  # type: ignore[import-untyped]
        return Quartz
    except ImportError:
        pass
    for p in (
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
        "/System/Library/Frameworks/Quartz.framework/Quartz",
    ):
        try:
            return ctypes.cdll.LoadLibrary(p)
        except OSError:
            continue
    raise OSError("Quartz/CoreGraphics framework not available")


def _load_core_foundation() -> Any:
    try:
        import CoreFoundation  # type: ignore[import-untyped]
        return CoreFoundation
    except ImportError:
        pass
    return ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )


class MacOSHookManager(PlatformHookManager):
    _POLL_INTERVAL = 0.02
    _EVENT_MASK = (
        (1 << 10) | (1 << 11) | (1 << 5) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 22)
    )

    def _install_hooks(self) -> None:
        self._tap_ref: Any = None
        self._run_loop_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        if not self._try_event_tap():
            _logger.warning(
                "macOS event tap unavailable (need Accessibility permissions). "
                "Falling back to polling-based input capture."
            )
            self._poll_thread = threading.Thread(
                target=self._poll_loop, daemon=True, name="tardis-macos-poll"
            )
            self._poll_thread.start()

    def _uninstall_hooks(self) -> None:
        self._stop_event.set()
        if self._tap_ref is not None:
            try:
                _load_quartz().CGEventTapEnable(self._tap_ref, False)
            except Exception:
                pass
            self._tap_ref = None
        for t in (self._poll_thread, self._run_loop_thread):
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
        self._poll_thread = self._run_loop_thread = None

    def _try_event_tap(self) -> bool:
        try:
            _cg = _load_quartz()
            _cf = _load_core_foundation()
        except OSError:
            return False
        try:
            tap = _cg.CGEventTapCreate(
                _cg.kCGSessionEventTap, _cg.kCGHeadInsertEventTap,
                _cg.kCGEventTapOptionListenOnly, self._EVENT_MASK,
                _macos_cocoa_callback, None,
            )
            if not tap:
                return False
            self._tap_ref = tap
            _set_macos_callback_target(self)
            src = _cg.CFMachPortCreateRunLoopSource(None, tap, 0)
            rl = _cf.CFRunLoopGetCurrent()
            _cf.CFRunLoopAddSource(rl, src, _cf.kCFRunLoopDefaultMode)
            _cg.CGEventTapEnable(tap, True)
            self._run_loop_thread = threading.Thread(
                target=lambda: _cf.CFRunLoopRun(), daemon=True, name="tardis-macos-runloop"
            )
            self._run_loop_thread.start()
            return True
        except Exception as exc:
            _logger.debug("Event tap creation failed: %s", exc)
            return False

    def _poll_loop(self) -> None:
        try:
            _cg = _load_quartz()
        except OSError:
            return
        prev_flags = 0
        while not self._stop_event.is_set():
            try:
                ev = _cg.CGEventCreate(None)
                flags = _cg.CGEventGetFlags(ev)
                changed = flags ^ prev_flags
                if changed:
                    now = time.time()
                    for bit, name in _MAC_CG_MODIFIER_MAP.items():
                        if changed & bit:
                            self._dispatch(InputEvent(
                                event_type="key_press" if (flags & bit) else "key_release",
                                timestamp=now, key=name,
                                modifiers=_mac_modifiers_from_flags(flags), platform="macos",
                            ))
                    prev_flags = flags
                x, y = _mac_cg_loc(_cg, ev)
                self._dispatch(InputEvent(
                    event_type="mouse_move", timestamp=time.time(),
                    x=x, y=y, modifiers=_mac_modifiers_from_flags(flags), platform="macos",
                ))
            except Exception:
                pass
            self._stop_event.wait(self._POLL_INTERVAL)


_macos_callback_target: PlatformHookManager | None = None
_macos_callback_lock = threading.Lock()


def _set_macos_callback_target(mgr: PlatformHookManager) -> None:
    global _macos_callback_target
    with _macos_callback_lock:
        _macos_callback_target = mgr


def _macos_cocoa_callback(
    proxy: Any, cg_event_type: ctypes.c_void_p,
    event: ctypes.c_void_p, refcon: ctypes.c_void_p,
) -> ctypes.c_void_p:
    try:
        with _macos_callback_lock:
            mgr = _macos_callback_target
        if mgr is None:
            return event
        _cg = _load_quartz()
        cg_type = ctypes.cast(cg_event_type, ctypes.POINTER(ctypes.c_long)).contents.value if cg_event_type else 0
        now = time.time()
        mods = _mac_modifiers_from_flags(_cg.CGEventGetFlags(event))
        if cg_type in (10, 11):
            kc = _cg.CGEventGetIntegerValueField(event, 10)
            mgr._dispatch(InputEvent(
                event_type="key_press" if cg_type == 10 else "key_release",
                timestamp=now, key=_MAC_KEYCODE_MAP.get(kc, f"key_{kc}"), vk_code=kc,
                modifiers=mods, platform="macos",
            ))
        elif cg_type in (1, 2, 3, 4):
            x, y = _mac_cg_loc(_cg, event)
            mgr._dispatch(InputEvent(
                event_type="mouse_click", timestamp=now, x=x, y=y,
                button="left" if cg_type in (1, 2) else "right",
                modifiers=mods, platform="macos",
            ))
        elif cg_type == 5:
            x, y = _mac_cg_loc(_cg, event)
            mgr._dispatch(InputEvent(
                event_type="mouse_move", timestamp=now, x=x, y=y,
                modifiers=mods, platform="macos",
            ))
        elif cg_type == 22:
            x, y = _mac_cg_loc(_cg, event)
            ie = InputEvent(
                event_type="mouse_scroll", timestamp=now, x=x, y=y,
                modifiers=mods, platform="macos",
            )
            d = ie.to_dict()
            d["delta"] = _cg.CGEventGetIntegerValueField(event, 11)
            mgr._dispatch(ie)
    except Exception:
        pass
    return event


_X11_KEYCODE_MAP: dict[int, str] = {
    9: "escape", 10: "1", 11: "2", 12: "3", 13: "4", 14: "5",
    15: "6", 16: "7", 17: "8", 18: "9", 19: "0",
    22: "backspace", 23: "tab", 24: "q", 25: "w", 26: "e", 27: "r",
    28: "t", 29: "y", 30: "u", 31: "i", 32: "o", 33: "p",
    36: "enter", 37: "ctrl", 38: "a", 39: "s", 40: "d", 41: "f",
    42: "g", 43: "h", 44: "j", 45: "k", 46: "l", 49: "space",
    50: "shift", 54: "shift", 55: "ctrl", 56: "alt",
    59: "f1", 60: "f2", 61: "f3", 62: "f4", 63: "f5", 64: "f6",
    65: "f7", 66: "f8", 67: "f9", 68: "f10", 71: "f11", 72: "f12",
    110: "home", 111: "up", 112: "page_up", 113: "left", 114: "right",
    115: "end", 116: "down", 117: "page_down", 119: "delete",
    133: "meta", 134: "meta",
}
_X11_MOUSE_BUTTONS = {1: "left", 2: "middle", 3: "right"}


class _XRecordInterceptData(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_long),
        ("category", ctypes.c_int),
        ("data_len", ctypes.c_int),
        ("data", ctypes.c_byte * 32),
    ]


def _load_x11() -> Any:
    return ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")


class LinuxHookManager(PlatformHookManager):
    _POLL_INTERVAL = 0.02

    def _install_hooks(self) -> None:
        self._backend: str | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._evdev_devices: list[Any] = []
        self._x11_display = self._x11_ctx = None
        if self._try_evdev():
            self._backend = "evdev"
        elif self._try_x11():
            self._backend = "x11"
        else:
            _logger.warning("No input hook backend available on Linux")
            return
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="tardis-linux-input"
        )
        self._reader_thread.start()

    def _uninstall_hooks(self) -> None:
        self._stop_event.set()
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        self._reader_thread = None
        for dev in self._evdev_devices:
            try:
                dev.close()
            except Exception:
                pass
        self._evdev_devices.clear()
        if self._x11_display is not None:
            try:
                x11 = _load_x11()
                x11.XRecordDisableContext(self._x11_display, self._x11_ctx)
                x11.XFlush(self._x11_display)
                x11.XCloseDisplay(self._x11_display)
            except Exception:
                pass
            self._x11_display = self._x11_ctx = None
        self._backend = None

    def _try_evdev(self) -> bool:
        try:
            import evdev  # type: ignore[import-untyped]
        except ImportError:
            return False
        try:
            devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
            if not devices:
                return False
            self._evdev_devices = devices
            return True
        except (OSError, PermissionError):
            return False

    def _try_x11(self) -> bool:
        x11_path = ctypes.util.find_library("X11")
        if not x11_path:
            return False
        try:
            x11 = ctypes.CDLL(x11_path)
            display = x11.XOpenDisplay(None)
            if not display:
                return False
            self._x11_display = display
            spec = ctypes.c_ulong(1)
            rng = x11.XRecordAllocRange()
            if not rng:
                x11.XCloseDisplay(display)
                self._x11_display = None
                return False
            ctx = x11.XRecordCreateContext(display, 0, ctypes.byref(spec), 1, ctypes.byref(rng), 0)
            if not ctx:
                x11.XCloseDisplay(display)
                self._x11_display = None
                return False
            self._x11_ctx = ctx
            return True
        except Exception:
            if self._x11_display:
                try:
                    _load_x11().XCloseDisplay(self._x11_display)
                except Exception:
                    pass
                self._x11_display = None
            return False

    def _read_loop(self) -> None:
        if self._backend == "evdev":
            self._evdev_read_loop()
        elif self._backend == "x11":
            self._x11_read_loop()

    def _evdev_read_loop(self) -> None:
        import select
        fd_map: dict[int, Any] = {dev.fd: dev for dev in self._evdev_devices}
        while not self._stop_event.is_set():
            try:
                readable, _, _ = select.select(list(fd_map.keys()), [], [], 0.05)
                for fd in readable:
                    dev = fd_map.get(fd)
                    if dev is None:
                        continue
                    try:
                        for ev in dev.read():
                            self._process_evdev_event(ev)
                    except OSError:
                        del fd_map[fd]
                if not fd_map:
                    break
            except Exception:
                time.sleep(0.1)

    def _process_evdev_event(self, ev: Any) -> None:
        import evdev  # type: ignore[import-untyped]
        now = time.time()
        if ev.type == evdev.ecodes.EV_KEY:
            if ev.value not in (0, 1):
                return
            cat = evdev.categorize(ev)
            key_name = getattr(cat, "keycode", None)
            if isinstance(key_name, tuple):
                key_name = key_name[0] if key_name else None
            ie_type = "key_press" if ev.value == 1 else "key_release"
            btn = None
            if key_name in ("left", "right", "middle"):
                btn = key_name
                ie_type = "mouse_click"
            self._dispatch(InputEvent(
                event_type=ie_type, timestamp=now, key=key_name,
                vk_code=ev.scancode, button=btn, platform="linux",
            ))
        elif ev.type in (evdev.ecodes.EV_REL, evdev.ecodes.EV_ABS):
            self._dispatch(InputEvent(
                event_type="mouse_move", timestamp=now,
                x=ev.value if ev.code == 0 else None,
                y=ev.value if ev.code == 1 else None, platform="linux",
            ))

    def _x11_read_loop(self) -> None:
        x11 = _load_x11()
        cb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            self._x11_callback
        )
        self._x11_cb_ref = cb
        x11.XRecordEnableContext(self._x11_display, self._x11_ctx, cb, None)
        while not self._stop_event.is_set():
            time.sleep(0.05)

    def _x11_callback(self, display: Any, closure: Any, record_data: Any) -> None:
        try:
            rec = ctypes.cast(record_data, ctypes.POINTER(_XRecordInterceptData)).contents
            if rec.category != 1:
                return
            keycode = rec.data[0] & 0xFF
            raw_type = rec.data[1] & 0xFF
            is_down = (raw_type & 0x80) == 0
            ie_type = "key_press" if is_down else "key_release"
            key_name = _X11_KEYCODE_MAP.get(keycode, f"key_{keycode}")
            btn = _X11_MOUSE_BUTTONS.get(keycode)
            if btn:
                ie_type = "mouse_click"
            self._dispatch(InputEvent(
                event_type=ie_type, timestamp=time.time(),
                key=key_name, vk_code=keycode, button=btn, platform="linux",
            ))
        except Exception:
            pass


def hook_input(
    platform: str | None = None,
    recorder: Any = None,
    redact_characters: bool = True,
    redact_vk_codes: bool = False,
    callback: Callable[[dict], Any] | None = None,
    max_events: int = 10000,
) -> PlatformHookManager:
    if platform is None:
        platform = _PLATFORM_MAP.get(sys.platform, sys.platform)
    cls_map = {
        "windows": WindowsHookManager,
        "macos": MacOSHookManager,
        "linux": LinuxHookManager,
    }
    cls = cls_map.get(platform)
    if cls is None:
        raise RuntimeError(f"Unsupported platform for input hooks: {platform!r}")
    return cls(
        recorder=recorder, redact_characters=redact_characters,
        redact_vk_codes=redact_vk_codes, callback=callback, max_events=max_events,
    ).start()
