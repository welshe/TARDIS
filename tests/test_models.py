"""
Unit tests for TARDIS models.
"""

import time

import pytest

from tardis.models import FailureType, Step, StepType, Trace


def test_step_creation():
    """Test basic step creation"""
    step = Step(
        trace_id="test_trace",
        index=0,
        type=StepType.llm_call,
        input={"test": "data"},
        output={"result": "success"},
    )
    assert step.trace_id == "test_trace"
    assert step.index == 0
    assert step.type == StepType.llm_call
    assert step.success is True
    assert step.id is not None


def test_step_with_enhanced_fields():
    """Test step with enhanced tracking fields"""
    step = Step(
        trace_id="test_trace",
        index=0,
        type=StepType.llm_call,
        input={"test": "data"},
        output={"result": "success"},
        token_count={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        cost_usd=0.001,
        model_name="gpt-4o",
    )
    assert step.token_count["total_tokens"] == 150
    assert step.cost_usd == 0.001
    assert step.model_name == "gpt-4o"


def test_trace_creation():
    """Test basic trace creation"""
    trace = Trace()
    assert trace.id is not None
    assert trace.steps == []
    assert trace.success is True
    assert trace.total_cost_usd == 0.0


def test_trace_add_step():
    """Test adding steps to trace"""
    trace = Trace()
    step1 = Step(
        trace_id="test",
        index=0,
        type=StepType.llm_call,
        input={"test": "data"},
        output={"result": "success"},
        cost_usd=0.001,
        token_count={"total_tokens": 100},
    )
    step2 = Step(
        trace_id="test",
        index=1,
        type=StepType.tool_call,
        input={"tool": "test"},
        output={"result": "done"},
        cost_usd=0.0005,
        token_count={"total_tokens": 50},
    )

    trace.add_step(step1)
    trace.add_step(step2)

    assert len(trace.steps) == 2
    assert trace.total_cost_usd == 0.0015
    assert trace.total_tokens == 150


def test_trace_get_steps_by_type():
    """Test filtering steps by type"""
    trace = Trace()
    trace.add_step(
        Step(trace_id="test", index=0, type=StepType.llm_call, input={}, output={})
    )
    trace.add_step(
        Step(trace_id="test", index=1, type=StepType.tool_call, input={}, output={})
    )
    trace.add_step(
        Step(trace_id="test", index=2, type=StepType.llm_call, input={}, output={})
    )

    llm_calls = trace.get_steps_by_type(StepType.llm_call)
    tool_calls = trace.get_steps_by_type(StepType.tool_call)

    assert len(llm_calls) == 2
    assert len(tool_calls) == 1


def test_trace_get_duration():
    """Test trace duration calculation"""
    trace = Trace()
    step1 = Step(trace_id="test", index=0, type=StepType.llm_call, input={}, output={})
    step1.timestamp = time.time() - 5  # 5 seconds ago

    step2 = Step(trace_id="test", index=1, type=StepType.tool_call, input={}, output={})
    step2.timestamp = time.time()  # now

    trace.add_step(step1)
    trace.add_step(step2)

    duration = trace.get_duration_seconds()
    assert 4.0 <= duration <= 6.0  # Allow some tolerance


def test_trace_error_tracking():
    """Test error tracking in trace"""
    trace = Trace()

    # Add successful step
    step1 = Step(trace_id="test", index=0, type=StepType.llm_call, input={}, output={})
    trace.add_step(step1)
    assert trace.success is True

    # Add error step
    step2 = Step(
        trace_id="test",
        index=1,
        type=StepType.error,
        input={},
        output={"error": "test"},
    )
    trace.add_step(step2)
    assert trace.success is False


def test_trace_get_error_steps():
    """Test getting error steps from trace"""
    trace = Trace()
    trace.add_step(
        Step(trace_id="test", index=0, type=StepType.llm_call, input={}, output={})
    )
    trace.add_step(
        Step(
            trace_id="test",
            index=1,
            type=StepType.error,
            input={},
            output={"error": "test"},
        )
    )
    trace.add_step(
        Step(
            trace_id="test",
            index=2,
            type=StepType.tool_call,
            input={},
            output={},
            success=False,
        )
    )

    error_steps = trace.get_error_steps()
    assert len(error_steps) == 2


def test_failure_type_enum():
    """Test FailureType enum values"""
    assert FailureType.reasoning_failure.value == "reasoning_failure"
    assert FailureType.grounding_failure.value == "grounding_failure"
    assert FailureType.tool_failure.value == "tool_failure"
    assert FailureType.memory_failure.value == "memory_failure"
    assert FailureType.environment_drift.value == "environment_drift"
    assert FailureType.unknown.value == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
