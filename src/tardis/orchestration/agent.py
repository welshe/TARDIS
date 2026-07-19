"""
Agent definitions for multi-agent orchestration.

Each Agent wraps a computer-use agent instance with its own TARDIS
recorder. The Orchestrator manages multiple Agents, delegates Tasks,
and coordinates via SharedMemory.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
import threading
import uuid


class AgentState(str, Enum):
    idle = "idle"
    running = "running"
    waiting = "waiting"
    error = "error"
    stopped = "stopped"


class AgentCapability(str, Enum):
    browser = "browser"
    terminal = "terminal"
    file_system = "file_system"
    code_execution = "code_execution"
    web_search = "web_search"
    api_call = "api_call"
    screen_control = "screen_control"
    vision = "vision"
    reasoning = "reasoning"


@dataclass
class Agent:
    """
    A managed agent in the orchestration system.

    Each agent has its own TARDIS Recorder for per-agent tracing,
    plus capabilities that the Orchestrator uses for task routing.
    """

    name: str
    capabilities: set[AgentCapability] = field(default_factory=set)
    model: str = "gpt-4o"
    metadata: dict[str, Any] = field(default_factory=dict)

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    state: AgentState = AgentState.idle
    current_task: Optional[Any] = None
    error_message: Optional[str] = None

    _recorder: Optional[Any] = field(default=None, repr=False)
    _fn: Optional[Callable] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def assign(self, task, fn: Optional[Callable] = None):
        with self._lock:
            self.current_task = task
            self._fn = fn
            self.state = AgentState.running

    def run(self, *args, **kwargs) -> Any:
        with self._lock:
            if self._fn is None:
                raise RuntimeError(f"Agent {self.name} has no assigned function")
            try:
                result = self._fn(self.current_task, *args, **kwargs)
                self.state = AgentState.idle
                return result
            except Exception as e:
                self.error_message = str(e)
                self.state = AgentState.error
                raise
            finally:
                self._fn = None

    def wait(self):
        with self._lock:
            self.state = AgentState.waiting

    def stop(self):
        with self._lock:
            self.state = AgentState.stopped
            self._fn = None

    def set_recorder(self, recorder):
        self._recorder = recorder

    @property
    def recorder(self):
        return self._recorder

    def has_capability(self, cap: AgentCapability) -> bool:
        return cap in self.capabilities

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state.value,
            "capabilities": [c.value for c in self.capabilities],
            "model": self.model,
            "current_task": self.current_task.id if self.current_task else None,
            "error": self.error_message,
        }
