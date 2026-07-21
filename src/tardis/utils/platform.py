"""
Cross-platform utilities for TARDIS.
Addresses platform lock-in concerns by providing platform-agnostic interfaces.
"""

import platform
import subprocess
import sys
from pathlib import Path


class PlatformDetector:
    """Detect current platform and provide platform-specific information"""

    @staticmethod
    def get_platform() -> str:
        """Get current platform identifier"""
        system = platform.system().lower()
        if system == "windows":
            return "windows"
        elif system == "darwin":
            return "macos"
        elif system == "linux":
            return "linux"
        else:
            return "unknown"

    @staticmethod
    def is_windows() -> bool:
        return platform.system().lower() == "windows"

    @staticmethod
    def is_linux() -> bool:
        return platform.system().lower() == "linux"

    @staticmethod
    def is_macos() -> bool:
        return platform.system().lower() == "darwin"

    @staticmethod
    def get_architecture() -> str:
        return platform.machine().lower()

    @staticmethod
    def get_python_version() -> tuple[int, int, int]:
        return sys.version_info[:3]


class ScreenCapture:
    """Cross-platform screen capture interface"""

    @staticmethod
    def is_available() -> bool:
        """Check if screen capture is available on current platform"""
        try:
            if PlatformDetector.is_windows():
                try:
                    import mss  # noqa: F401
                    return True
                except ImportError:
                    return False
            elif PlatformDetector.is_macos():
                # Check for screencapture availability
                result = subprocess.run(
                    ["which", "screencapture"], capture_output=True, text=True
                )
                return result.returncode == 0
            elif PlatformDetector.is_linux():
                # Check for scrot or import availability
                for cmd in ["scrot", "import", "maim"]:
                    result = subprocess.run(
                        ["which", cmd], capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        return True
                return False
        except Exception:
            return False
        return False

    @staticmethod
    def get_capture_method() -> str:
        """Get the recommended capture method for current platform"""
        if PlatformDetector.is_windows():
            return "mss"
        elif PlatformDetector.is_macos():
            return "screencapture"
        elif PlatformDetector.is_linux():
            return "scrot"  # or maim/import
        return "unknown"


class WindowManagement:
    """Cross-platform window management interface"""

    @staticmethod
    def is_available() -> bool:
        """Check if window management is available"""
        if PlatformDetector.is_windows():
            try:
                import win32gui  # noqa: F401

                return True
            except ImportError:
                return False
        elif PlatformDetector.is_macos():
            # Check for AppleScript availability
            result = subprocess.run(
                ["which", "osascript"], capture_output=True, text=True
            )
            return result.returncode == 0
        elif PlatformDetector.is_linux():
            # Check for wmctrl or xdotool
            for cmd in ["wmctrl", "xdotool"]:
                result = subprocess.run(["which", cmd], capture_output=True, text=True)
                if result.returncode == 0:
                    return True
            return False
        return False

    @staticmethod
    def get_window_info() -> dict:
        """Get information about the active window"""
        platform = PlatformDetector.get_platform()

        if platform == "windows":
            try:
                import win32gui
                import win32process

                hwnd = win32gui.GetForegroundWindow()
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                title = win32gui.GetWindowText(hwnd)
                rect = win32gui.GetWindowRect(hwnd)

                return {
                    "platform": "windows",
                    "hwnd": hwnd,
                    "pid": pid,
                    "title": title,
                    "rect": rect,
                    "method": "win32api",
                }
            except Exception as e:
                return {"error": str(e), "platform": "windows"}

        elif platform == "macos":
            try:
                script = """
                tell application "System Events"
                    set frontApp to name of first application process whose frontmost is true
                    try
                        set frontWindow to front window of process frontApp
                        set windowTitle to title of frontWindow
                        set windowBounds to bounds of frontWindow
                        return windowTitle & "|" & (item 1 of windowBounds as text) & "," & (item 2 of windowBounds as text) & "," & (item 3 of windowBounds as text) & "," & (item 4 of windowBounds as text)
                    on error
                        return frontApp & "|"
                    end try
                end tell
                """
                result = subprocess.run(
                    ["osascript", "-e", script], capture_output=True, text=True
                )
                if result.returncode == 0:
                    output = result.stdout.strip()
                    parts = output.split("|", 1)
                    info = {
                        "platform": "macos",
                        "method": "applescript",
                        "title": parts[0] if parts else "",
                    }
                    if len(parts) > 1 and parts[1]:
                        bounds = parts[1].split(",")
                        if len(bounds) == 4:
                            info["bounds"] = {
                                "x": int(bounds[0]),
                                "y": int(bounds[1]),
                                "width": int(bounds[2]),
                                "height": int(bounds[3]),
                            }
                    return info
                return {"error": "AppleScript failed", "platform": "macos"}
            except Exception as e:
                return {"error": str(e), "platform": "macos"}

        elif platform == "linux":
            try:
                # Try wmctrl first
                result = subprocess.run(
                    ["wmctrl", "-l"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if lines:
                        # Parse first line (active window)
                        parts = lines[0].split(None, 3)
                        if len(parts) >= 4:
                            return {
                                "platform": "linux",
                                "method": "wmctrl",
                                "title": parts[3],
                                "raw_output": lines[0],
                            }
                return {"error": "wmctrl parsing failed", "platform": "linux"}
            except Exception as e:
                return {"error": str(e), "platform": "linux"}

        return {"error": "Unsupported platform", "platform": platform}


class FileSystem:
    """Cross-platform file system utilities"""

    @staticmethod
    def get_config_dir() -> Path:
        """Get platform-specific config directory"""
        platform = PlatformDetector.get_platform()

        if platform == "windows":
            base = Path.home() / "AppData" / "Roaming"
        elif platform == "macos":
            base = Path.home() / "Library" / "Application Support"
        elif platform == "linux":
            base = Path.home() / ".config"
        else:
            base = Path.home()

        tardis_dir = base / "tardis"
        tardis_dir.mkdir(parents=True, exist_ok=True)
        return tardis_dir

    @staticmethod
    def get_cache_dir() -> Path:
        """Get platform-specific cache directory"""
        platform = PlatformDetector.get_platform()

        if platform == "windows":
            base = Path.home() / "AppData" / "Local"
        elif platform == "macos":
            base = Path.home() / "Library" / "Caches"
        elif platform == "linux":
            base = Path.home() / ".cache"
        else:
            base = Path.home() / ".tardis_cache"

        cache_dir = base / "tardis"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def normalize_path(path: str) -> Path:
        """Normalize path for current platform"""
        return Path(path).expanduser().resolve()


class ProcessManagement:
    """Cross-platform process management utilities"""

    @staticmethod
    def get_process_info(pid: int) -> dict:
        """Get information about a process"""
        try:
            import psutil

            process = psutil.Process(pid)
            return {
                "pid": pid,
                "name": process.name(),
                "status": process.status(),
                "memory_percent": process.memory_percent(),
                "cpu_percent": process.cpu_percent(),
                "platform": PlatformDetector.get_platform(),
            }
        except ImportError:
            return {"error": "psutil not installed", "pid": pid}
        except Exception as e:
            return {"error": str(e), "pid": pid}

    @staticmethod
    def kill_process(pid: int) -> bool:
        """Attempt to kill a process"""
        try:
            import psutil

            process = psutil.Process(pid)
            process.kill()
            return True
        except Exception:
            return False


def get_platform_info() -> dict:
    """Get comprehensive platform information"""
    return {
        "platform": PlatformDetector.get_platform(),
        "architecture": PlatformDetector.get_architecture(),
        "python_version": PlatformDetector.get_python_version(),
        "screen_capture_available": ScreenCapture.is_available(),
        "screen_capture_method": ScreenCapture.get_capture_method(),
        "window_management_available": WindowManagement.is_available(),
        "config_dir": str(FileSystem.get_config_dir()),
        "cache_dir": str(FileSystem.get_cache_dir()),
    }


if __name__ == "__main__":
    # Test platform detection
    print("Platform Information:")
    import json

    print(json.dumps(get_platform_info(), indent=2))
