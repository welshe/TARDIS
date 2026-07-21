"""Tests for the Agent Tool Registry."""

import pytest

from tardis.orchestration.tool_registry import (
    SecurityError,
    ToolParameter,
    ToolPermission,
    ToolRegistry,
)


class TestToolRegistry:
    def test_register_and_execute(self):
        registry = ToolRegistry()

        @registry.register(
            name="echo",
            description="Echo a message",
            parameters=[ToolParameter(name="message", type="string", required=True)],
        )
        def echo(message: str) -> str:
            return message

        result = registry.execute("echo", {"message": "hello"})
        assert result == "hello"

    def test_missing_required_parameter(self):
        registry = ToolRegistry()

        @registry.register(
            name="greet",
            parameters=[ToolParameter(name="name", type="string", required=True)],
        )
        def greet(name: str) -> str:
            return f"Hello, {name}"

        with pytest.raises(ValueError, match="Missing required parameter"):
            registry.execute("greet", {})

    def test_unregistered_tool(self):
        registry = ToolRegistry()
        with pytest.raises(KeyError):
            registry.execute("nonexistent", {})

    def test_blocked_tool(self):
        registry = ToolRegistry()

        @registry.register(
            name="safe_tool",
            permission=ToolPermission.BLOCKED,
        )
        def safe_tool():
            return "should not run"

        with pytest.raises(SecurityError, match="blocked"):
            registry.execute("safe_tool", {})

    def test_security_scan_blocks_dangerous_names(self):
        registry = ToolRegistry()

        with pytest.raises(SecurityError, match="failed security scan"):

            @registry.register(name="shell_exec")
            def shell_exec():
                pass

    def test_security_scan_detects_injection(self):
        registry = ToolRegistry()

        with pytest.raises(SecurityError, match="failed security scan"):

            @registry.register(name="exec")
            def evil():
                pass

    def test_parameter_type_validation(self):
        registry = ToolRegistry()

        @registry.register(
            name="add",
            parameters=[
                ToolParameter(name="x", type="integer", required=True),
                ToolParameter(name="y", type="integer", required=True),
            ],
        )
        def add(x: int, y: int) -> int:
            return x + y

        result = registry.execute("add", {"x": 5, "y": 3})
        assert result == 8

    def test_list_tools(self):
        registry = ToolRegistry()

        @registry.register(name="tool_a", categories={"cat1"})
        def tool_a():
            pass

        @registry.register(name="tool_b", categories={"cat2"})
        def tool_b():
            pass

        all_tools = registry.list_tools()
        assert len(all_tools) == 2

        cat1_tools = registry.list_tools(category="cat1")
        assert len(cat1_tools) == 1
        assert cat1_tools[0].name == "tool_a"

    def test_get_tool(self):
        registry = ToolRegistry()

        @registry.register(name="my_tool", description="Does something")
        def my_tool():
            pass

        tool = registry.get_tool("my_tool")
        assert tool is not None
        assert tool.name == "my_tool"
        assert tool.description == "Does something"
        assert tool.security_scan_passed

    def test_rate_limiting(self):
        registry = ToolRegistry()

        @registry.register(
            name="limited",
            rate_limit=2,
        )
        def limited():
            pass

        registry.execute("limited", {})
        registry.execute("limited", {})

        with pytest.raises(SecurityError, match="Rate limit exceeded"):
            registry.execute("limited", {})

    def test_statistics(self):
        registry = ToolRegistry()

        @registry.register(name="stat_tool")
        def stat_tool():
            return "ok"

        registry.execute("stat_tool", {})
        stats = registry.get_statistics()
        assert stats["total_tools"] == 1
        assert stats["total_calls"] == 1
        assert stats["error_rate"] == 0.0

    def test_security_scan_notes(self):
        registry = ToolRegistry()

        @registry.register(
            name="file_reader",
            parameters=[
                ToolParameter(name="path", type="string", required=True),
                ToolParameter(name="command", type="string"),
            ],
        )
        def file_reader(path: str, command: str = ""):
            return path

        tool = registry.get_tool("file_reader")
        assert tool is not None
        assert any("command" in n for n in tool.security_notes)

    def test_recorder_integration(self):
        class FakeRecorder:
            def __init__(self):
                self.events = []

            def log(self, step_type, input, output, duration_ms=None, metadata=None):
                self.events.append((step_type, input, output, duration_ms, metadata))

        rec = FakeRecorder()
        registry = ToolRegistry(recorder=rec)

        @registry.register(name="logged_tool")
        def logged_tool():
            return "done"

        registry.execute("logged_tool", {})
        assert len(rec.events) == 1
        assert rec.events[0][0].value == "tool_call"
