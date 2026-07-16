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

class FailureType(str, Enum):
    reasoning_failure = "reasoning_failure"
    grounding_failure = "grounding_failure"
    tool_failure = "tool_failure"
    memory_failure = "memory_failure"
    environment_drift = "environment_drift"
    unknown = "unknown"

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
    # Enhanced tracking fields
    token_count: Optional[dict[str, int]] = Field(default_factory=dict)  # prompt_tokens, completion_tokens
    cost_usd: Optional[float] = None
    model_name: Optional[str] = None
    success: bool = True
    error_type: Optional[str] = None

class Trace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = Field(default_factory=time.time)
    root_cause: Optional[str] = None
    failure_type: Optional[FailureType] = None
    steps: list[Step] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Enhanced tracking fields
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    success: bool = True
    environment_info: dict[str, Any] = Field(default_factory=dict)

    def add_step(self, step: Step):
        step.trace_id = self.id
        step.index = len(self.steps)
        self.steps.append(step)
        # Update aggregate statistics
        if step.cost_usd:
            self.total_cost_usd += step.cost_usd
        if step.token_count:
            self.total_tokens += step.token_count.get("total_tokens", 0)
        if not step.success or step.type == StepType.error:
            self.success = False
        return step

    def get_steps_by_type(self, step_type: StepType) -> list[Step]:
        return [s for s in self.steps if s.type == step_type]

    def get_duration_seconds(self) -> float:
        if not self.steps:
            return 0.0
        return self.steps[-1].timestamp - self.steps[0].timestamp

    def get_error_steps(self) -> list[Step]:
        return [s for s in self.steps if s.type == StepType.error or not s.success]
