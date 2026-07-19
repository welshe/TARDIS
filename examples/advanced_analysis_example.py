"""
Advanced analysis example showing causal graphs and pattern analysis.
"""
from tardis.replay.engine import ReplayEngine
from tardis.causal.graph import CausalGraph
from tardis.autopsy.classifier import Autopsy
from tardis.store.sqlite_store import Store

# Get the latest trace
store = Store()
traces = store.list_traces()
if not traces:
    print("No traces yet. Run basic_agent.py or tool_tracing_example.py first")
    exit()

trace_id = traces[0]['id']
trace = store.get_trace(trace_id)

print(f"=== ADVANCED ANALYSIS FOR TRACE {trace_id} ===\n")

# 1. Pattern Analysis
print("1. PATTERN ANALYSIS")
engine = ReplayEngine(trace_id)
engine.analyze_patterns()

# 2. Causal Graph Analysis
print("\n2. CAUSAL GRAPH ANALYSIS")
graph = CausalGraph(trace)
edges = graph.render()

# 3. Critical Path Analysis (if there are failures)
if trace.get_error_steps():
    print("\n3. CRITICAL PATH ANALYSIS")
    critical = graph.analyze_critical_path()
    if critical:
        print("Critical path to failure:")
        for src, dst, label, weight in critical[:10]:
            print(f"  {src} --{label}--> {dst} (weight: {weight:.1f})")

# 4. Loop Detection
print("\n4. LOOP DETECTION")
loops = graph.find_loops()
if loops:
    print(f"Found {len(loops)} potential causal loops:")
    for i, loop in enumerate(loops[:3]):
        print(f"  Loop {i+1}: {' -> '.join(map(str, loop))}")
else:
    print("No causal loops detected")

# 5. Influence Analysis
print("\n5. INFLUENCE ANALYSIS")
if len(trace.steps) > 5:
    # Analyze what influences the last step
    influencers = graph.get_influence_map(len(trace.steps) - 1)
    print(f"Steps influencing final step:")
    for src, label, weight in influencers[:5]:
        print(f"  Step {src} ({label}): {weight:.1f}")

# 6. Comprehensive Autopsy
print("\n6. COMPREHENSIVE AUTOPSY")
autopsy = Autopsy(trace)
failure_type, details, confidence = autopsy.report()

# 7. Export Causal Graph
print("\n7. EXPORT CAUSAL GRAPH")
dot_content = graph.export_dot(f"{trace_id}_causal_graph.dot")
print(f"Causal graph exported to {trace_id}_causal_graph.dot")
print("You can visualize this using: https://dreampuf.github.io/GraphvizOnline/")

print(f"\n=== ANALYSIS COMPLETE ===")
print(f"Trace saved as: {trace_id}")
print(f"Failure type: {failure_type.value if failure_type else 'None'}")
print(f"Confidence: {confidence:.1%}")
