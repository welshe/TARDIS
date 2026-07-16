from ..store.sqlite_store import Store
from ..models import StepType
import json

class ReplayEngine:
    def __init__(self, trace_id: str):
        self.store = Store()
        self.trace = self.store.get_trace(trace_id)
        if not self.trace:
            raise ValueError(f"Trace {trace_id} not found")
        self.edit_injections = {}
        self.breakpoints = set()

    def replay(self, from_idx: int = 0, to_idx: int | None = None, edit_tool_output: dict | None = None):
        to_idx = to_idx if to_idx is not None else len(self.trace.steps)
        print(f"\n[ TARDIS REPLAY ] Trace {self.trace.id} steps {from_idx} -> {to_idx}")
        print(f"Total steps: {len(self.trace.steps)}")
        print(f"Duration: {self.trace.get_duration_seconds():.2f}s")
        print(f"Total cost: ${self.trace.total_cost_usd:.4f}")
        print(f"Total tokens: {self.trace.total_tokens}")
        
        if edit_tool_output:
            self.edit_injections[from_idx] = edit_tool_output
            print(f"[ EDIT INJECTED at step {from_idx} ] {edit_tool_output}")
        
        replay_state = {
            "variables": {},
            "context": {},
            "step_count": 0
        }
        
        for s in self.trace.steps[from_idx:to_idx]:
            # Check for breakpoint
            if s.index in self.breakpoints:
                print(f"\n  [ BREAKPOINT at step {s.index} ]")
                response = input("Press Enter to continue, 'q' to quit, 'i' to inspect: ")
                if response.lower() == 'q':
                    break
                elif response.lower() == 'i':
                    self._inspect_step(s)
            
            # Apply edit injection if present
            out = s.output
            if s.index in self.edit_injections:
                out = self.edit_injections[s.index]
                print(f"\n  [ EDIT APPLIED at step {s.index} ]")
            
            print(f"\n  [{s.index}] {s.type.value} | {s.duration_ms}ms | hash={s.hash}")
            
            # Update replay state
            replay_state["step_count"] += 1
            if s.type == StepType.llm_call:
                self._replay_llm_call(s, out, replay_state)
            elif s.type == StepType.tool_call:
                self._replay_tool_call(s, out, replay_state)
            elif s.type == StepType.error:
                self._replay_error(s, replay_state)
            else:
                self._replay_generic(s, out, replay_state)
        
        print("\n[ END REPLAY ] - Deterministic replay complete.")
        print(f"Replayed {replay_state['step_count']} steps")
        return self.trace

    def _replay_llm_call(self, step, output, state):
        kwargs = step.input.get("kwargs", {})
        msgs = kwargs.get("messages", [])[-1:]
        model = step.model_name or "unknown"
        
        print(f"      Model: {model}")
        print(f"      Tokens: {step.token_count}")
        print(f"      Cost: ${step.cost_usd:.6f}" if step.cost_usd else "      Cost: N/A")
        print(f"      prompt: {str(msgs)[:400]}")
        print(f"      completion: {str(output)[:600]}")
        
        # Update state with LLM response
        state["context"]["last_llm_response"] = output
        state["context"]["last_model"] = model

    def _replay_tool_call(self, step, output, state):
        name = step.input.get("name", "unknown")
        print(f"      Tool: {name}")
        print(f"      Input: {str(step.input)[:400]}")
        print(f"      Output: {str(output)[:400]}")
        
        # Update state with tool result
        state["variables"][f"tool_{name}_result"] = output

    def _replay_error(self, step, state):
        print(f"      ERROR: {step.output.get('error', 'Unknown error')}")
        state["context"]["last_error"] = step.output

    def _replay_generic(self, step, output, state):
        print(f"      Input: {str(step.input)[:300]}")
        print(f"      Output: {str(output)[:400]}")

    def _inspect_step(self, step):
        print(f"\n  [ INSPECTING STEP {step.index} ]")
        print(f"  Type: {step.type.value}")
        print(f"  Input: {json.dumps(step.input, indent=2, default=str)[:800]}")
        print(f"  Output: {json.dumps(step.output, indent=2, default=str)[:800]}")
        print(f"  Metadata: {json.dumps(step.metadata, indent=2, default=str)}")

    def add_breakpoint(self, step_idx: int):
        self.breakpoints.add(step_idx)

    def remove_breakpoint(self, step_idx: int):
        self.breakpoints.discard(step_idx)

    def diff(self, other_trace_id: str):
        other = self.store.get_trace(other_trace_id)
        print(f"\nDiff {self.trace.id} vs {other.id}")
        
        if len(self.trace.steps) != len(other.steps):
            print(f"  Length mismatch: {len(self.trace.steps)} vs {len(other.steps)}")
        
        divergences = []
        for i, (a, b) in enumerate(zip(self.trace.steps, other.steps)):
            if a.hash != b.hash:
                divergences.append((i, a.type, a.hash, b.hash))
                print(f"  Divergence at step {a.index}: {a.type.value}")
                print(f"    Hash A: {a.hash}")
                print(f"    Hash B: {b.hash}")
        
        if not divergences:
            print("No divergence found")
        else:
            print(f"\nTotal divergences: {len(divergences)}")
        
        return divergences

    def analyze_patterns(self):
        """Analyze patterns in the trace for debugging insights"""
        print(f"\n[ PATTERN ANALYSIS ] Trace {self.trace.id}")
        
        # Analyze LLM call patterns
        llm_calls = self.trace.get_steps_by_type(StepType.llm_call)
        if llm_calls:
            avg_duration = sum(s.duration_ms or 0 for s in llm_calls) / len(llm_calls)
            total_cost = sum(s.cost_usd or 0 for s in llm_calls)
            print(f"  LLM Calls: {len(llm_calls)}")
            print(f"  Avg duration: {avg_duration:.0f}ms")
            print(f"  Total LLM cost: ${total_cost:.4f}")
            
            # Check for repeated patterns
            hashes = [s.hash for s in llm_calls]
            unique_hashes = set(hashes)
            if len(unique_hashes) < len(hashes):
                print(f"  Repeated patterns detected: {len(hashes) - len(unique_hashes)} duplicates")
        
        # Analyze error patterns
        error_steps = self.trace.get_error_steps()
        if error_steps:
            print(f"  Errors: {len(error_steps)}")
            error_types = {}
            for e in error_steps:
                error_type = e.error_type or "unknown"
                error_types[error_type] = error_types.get(error_type, 0) + 1
            for err_type, count in error_types.items():
                print(f"    {err_type}: {count}")
        
        # Analyze tool usage
        tool_calls = self.trace.get_steps_by_type(StepType.tool_call)
        if tool_calls:
            tool_names = {}
            for t in tool_calls:
                name = t.input.get("name", "unknown")
                tool_names[name] = tool_names.get(name, 0) + 1
            print(f"  Tool calls: {len(tool_calls)}")
            for name, count in sorted(tool_names.items(), key=lambda x: x[1], reverse=True):
                print(f"    {name}: {count}")
