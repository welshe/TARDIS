"""
Unit tests for causal graph functionality.
"""
import pytest
from tardis.models import Step, StepType, Trace, FailureType
from tardis.causal.graph import CausalGraph


def create_test_trace():
    """Create a test trace with various step types"""
    trace = Trace()
    
    # Add some steps in a typical pattern
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call, 
                       input={"messages": "test"}, output={"content": "response"}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call,
                       input={"tool": "click"}, output={"result": "clicked"}))
    trace.add_step(Step(trace_id="test", index=2, type=StepType.tool_result,
                       input={}, output={"status": "success"}))
    trace.add_step(Step(trace_id="test", index=3, type=StepType.llm_call,
                       input={"messages": "next"}, output={"content": "next response"}))
    trace.add_step(Step(trace_id="test", index=4, type=StepType.error,
                       input={}, output={"error": "element not found"}))
    
    return trace


def test_causal_graph_building():
    """Test causal graph construction"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    edges = graph.build()
    
    assert len(edges) > 0
    assert graph.nodes is not None
    assert len(graph.nodes) == len(trace.steps)


def test_causal_graph_node_structure():
    """Test that nodes are properly structured"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    
    for idx, node_data in graph.nodes.items():
        assert "type" in node_data
        assert "hash" in node_data
        assert "success" in node_data
        assert "timestamp" in node_data


def test_causal_graph_edge_types():
    """Test that different edge types are created"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    edges = graph.build()
    
    edge_types = set(edge[2] for edge in edges)
    # Should have various edge types
    assert len(edge_types) > 0


def test_critical_path_analysis():
    """Test critical path analysis for failures"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    
    critical = graph.analyze_critical_path()
    # Should return some critical path since there's an error
    assert isinstance(critical, list)


def test_loop_detection():
    """Test loop detection in causal graph"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    
    loops = graph.find_loops()
    # Should return list (possibly empty)
    assert isinstance(loops, list)


def test_influence_map():
    """Test influence map generation"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    
    # Test influence on last step
    influencers = graph.get_influence_map(len(trace.steps) - 1)
    assert isinstance(influencers, list)


def test_causal_graph_render():
    """Test causal graph rendering"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    
    # Should not raise exception
    edges = graph.render()
    assert edges is not None


def test_causal_graph_export_dot():
    """Test DOT format export"""
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    
    dot_content = graph.export_dot()
    assert dot_content is not None
    assert "digraph causal_graph" in dot_content
    assert "}" in dot_content


def test_causal_graph_with_no_failures():
    """Test causal graph behavior with no failures"""
    trace = Trace()
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call, input={}, output={}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call, input={}, output={}))
    
    graph = CausalGraph(trace)
    graph.build()
    
    # Should still build graph
    assert len(graph.nodes) == 2
    # Critical path should be empty
    critical = graph.analyze_critical_path()
    assert len(critical) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
