"""
Agent Tool Registry

A secure, typed registry for agent tool definitions with schema validation,
security scanning, permission tracking, and instrumentation for TARDIS recording.

SECURITY: Every tool registration undergoes security scanning for:
- Shell injection patterns in tool names and parameter schemas
- Path traversal in file-related tools
- Dangerous capabilities (eval, exec, subprocess)
- Permission requirements validation
"""

import inspect
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..models import StepType

_INJECTION_PATTERNS = re.compile(
    r"(eval|exec|__import__|compile|os\.system|subprocess\.call|subprocess\.Popen)",
    re.I,
)

_PATH_TRAVERSAL = re.compile(r"(\.\./|\.\.\\|~[/\\])")

_DANGEROUS_TOOL_NAMES = {
    "shell_exec",
    "shell",
    "bash",
    "sh",
    "eval",
    "exec",
    "system",
    "delete_file",
    "rm",
    "format",
    "chmod",
    "chown",
    "setuid",
}

_DANGEROUS_PARAM_SCHEMAS = {
    "command",
    "shell_command",
    "executable",
    "script",
    "sql",
    "query_raw",
    "expression",
}


class ToolPermission(str, Enum):
    """Permission levels for tool execution."""

    UNRESTRICTED = "unrestricted"
    SANDBOXED = "sandboxed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    BLOCKED = "blocked"


@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    pattern: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[Any] | None = None
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default,
            "pattern": self.pattern,
            "sensitive": self.sensitive,
        }


@dataclass
class ToolDefinition:
    """A registered tool with schema, security metadata, and implementation."""

    name: str
    description: str
    parameters: list[ToolParameter]
    implementation: Any = field(repr=False)
    permission: ToolPermission = ToolPermission.SANDBOXED
    categories: set[str] = field(default_factory=set)
    timeout_seconds: float | None = 30.0
    rate_limit: int | None = None
    requires_confirmation: bool = False
    security_scan_passed: bool = False
    security_notes: list[str] = field(default_factory=list)
    registered_at: datetime = field(default_factory=datetime.now)
    call_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters],
            "permission": self.permission.value,
            "categories": list(self.categories),
            "timeout_seconds": self.timeout_seconds,
            "rate_limit": self.rate_limit,
            "requires_confirmation": self.requires_confirmation,
            "security_scan_passed": self.security_scan_passed,
            "security_notes": self.security_notes,
            "call_count": self.call_count,
            "error_count": self.error_count,
        }


