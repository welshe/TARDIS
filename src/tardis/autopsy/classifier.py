from ..models import Trace, StepType

class Autopsy:
    def __init__(self, trace: Trace):
        self.trace = trace

    def classify(self):
        if not self.trace.steps:
            return "empty_trace"
        last = self.trace.steps[-1]
        # heuristic rules - v0.1, will be ML in v0.2
        text = str(self.trace.steps).lower()

        # check for grounding patterns
        if "elementnotfound" in text or "click failed" in text or "no such element" in text:
            return "grounding_failure", "Agent tried to click element that moved or did not exist. Screen diff between step N-2 and N shows layout shift."

        # check for tool failure loops
        errors = [s for s in self.trace.steps if s.type == StepType.error]
        if len(errors) >= 2:
            # same hash twice?
            if len(set(e.hash for e in errors)) < len(errors):
                return "tool_failure_loop", f"Same error repeated {len(errors)} times. Agent did not learn from failure. Hashes: {[e.hash for e in errors]}"

        # check for auth / rate limit
        if "401" in text or "403" in text or "rate limit" in text:
            return "environment_drift", "API auth or rate limit changed mid-trajectory."

        # check for reasoning loop
        llm_calls = [s for s in self.trace.steps if s.type == StepType.llm_call]
        if len(llm_calls) > 3:
            hashes = [s.hash for s in llm_calls[-3:]]
            if len(set(hashes)) == 1:
                return "reasoning_failure", "LLM stuck in loop, same completion 3 times."

        return "unknown", f"Last step: {last.type} with output {str(last.output)[:500]}"

    def report(self):
        kind, details = self.classify()
        print(f"\n[ AUTOPSY REPORT ] Trace {self.trace.id}")
        print(f"Root cause: {kind}")
        print(f"Details: {details}")
        print("\nSuggested fix:")
        if kind == "grounding_failure":
            print(" - Add active-window rect validation before click")
            print(" - Use tardis export --format negative-pair to fine-tune grounding model")
        elif kind == "tool_failure_loop":
            print(" - Inject skill: if EBUSY, kill process before retry")
            print(" - Add LanceDB lookup before generic fix")
        elif kind == "reasoning_failure":
            print(" - Add thought validator that checks for repeated hashes")
        else:
            print(" - Run tardis replay --from <failure-2> to inspect context")
        return kind, details
