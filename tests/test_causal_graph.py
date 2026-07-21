"""Unit tests for causal graph functionality."""

import pytest

from tardis.causal.graph import CausalGraph
from tardis.models import Step, StepType, Trace


def create_test_trace(step_count=5):
    trace = Trace()
    step_types = [StepType.llm_call, StepType.tool_call, StepType.tool_result,
                  StepType.llm_call, StepType.error]
    for i in range(step_count):
        idx = i % len(step_types)
        trace.add_step(
            Step(trace_id="test", index=i, type=step_types[idx],
                 input={"i": i}, output={"o": i}, hash=f"ht{i}")
        )
    return trace


def create_loop_trace():
    trace = Trace()
    for i in range(4):
        trace.add_step(
            Step(trace_id="loop", index=i, type=StepType.tool_call,
                 input={"tool": "retry"}, output={"status": f"fail_{i}"},
                 hash=f"loop_{i}")
        )
    trace.add_step(
        Step(trace_id="loop", index=4, type=StepType.error,
             input={}, output={"error": "stuck"}, hash="loop_err")
    )
    return trace


def test_causal_graph_building():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    edges = graph.build()
    assert len(edges) > 0
    assert graph.nodes is not None
    assert len(graph.nodes) == len(trace.steps)


def test_causal_graph_node_structure():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    for idx, node_data in graph.nodes.items():
        assert "type" in node_data
        assert "hash" in node_data
        assert "success" in node_data
        assert "timestamp" in node_data


def test_causal_graph_edge_types():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    edges = graph.build()
    edge_types = set(edge[2] for edge in edges)
    assert len(edge_types) > 0


def test_critical_path_analysis():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    critical = graph.analyze_critical_path()
    assert isinstance(critical, list)


def test_loop_detection():
    trace = create_loop_trace()
    graph = CausalGraph(trace)
    graph.build()
    loops = graph.find_loops()
    assert isinstance(loops, list)


def test_influence_map():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    influencers = graph.get_influence_map(len(trace.steps) - 1)
    assert isinstance(influencers, list)


def test_causal_graph_render():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    edges = graph.render()
    assert edges is not None


def test_causal_graph_export_dot():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    dot_content = graph.export_dot()
    assert dot_content is not None
    assert "digraph causal_graph" in dot_content
    assert "}" in dot_content


def test_causal_graph_with_no_failures():
    trace = Trace()
    trace.add_step(Step(trace_id="test", index=0, type=StepType.llm_call,
                        input={}, output={}))
    trace.add_step(Step(trace_id="test", index=1, type=StepType.tool_call,
                        input={}, output={}))
    graph = CausalGraph(trace)
    graph.build()
    assert len(graph.nodes) == 2
    critical = graph.analyze_critical_path()
    assert len(critical) == 0


def test_large_trace_performance():
    trace = Trace()
    for i in range(100):
        stype = StepType.llm_call if i % 2 == 0 else StepType.tool_call
        trace.add_step(Step(trace_id="perf", index=i, type=stype,
                            input={}, output={}, hash=f"ph{i}"))
    graph = CausalGraph(trace)
    edges = graph.build()
    assert len(graph.nodes) == 100
    assert len(edges) > 0


def test_single_step_trace():
    trace = Trace()
    trace.add_step(Step(trace_id="one", index=0, type=StepType.llm_call,
                        input={}, output={}))
    graph = CausalGraph(trace)
    graph.build()
    assert len(graph.nodes) == 1


def test_error_and_success_mixed():
    trace = Trace()
    trace.add_step(Step(trace_id="mix", index=0, type=StepType.llm_call,
                        input={}, output={}, success=True))
    trace.add_step(Step(trace_id="mix", index=1, type=StepType.error,
                        input={}, output={}, success=False))
    trace.add_step(Step(trace_id="mix", index=2, type=StepType.llm_call,
                        input={}, output={}, success=True))
    graph = CausalGraph(trace)
    edges = graph.build()
    assert len(graph.nodes) == 3
    assert len(edges) > 0


def test_influence_map_first_step():
    trace = create_test_trace()
    graph = CausalGraph(trace)
    graph.build()
    influencers = graph.get_influence_map(0)
    assert isinstance(influencers, list)


def test_critical_path_short_trace():
    trace = Trace()
    trace.add_step(Step(trace_id="short", index=0, type=StepType.llm_call,
                        input={}, output={}, hash="s0"))
    trace.add_step(Step(trace_id="short", index=1, type=StepType.tool_call,
                        input={}, output={}, hash="s1"))
    graph = CausalGraph(trace)
    graph.build()
    critical = graph.analyze_critical_path()
    assert isinstance(critical, list)


def test_causal_graph_with_repeated_hashes():
    trace = Trace()
    for i in range(5):
        trace.add_step(Step(trace_id="reph", index=i, type=StepType.tool_call,
                            input={}, output={}, hash="same_hash"))
    graph = CausalGraph(trace)
    graph.build()
    assert len(graph.nodes) == 5


def test_loop_trace_detection():
    trace = create_loop_trace()
    graph = CausalGraph(trace)
    graph.build()
    critical = graph.analyze_critical_path()
    assert isinstance(critical, list)


def test_empty_trace():
    trace = Trace()
    graph = CausalGraph(trace)
    graph.build()
    assert len(graph.nodes) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
