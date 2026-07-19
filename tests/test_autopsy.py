"""
Unit tests for autopsy classifier functionality.
"""
import pytest
from tardis.models import Step, StepType, Trace, FailureType
from tardis.autopsy.classifier import Autopsy


def create_grounding_failure_trace():
    """Create a trace with grounding failure patterns"""
    trace = Trace()
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call, 
                       input={"messages": "click button"}, output={"content": "clicking"}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call,
                       input={"tool": "click", "coords": [100, 100]}, output={}))
    trace.add_step(Step(trace_id="test", index=2, type=StepType.error,
                       input={}, output={"error": "ElementNotFound: element not found"}))
    return trace


def create_tool_failure_loop_trace():
    """Create a trace with repeated tool failures"""
    trace = Trace()
    error_hash = "abc123"
    
    trace.add_step(Step(trace_id="test", index=0, type=StepType.tool_call,
                       input={"tool": "retry"}, output={}, hash=error_hash))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.error,
                       input={}, output={"error": "EBUSY"}, hash=error_hash))
    trace.add_step(Step(trace_id="test", index=2, type=StepType.tool_call,
                       input={"tool": "retry"}, output={}, hash=error_hash))
    trace.add_step(Step(trace_id="test", index=3, type=StepType.error,
                       input={}, output={"error": "EBUSY"}, hash=error_hash))
    return trace


def create_reasoning_failure_trace():
    """Create a trace with reasoning loop"""
    trace = Trace()
    same_hash = "xyz789"
    
    for i in range(4):
        trace.add_step(Step(trace_id="test", index=i, type=StepType.llm_call,
                           input={"messages": "thinking"}, output={"content": "same response"}, 
                           hash=same_hash))
    return trace


def create_environment_drift_trace():
    """Create a trace with environment drift"""
    trace = Trace()
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call,
                       input={"messages": "api call"}, output={"content": "calling"}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call,
                       input={"tool": "api"}, output={}))
    trace.add_step(Step(trace_id="test", index=2, type=StepType.error,
                       input={}, output={"error": "401 Unauthorized"}))
    return trace


def test_grounding_failure_classification():
    """Test grounding failure classification"""
    trace = create_grounding_failure_trace()
    autopsy = Autopsy(trace)
    
    failure_type, details, confidence = autopsy.classify()
    
    assert failure_type == FailureType.grounding_failure
    assert confidence > 0.5
    assert "grounding" in details.lower() or "element" in details.lower()


def test_tool_failure_loop_classification():
    """Test tool failure loop classification"""
    trace = create_tool_failure_loop_trace()
    autopsy = Autopsy(trace)
    
    failure_type, details, confidence = autopsy.classify()
    
    assert failure_type == FailureType.tool_failure
    assert confidence > 0.5
    assert "repeated" in details.lower() or "loop" in details.lower()


def test_reasoning_failure_classification():
    """Test reasoning failure classification"""
    trace = create_reasoning_failure_trace()
    autopsy = Autopsy(trace)
    
    failure_type, details, confidence = autopsy.classify()
    
    assert failure_type == FailureType.reasoning_failure
    assert confidence > 0.5
    assert "reasoning" in details.lower() or "loop" in details.lower()


def test_environment_drift_classification():
    """Test environment drift classification"""
    trace = create_environment_drift_trace()
    autopsy = Autopsy(trace)
    
    failure_type, details, confidence = autopsy.classify()
    
    assert failure_type == FailureType.environment_drift
    assert confidence > 0.5


def test_empty_trace_classification():
    """Test classification of empty trace"""
    trace = Trace()
    autopsy = Autopsy(trace)
    
    failure_type, details, confidence = autopsy.classify()
    
    assert failure_type == FailureType.unknown
    assert confidence == 0.0
    assert "empty" in details.lower()


def test_successful_trace_classification():
    """Test classification of successful trace"""
    trace = Trace()
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call,
                       input={}, output={"content": "success"}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call,
                       input={}, output={"result": "done"}))
    
    autopsy = Autopsy(trace)
    failure_type, details, confidence = autopsy.classify()
    
    # Should be unknown with low confidence for successful traces
    assert failure_type == FailureType.unknown
    assert confidence < 0.5


def test_evidence_collection():
    """Test that evidence is collected during classification"""
    trace = create_grounding_failure_trace()
    autopsy = Autopsy(trace)
    
    autopsy.classify()
    
    assert len(autopsy.evidence) > 0
    assert autopsy.confidence > 0.0


def test_fix_suggestions_generation():
    """Test fix suggestions generation"""
    trace = create_grounding_failure_trace()
    autopsy = Autopsy(trace)
    
    suggestions = autopsy.generate_fix_suggestions(FailureType.grounding_failure)
    
    assert isinstance(suggestions, list)
    assert len(suggestions) > 0
    assert any("validation" in s.lower() for s in suggestions)


def test_comprehensive_report():
    """Test comprehensive report generation"""
    trace = create_grounding_failure_trace()
    autopsy = Autopsy(trace)
    
    # Should not raise exception
    failure_type, details, confidence = autopsy.report()
    
    assert failure_type is not None
    assert details is not None
    assert 0.0 <= confidence <= 1.0


def test_multiple_failure_patterns():
    """Test classification with multiple potential failure patterns"""
    trace = Trace()
    # Add steps that could match multiple patterns
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call,
                       input={}, output={"content": "response"}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call,
                       input={}, output={}))
    trace.add_step(Step(trace_id="test", index=2, type=StepType.error,
                       input={}, output={"error": "401 Unauthorized timeout"}))
    
    autopsy = Autopsy(trace)
    failure_type, details, confidence = autopsy.classify()
    
    # Should classify with some confidence
    assert failure_type is not None
    assert confidence > 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
