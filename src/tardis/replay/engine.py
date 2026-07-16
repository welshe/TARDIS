from ..store.sqlite_store import Store

class ReplayEngine:
    def __init__(self, trace_id: str):
        self.store = Store()
        self.trace = self.store.get_trace(trace_id)
        if not self.trace:
            raise ValueError(f"Trace {trace_id} not found")

    def replay(self, from_idx: int = 0, to_idx: int | None = None, edit_tool_output: dict | None = None):
        to_idx = to_idx if to_idx is not None else len(self.trace.steps)
        print(f"\n[ TARDIS REPLAY ] Trace {self.trace.id} steps {from_idx} -> {to_idx}")
        print(f"Total steps: {len(self.trace.steps)}")
        if edit_tool_output:
            print(f"[ EDIT INJECTED ] {edit_tool_output}")
        for s in self.trace.steps[from_idx:to_idx]:
            out = s.output
            if edit_tool_output and s.type == "tool_result":
                out = edit_tool_output
            print(f"\n  [{s.index}] {s.type.value} | {s.duration_ms}ms | hash={s.hash}")
            if s.type == "llm_call":
                # show truncated prompt
                kwargs = s.input.get("kwargs", {})
                msgs = kwargs.get("messages", [])[-1:]
                print(f"      prompt: {str(msgs)[:300]}")
                print(f"      completion: {str(out)[:500]}")
            else:
                print(f"      in: {str(s.input)[:300]}")
                print(f"      out: {str(out)[:500]}")
        print("\n[ END REPLAY ] - Deterministic replay complete. No side effects executed.")
        return self.trace

    def diff(self, other_trace_id: str):
        other = self.store.get_trace(other_trace_id)
        print(f"\nDiff {self.trace.id} vs {other.id}")
        for a, b in zip(self.trace.steps, other.steps):
            if a.hash != b.hash:
                print(f"  Divergence at step {a.index}: {a.type} hash {a.hash} != {b.hash}")
                return a.index
        print("No divergence")
        return -1
