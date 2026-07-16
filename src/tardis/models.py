from __future__ import annotations
from enum import Enum
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
import time, uuid

class StepType(str, Enum):
    llm_call = "llm_call"
    tool_call = "tool_call"
    tool_result = "tool_result"
    screen_frame = "screen_frame"
    user_action = "user_action"
    thought = "thought"
    error = "error"

class Step(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    trace_id: str
    index: int
    type: StepType
    timestamp: float = Field(default_factory=time.time)
    parent_id: Optional[str] = None
    hash: Optional[str] = None
    duration_ms: Optional[int] = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

class Trace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = Field(default_factory=time.time)
    root_cause: Optional[str] = None
    steps: list[Step] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_step(self, step: Step):
        step.trace_id = self.id
        step.index = len(self.steps)
        self.steps.append(step)
        return step
