"""
Task model for multi-agent orchestration.

Tasks represent units of work that can be delegated to Agents.
Supports dependencies, priorities, and status tracking.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    pending = "pending"
    assigned = "assigned"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskPriority(int, Enum):
    low = 0
    normal = 5
    high = 10
    critical = 20


@dataclass
class Task:
    """
    A unit of work in the orchestration system.

    Tasks can depend on other tasks (dependency graph), carry priority,
    and track which agent executed them. The Orchestrator uses capability
    matching to route tasks to appropriate agents.
    """

    description: str
    priority: TaskPriority = TaskPriority.normal
    required_capabilities: set[str] = field(default_factory=set)
    dependencies: set[str] = field(default_factory=set)
    payload: dict[str, Any] = field(default_factory=dict)

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.pending
    assigned_agent: str | None = None
    result: Any | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    retries: int = 0
    max_retries: int = 3

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    def mark_assigned(self, agent_id: str):
        self.status = TaskStatus.assigned
        self.assigned_agent = agent_id

    def mark_running(self):
        self.status = TaskStatus.running
        self.started_at = time.time()

    def mark_completed(self, result: Any = None):
        self.status = TaskStatus.completed
        self.result = result
        self.completed_at = time.time()

    def mark_failed(self, error: str):
        self.status = TaskStatus.failed
        self.error = error
        self.completed_at = time.time()

    def mark_cancelled(self):
        self.status = TaskStatus.cancelled
        self.completed_at = time.time()

    def can_retry(self) -> bool:
        return self.retries < self.max_retries

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value
            if isinstance(self.priority, TaskPriority)
            else self.priority,
            "assigned_agent": self.assigned_agent,
            "dependencies": list(self.dependencies),
            "created_at": self.created_at,
            "duration": self.duration_seconds,
            "error": self.error,
            "retries": self.retries,
        }