class ToolRegistry:
    """Secure, typed registry for agent tool definitions.

    Features:
    - Schema validation with parameter types and constraints
    - Security scanning on registration (injection, traversal, danger names)
    - Permission-based execution controls
    - Rate limiting enforcement
    - TARDIS recorder integration for full traceability
    - Thread-safe registration and lookup

    Usage:
        registry = ToolRegistry(recorder=my_recorder)

        @registry.register(
            name="read_file",
            description="Read a file from disk",
            parameters=[ToolParameter(name="path", type="string", required=True)],
        )
        def read_file(path: str) -> str:
            with open(path) as f:
                return f.read()

        result = registry.execute("read_file", {"path": "data.txt"})
    """

    def __init__(self, recorder: Any | None = None):
        self._tools: dict[str, ToolDefinition] = {}
        self._lock = threading.RLock()
        self._call_history: list[dict[str, Any]] = []
        self._rate_counters: dict[str, list] = {}
        self._recorder = recorder

    def register(
        self,
        name: str | None = None,
        description: str = "",
        parameters: list[ToolParameter] | None = None,
        permission: ToolPermission = ToolPermission.SANDBOXED,
        categories: set[str] | None = None,
        timeout_seconds: float | None = 30.0,
        rate_limit: int | None = None,
        requires_confirmation: bool = False,
    ) -> Callable:
        """Decorator to register a tool with security scanning.

        Args:
            name: Tool name (defaults to function name).
            description: Human-readable description.
            parameters: List of ToolParameter defining the schema.
            permission: Permission level for execution.
            categories: Set of category tags for tool grouping.
            timeout_seconds: Maximum execution time.
            rate_limit: Max calls per minute (None = unlimited).
            requires_confirmation: If True, requires explicit user confirmation.

        Returns:
            Decorator that registers the function and returns it unchanged.

        Raises:
            SecurityError: If the tool fails security scanning.
        """

        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            tool_params = parameters or self._infer_parameters(fn)
            tool_desc = (
                description or (fn.__doc__ or "").strip() or f"Tool: {tool_name}"
            )

            security_notes = self._scan_for_security(tool_name, tool_params)
            scan_passed = (
                len([n for n in security_notes if n.startswith("BLOCKED")]) == 0
            )

            if not scan_passed:
                blocked = [n for n in security_notes if n.startswith("BLOCKED")]
                raise SecurityError(
                    f"Tool '{tool_name}' failed security scan: {'; '.join(blocked)}"
                )

            definition = ToolDefinition(
                name=tool_name,
                description=tool_desc,
                parameters=tool_params,
                implementation=fn,
                permission=permission,
                categories=categories or set(),
                timeout_seconds=timeout_seconds,
                rate_limit=rate_limit,
                requires_confirmation=requires_confirmation,
                security_scan_passed=scan_passed,
                security_notes=security_notes,
            )

            with self._lock:
                self._tools[tool_name] = definition

            return fn

        return decorator

    def _infer_parameters(self, fn: Callable) -> list[ToolParameter]:
        """Infer parameters from function signature."""
        params = []
        try:
            sig = inspect.signature(fn)
            for p_name, p_param in sig.parameters.items():
                p_type = "string"
                if p_param.annotation != inspect.Parameter.empty:
                    type_name = str(p_param.annotation)
                    if "int" in type_name.lower():
                        p_type = "integer"
                    elif "float" in type_name.lower():
                        p_type = "number"
                    elif "bool" in type_name.lower():
                        p_type = "boolean"
                    elif "list" in type_name.lower() or "dict" in type_name.lower():
                        p_type = "object"
                params.append(
                    ToolParameter(
                        name=p_name,
                        type=p_type,
                        required=p_param.default == inspect.Parameter.empty,
                    )
                )
        except Exception:
            pass
        return params

    def _scan_for_security(
        self, name: str, parameters: list[ToolParameter]
    ) -> list[str]:
        """Security scan a tool definition."""
        notes = []

        if name in _DANGEROUS_TOOL_NAMES:
            notes.append(f"BLOCKED: Tool name '{name}' matches dangerous tool patterns")

        if _INJECTION_PATTERNS.search(name):
            notes.append(f"BLOCKED: Tool name '{name}' contains code injection pattern")

        for param in parameters:
            if param.name in _DANGEROUS_PARAM_SCHEMAS:
                notes.append(
                    f"WARNING: Parameter '{param.name}' may allow code execution"
                )

            if param.type == "string" and _PATH_TRAVERSAL.search(param.name):
                notes.append(
                    f"WARNING: Parameter '{param.name}' may allow path traversal"
                )

            if param.sensitive and param.default is not None:
                notes.append(
                    "WARNING: Sensitive parameter has default value (may leak secrets)"
                )

        if not notes:
            notes.append("PASSED: Security scan completed with no issues")

        return notes

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a registered tool with validation and recording.

        Args:
            name: Registered tool name.
            arguments: Tool arguments as dict.
            context: Optional execution context (trace_id, agent_id, etc.).

        Returns:
            Tool execution result.

        Raises:
            KeyError: If tool is not registered.
            ValueError: If argument validation fails.
            SecurityError: If tool is blocked or rate limited.
        """
        with self._lock:
            tool = self._tools.get(name)
            if tool is None:
                raise KeyError(f"Tool '{name}' not registered")

            if tool.permission == ToolPermission.BLOCKED:
                raise SecurityError(f"Tool '{name}' is blocked")

            if tool.permission == ToolPermission.CONFIRMATION_REQUIRED:
                if not context or not context.get("confirmed"):
                    raise SecurityError(
                        f"Tool '{name}' requires confirmation. "
                        "Pass context={'confirmed': True} after user approval."
                    )

            if tool.rate_limit:
                self._check_rate_limit(name, tool.rate_limit)

            self._validate_arguments(tool, arguments)

            tool.call_count += 1

        start = time.time()
        try:
            result = tool.implementation(**arguments)

            duration_ms = int((time.time() - start) * 1000)
            self._log_tool_call(name, arguments, result, duration_ms, context)

            return result

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            with self._lock:
                tool.error_count += 1
            self._log_tool_call(
                name, arguments, {"error": str(e)}, duration_ms, context
            )
            raise

    def _validate_arguments(self, tool: ToolDefinition, arguments: dict[str, Any]):
        """Validate arguments against the tool's parameter schema."""
        param_map = {p.name: p for p in tool.parameters}

        for param in tool.parameters:
            if param.required and param.name not in arguments:
                raise ValueError(
                    f"Missing required parameter '{param.name}' for tool '{tool.name}'"
                )

        for arg_name, arg_value in arguments.items():
            if arg_name not in param_map:
                continue

            param = param_map[arg_name]

            if param.type == "integer" and not isinstance(arg_value, int):
                try:
                    arguments[arg_name] = int(arg_value)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"Parameter '{arg_name}' must be integer, got {type(arg_value).__name__}"
                    )

            if param.pattern and isinstance(arg_value, str):
                if not re.match(param.pattern, arg_value):
                    raise ValueError(
                        f"Parameter '{arg_name}' does not match required pattern '{param.pattern}'"
                    )

            if isinstance(arg_value, (int, float)):
                if param.min_value is not None and arg_value < param.min_value:
                    raise ValueError(
                        f"Parameter '{arg_name}' below minimum ({param.min_value})"
                    )
                if param.max_value is not None and arg_value > param.max_value:
                    raise ValueError(
                        f"Parameter '{arg_name}' above maximum ({param.max_value})"
                    )

            if (
                param.allowed_values is not None
                and arg_value not in param.allowed_values
            ):
                raise ValueError(
                    f"Parameter '{arg_name}' must be one of {param.allowed_values}"
                )

            # Runtime path-traversal check: validate the actual argument value,
            # not just the parameter name. A path-typed parameter can still
            # receive a malicious value ('../../etc/passwd') that the static
            # scan never inspects.
            if param.type == "string" and _PATH_TRAVERSAL.search(str(arg_value)):
                raise SecurityError(
                    f"Parameter '{arg_name}' rejected: path traversal pattern "
                    f"detected in value"
                )

    def _check_rate_limit(self, name: str, limit: int):
        """Enforce per-minute rate limiting."""
        now = time.time()
        with self._lock:
            if name not in self._rate_counters:
                self._rate_counters[name] = []
            window = [t for t in self._rate_counters[name] if now - t < 60]
            if len(window) >= limit:
                raise SecurityError(
                    f"Rate limit exceeded for tool '{name}': {limit} calls per minute"
                )
            window.append(now)
            self._rate_counters[name] = window

    def _log_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        duration_ms: int,
        context: dict[str, Any] | None = None,
    ):
        """Log tool call to recorder and internal history."""
        entry = {
            "tool": name,
            "arguments": arguments,
            "result": str(result)[:1000],
            "duration_ms": duration_ms,
            "timestamp": time.time(),
            "context": context or {},
        }
        with self._lock:
            self._call_history.append(entry)

        if self._recorder:
            try:
                self._recorder.log(
                    StepType.tool_call,
                    input={"tool_name": name, "arguments": arguments},
                    output={"result": str(result)[:4000]},
                    duration_ms=duration_ms,
                    metadata={"source": "tool_registry"},
                )
            except Exception:
                pass

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        with self._lock:
            return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        """List registered tools, optionally filtered by category."""
        with self._lock:
            tools = list(self._tools.values())
            if category:
                tools = [t for t in tools if category in t.categories]
            return sorted(tools, key=lambda t: t.name)

    def get_statistics(self) -> dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            total_calls = sum(t.call_count for t in self._tools.values())
            total_errors = sum(t.error_count for t in self._tools.values())
            by_permission = {}
            for t in self._tools.values():
                key = t.permission.value
                by_permission[key] = by_permission.get(key, 0) + 1
            return {
                "total_tools": len(self._tools),
                "total_calls": total_calls,
                "total_errors": total_errors,
                "error_rate": total_errors / max(total_calls, 1),
                "by_permission": by_permission,
                "history_size": len(self._call_history),
            }


class SecurityError(Exception):
    """Raised when a tool fails security validation or execution."""

    pass
