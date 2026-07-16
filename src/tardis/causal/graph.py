from ..models import Trace

class CausalGraph:
    def __init__(self, trace: Trace):
        self.trace = trace

    def build(self):
        # Simple heuristic: link each step to previous llm_call and previous tool_result
        edges = []
        last_llm = None
        last_tool = None
        for s in self.trace.steps:
            if s.type == "llm_call":
                if last_tool:
                    edges.append((last_tool, s.index, "tool_informs_llm"))
                last_llm = s.index
            if s.type == "tool_call":
                if last_llm is not None:
                    edges.append((last_llm, s.index, "llm_calls_tool"))
                last_tool = s.index
            if s.type == "error":
                edges.append((s.index-1 if s.index>0 else 0, s.index, "causes_error"))
        return edges

    def render(self):
        edges = self.build()
        print(f"\n[ CAUSAL GRAPH ] {self.trace.id}")
        for src, dst, label in edges:
            print(f"  {src} --{label}--> {dst}")
        return edges
