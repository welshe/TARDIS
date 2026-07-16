from ..models import Trace, StepType
from collections import defaultdict
import json

class CausalGraph:
    def __init__(self, trace: Trace):
        self.trace = trace
        self.edges = []
        self.nodes = {}
        self.failure_chains = []

    def build(self):
        """Build a sophisticated causal graph with multiple relationship types"""
        edges = []
        last_llm = None
        last_tool = None
        last_error = None
        context_stack = []
        
        for i, s in enumerate(self.trace.steps):
            self.nodes[s.index] = {
                "type": s.type.value,
                "hash": s.hash,
                "success": s.success,
                "timestamp": s.timestamp
            }
            
            if s.type == StepType.llm_call:
                # LLM calls are informed by previous tool results
                if last_tool is not None:
                    edges.append((last_tool, s.index, "tool_informs_llm", 0.8))
                # Also connected to previous LLM call (context chain)
                if last_llm is not None:
                    edges.append((last_llm, s.index, "context_chain", 0.6))
                last_llm = s.index
                
            elif s.type == StepType.tool_call:
                # Tool calls are caused by LLM decisions
                if last_llm is not None:
                    edges.append((last_llm, s.index, "llm_calls_tool", 0.9))
                last_tool = s.index
                
            elif s.type == StepType.tool_result:
                # Tool results inform subsequent LLM calls
                if last_tool is not None:
                    edges.append((last_tool, s.index, "tool_execution", 1.0))
                
            elif s.type == StepType.error:
                # Errors are caused by the previous step
                if i > 0:
                    cause_step = self.trace.steps[i-1]
                    edges.append((cause_step.index, s.index, "causes_error", 1.0))
                    # Track failure chains
                    if last_error is not None:
                        edges.append((last_error, s.index, "error_propagation", 0.7))
                    last_error = s.index
                    self.failure_chains.append(s.index)
                
            elif s.type == StepType.screen_frame:
                # Screen frames can inform grounding
                if last_llm is not None:
                    edges.append((last_llm, s.index, "llm_uses_screen", 0.5))
        
        # Add temporal edges (sequential causality)
        for i in range(len(self.trace.steps) - 1):
            edges.append((i, i+1, "temporal", 0.3))
        
        self.edges = edges
        return edges

    def analyze_critical_path(self):
        """Find the critical path that led to failure"""
        if not self.failure_chains:
            return []
        
        # Work backwards from first error
        first_error = min(self.failure_chains)
        critical_path = []
        
        # Find all edges that lead to the error
        for src, dst, label, weight in self.edges:
            if dst == first_error and weight > 0.7:
                critical_path.append((src, dst, label, weight))
        
        # Recursively find causes
        visited = set()
        def find_causes(node, depth=0):
            if depth > 5 or node in visited:
                return
            visited.add(node)
            for src, dst, label, weight in self.edges:
                if dst == node and weight > 0.6:
                    critical_path.append((src, dst, label, weight))
                    find_causes(src, depth+1)
        
        find_causes(first_error)
        return sorted(critical_path, key=lambda x: x[0])

    def find_loops(self):
        """Detect causal loops that might indicate infinite loops"""
        # Build adjacency list
        adj = defaultdict(list)
        for src, dst, _, _ in self.edges:
            adj[src].append(dst)
        
        # Detect cycles using DFS
        visited = set()
        recursion_stack = set()
        cycles = []
        
        def dfs(node, path):
            if node in recursion_stack:
                cycle_start = path.index(node)
                cycles.append(path[cycle_start:] + [node])
                return
            if node in visited:
                return
            
            visited.add(node)
            recursion_stack.add(node)
            path.append(node)
            
            for neighbor in adj[node]:
                dfs(neighbor, path.copy())
            
            recursion_stack.remove(node)
        
        for node in range(len(self.trace.steps)):
            dfs(node, [])
        
        return cycles

    def get_influence_map(self, step_idx: int):
        """Get all steps that influence a given step"""
        influencers = []
        for src, dst, label, weight in self.edges:
            if dst == step_idx and weight > 0.5:
                influencers.append((src, label, weight))
        return sorted(influencers, key=lambda x: x[2], reverse=True)

    def render(self):
        edges = self.build()
        print(f"\n[ CAUSAL GRAPH ] {self.trace.id}")
        print(f"Nodes: {len(self.nodes)}, Edges: {len(edges)}")
        
        # Group edges by relationship type
        by_type = defaultdict(list)
        for src, dst, label, weight in edges:
            by_type[label].append((src, dst, weight))
        
        for label, edge_list in sorted(by_type.items()):
            print(f"\n  {label} ({len(edge_list)} edges):")
            for src, dst, weight in edge_list[:5]:  # Show first 5 of each type
                print(f"    {src} -> {dst} (weight: {weight:.1f})")
            if len(edge_list) > 5:
                print(f"    ... and {len(edge_list) - 5} more")
        
        # Analyze critical path if there are failures
        if self.failure_chains:
            print(f"\n[ CRITICAL PATH ANALYSIS ]")
            critical = self.analyze_critical_path()
            if critical:
                print("  Most likely failure causes:")
                for src, dst, label, weight in critical[:10]:
                    print(f"    {src} --{label}--> {dst} (weight: {weight:.1f})")
        
        # Check for loops
        loops = self.find_loops()
        if loops:
            print(f"\n[ LOOP DETECTION ] Found {len(loops)} potential causal loops")
            for i, loop in enumerate(loops[:3]):
                print(f"  Loop {i+1}: {' -> '.join(map(str, loop))}")
        
        return edges

    def export_dot(self, output_file: str = None):
        """Export causal graph as DOT format for visualization"""
        dot_lines = ["digraph causal_graph {"]
        dot_lines.append("  rankdir=LR;")
        dot_lines.append("  node [shape=box];")
        
        # Add nodes with colors based on type
        for idx, node_data in self.nodes.items():
            color = "lightblue"
            if node_data["type"] == "error":
                color = "lightcoral"
            elif node_data["type"] == "llm_call":
                color = "lightgreen"
            elif node_data["type"] == "tool_call":
                color = "lightyellow"
            
            label = f"{idx}\\n{node_data['type']}"
            dot_lines.append(f'  {idx} [label="{label}", fillcolor="{color}", style="filled"];')
        
        # Add edges
        for src, dst, label, weight in self.edges:
            if weight > 0.5:  # Only show strong relationships
                dot_lines.append(f'  {src} -> {dst} [label="{label}", penwidth={weight}];')
        
        dot_lines.append("}")
        
        dot_content = "\n".join(dot_lines)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(dot_content)
            print(f"Exported causal graph to {output_file}")
        
        return dot_content
