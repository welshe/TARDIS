"""Tests for cross-platform utilities."""

import platform
from pathlib import Path

from tardis.utils.platform import (
    FileSystem,
    PlatformDetector,
    ScreenCapture,
    WindowManagement,
    get_platform_info,
)


class TestPlatformDetector:
    def test_get_platform(self):
        p = PlatformDetector.get_platform()
        assert p in ("windows", "macos", "linux", "unknown")

    def test_is_windows(self):
        result = PlatformDetector.is_windows()
        assert isinstance(result, bool)
        assert result == (platform.system().lower() == "windows")

    def test_is_linux(self):
        result = PlatformDetector.is_linux()
        assert isinstance(result, bool)
        assert result == (platform.system().lower() == "linux")

    def test_is_macos(self):
        result = PlatformDetector.is_macos()
        assert isinstance(result, bool)
        assert result == (platform.system().lower() == "darwin")

    def test_get_architecture(self):
        arch = PlatformDetector.get_architecture()
        assert isinstance(arch, str)
        assert len(arch) > 0

    def test_get_python_version(self):
        version = PlatformDetector.get_python_version()
        assert isinstance(version, tuple)
        assert len(version) == 3
        assert all(isinstance(v, int) for v in version)


class TestScreenCapture:
    def test_get_capture_method(self):
        method = ScreenCapture.get_capture_method()
        assert isinstance(method, str)

    def test_is_available(self):
        result = ScreenCapture.is_available()
        assert isinstance(result, bool)


class TestWindowManagement:
    def test_get_window_info(self):
        info = WindowManagement.get_window_info()
        assert "platform" in info


class TestFileSystem:
    def test_get_config_dir(self):
        config_dir = FileSystem.get_config_dir()
        assert isinstance(config_dir, Path)
        assert config_dir.name == "tardis"

    def test_get_cache_dir(self):
        cache_dir = FileSystem.get_cache_dir()
        assert isinstance(cache_dir, Path)
        assert cache_dir.name == "tardis"

    def test_normalize_path(self):
        path = FileSystem.normalize_path("~/test")
        assert path.is_absolute()


class TestGetPlatformInfo:
    def test_returns_dict(self):
        info = get_platform_info()
        assert "platform" in info
        assert "architecture" in info
        assert "python_version" in info
        assert "config_dir" in info
        assert "cache_dir" in info

    def test_screen_capture_fields(self):
        info = get_platform_info()
        assert "screen_capture_available" in info
        assert "screen_capture_method" in info
