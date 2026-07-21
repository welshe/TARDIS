import re
from collections import Counter

from ..models import FailureType, StepType, Trace
from ..store.lancedb_store import FailurePatternStore

_NUMERIC_PATTERNS = re.compile(r"(?<!\w)(401|403|407|429|500|502|503)(?!\w)")

# Define pattern priorities (higher number = higher priority)
_PATTERN_PRIORITY = {
    FailureType.grounding_failure: 10,
    FailureType.tool_failure: 9,
    FailureType.reasoning_failure: 8,
    FailureType.memory_failure: 7,
    FailureType.environment_drift: 6,
    FailureType.unknown: 0,
}


class Autopsy:
    def __init__(self, trace: Trace):
        self.trace = trace
        self.confidence = 0.0
        self.evidence = []

    def classify(self):
        """Classify the failure type with confidence scoring"""
        if not self.trace.steps:
            return FailureType.unknown, "empty_trace", 0.0

        # Run all classification checks
        checks = [
            self._check_grounding_failure,
            self._check_tool_failure_loop,
            self._check_reasoning_failure,
            self._check_memory_failure,
            self._check_environment_drift,
            self._check_api_errors,
            self._check_timeout_issues,
            self._check_resource_exhaustion,
        ]

        results = []
        for check in checks:
            result = check()
            if result:
                results.append(result)

        # Sort by priority first, then by confidence
        if results:
            results.sort(
                key=lambda x: (_PATTERN_PRIORITY.get(x[0], 0), x[2]), reverse=True
            )
            failure_type, details, confidence = results[0]
            self.confidence = confidence
            self.trace.failure_type = failure_type
            return failure_type, details, confidence

        return (
            FailureType.unknown,
            f"Last step: {self.trace.steps[-1].type} with output {str(self.trace.steps[-1].output)[:500]}",
            0.3,
        )

    def _get_error_text(self) -> str:
        """Extract error text from steps using structured field access."""
        error_texts = []
        for step in self.trace.steps:
            if step.type == StepType.error or not step.success:
                # Use structured field access instead of repr serialization
                if step.output.get("error"):
                    error_texts.append(step.output["error"].lower())
                if step.error_type:
                    error_texts.append(step.error_type.lower())
                # Also check metadata for error info
                if step.metadata.get("error"):
                    error_texts.append(str(step.metadata["error"]).lower())
        return " ".join(error_texts)

    def _check_grounding_failure(self):
        """Check for grounding failures (UI element location issues)"""
        # Check for snapshot-related grounding evidence
        dom_steps = [s for s in self.trace.steps if s.type == StepType.dom_snapshot]
        acc_steps = [
            s for s in self.trace.steps if s.type == StepType.accessibility_snapshot
        ]

        if len(dom_steps) >= 2 or len(acc_steps) >= 2:
            # Compare consecutive snapshots for layout shifts
            from ..capture.dom_snapshot import diff_snapshots

            snapshots = dom_steps or acc_steps
            for i in range(len(snapshots) - 1):
                diff = diff_snapshots(snapshots[i].output, snapshots[i + 1].output)
                if diff.get("layout_shift"):
                    self.evidence.append(("snapshot_layout_shift", diff))
                    return (
                        FailureType.grounding_failure,
                        (
                            f"Layout shift detected between snapshots: "
                            f"{diff['modified_count']} elements moved, "
                            f"{diff['added_count']} added, {diff['removed_count']} removed"
                        ),
                        0.85,
                    )

        # Use structured field access instead of string serialization
        error_text = self._get_error_text()

        patterns = [
            "element not found",
            "elementnotfound",
            "click failed",
            "no such element",
            "element not interactable",
            "element not clickable",
            "element obscured",
            "element not visible",
            "timeout waiting for element",
            "stale element",
        ]

        matches = [p for p in patterns if p in error_text]
        if matches:
            confidence = min(0.9, 0.5 + len(matches) * 0.1)
            details = f"Agent tried to interact with UI element that moved or did not exist. Patterns found: {matches}"
            self.evidence.append(("grounding_patterns", matches))
            return FailureType.grounding_failure, details, confidence
        return None

    def _check_tool_failure_loop(self):
        """Check for repeated tool failures"""
        errors = [
            s for s in self.trace.steps if s.type == StepType.error or not s.success
        ]
        if len(errors) >= 2:
            # Check for repeated error hashes
            error_hashes = [e.hash for e in errors if e.hash]
            if len(set(error_hashes)) < len(error_hashes):
                duplicates = len(error_hashes) - len(set(error_hashes))
                confidence = min(0.95, 0.6 + duplicates * 0.1)
                details = f"Same error repeated {duplicates} times. Agent did not learn from failure. Error hashes: {error_hashes}"
                self.evidence.append(("repeated_errors", error_hashes))
                return FailureType.tool_failure, details, confidence
        return None

    def _check_reasoning_failure(self):
        """Check for LLM reasoning loops"""
        llm_calls = [s for s in self.trace.steps if s.type == StepType.llm_call]
        if len(llm_calls) > 3:
            # Check for repeated completion hashes
            hashes = [s.hash for s in llm_calls[-5:]]
            if len(set(hashes)) == 1:
                confidence = 0.9
                details = f"LLM stuck in reasoning loop, same completion {len(hashes)} times consecutively."
                self.evidence.append(("reasoning_loop", hashes))
                return FailureType.reasoning_failure, details, confidence

            # Check for similar patterns (not exact matches)
            if len(set(hashes)) <= 2:
                confidence = 0.7
                details = f"LLM showing repetitive behavior patterns. Only {len(set(hashes))} unique patterns in last {len(hashes)} calls."
                self.evidence.append(("repetitive_patterns", hashes))
                return FailureType.reasoning_failure, details, confidence
        return None

    def _check_environment_drift(self):
        """Check for environment changes (auth, rate limits, etc.)"""
        error_text = self._get_error_text()
        patterns = [
            "authentication",
            "unauthorized",
            "rate limit",
            "too many requests",
            "connection refused",
            "network unreachable",
            "dns error",
            "service unavailable",
        ]

        matches = [p for p in patterns if p in error_text]
        numeric_matches = _NUMERIC_PATTERNS.findall(error_text)
        if numeric_matches:
            matches.extend(numeric_matches)
        if matches:
            confidence = min(0.85, 0.6 + len(matches) * 0.05)
            details = f"Environment changed mid-trajectory. Issues detected: {matches}"
            self.evidence.append(("environment_issues", matches))
            return FailureType.environment_drift, details, confidence
        return None

    def _check_memory_failure(self):
        """Check for memory/context failures"""
        error_text = self._get_error_text()
        patterns = [
            "context length exceeded",
            "maximum context length",
            "token limit",
            "too many tokens",
            "context window",
            "conversation too long",
        ]

        matches = [p for p in patterns if p in error_text]
        if matches:
            confidence = 0.8
            details = f"Agent exceeded context/memory limits. Issues: {matches}"
            self.evidence.append(("memory_issues", matches))
            return FailureType.memory_failure, details, confidence

        # Check if agent forgets previous information
        llm_calls = [s for s in self.trace.steps if s.type == StepType.llm_call]
        if len(llm_calls) > 10:
            # Heuristic: if later calls don't reference earlier context
            confidence = 0.5
            details = (
                "Potential memory failure: long conversation with possible context loss"
            )
            self.evidence.append(("long_conversation", len(llm_calls)))
            return FailureType.memory_failure, details, confidence
        return None

    def _check_api_errors(self):
        """Check for API-specific errors"""
        error_text = self._get_error_text()
        patterns = [
            "internal server error",
            "api error",
            "service error",
            "upstream error",
        ]

        matches = [p for p in patterns if p in error_text]
        if matches:
            confidence = 0.75
            details = f"API service errors detected: {matches}"
            self.evidence.append(("api_errors", matches))
            return FailureType.environment_drift, details, confidence
        return None

    def _check_timeout_issues(self):
        """Check for timeout-related failures"""
        error_text = self._get_error_text()
        patterns = [
            "timed out",
            "deadline exceeded",
            "operation timed out",
            "request timeout",
        ]

        matches = [p for p in patterns if p in error_text]
        if matches:
            confidence = 0.7
            details = f"Timeout issues detected: {matches}"
            self.evidence.append(("timeout_issues", matches))
            return FailureType.tool_failure, details, confidence
        return None

    def _check_resource_exhaustion(self):
        """Check for resource exhaustion issues"""
        error_text = self._get_error_text()
        patterns = [
            "out of memory",
            "disk full",
            "no space left",
            "resource exhausted",
            "quota exceeded",
            "memory limit",
            "cpu limit",
        ]

        matches = [p for p in patterns if p in error_text]
        if matches:
            confidence = 0.8
            details = f"Resource exhaustion detected: {matches}"
            self.evidence.append(("resource_issues", matches))
            return FailureType.environment_drift, details, confidence
        return None

    def generate_fix_suggestions(self, failure_type):
        """Generate specific fix suggestions based on failure type"""
        suggestions = {
            FailureType.grounding_failure: [
                "Add active-window rect validation before UI interactions",
                "Implement retry logic with element re-location",
                "Use screen diff to detect layout shifts before interaction",
                "Add visual verification before click operations",
                "Use tardis export --format negative-pair to fine-tune grounding model",
            ],
            FailureType.tool_failure: [
                "Implement exponential backoff for tool failures",
                "Add tool-specific error handling and recovery",
                "Cache successful tool results to avoid repeated failures",
                "Add LanceDB lookup for known failure patterns before retry",
                "Implement circuit breaker pattern for failing tools",
            ],
            FailureType.reasoning_failure: [
                "Add thought validator that checks for repeated hashes",
                "Implement diversity checks in LLM responses",
                "Add few-shot examples to break repetitive patterns",
                "Increase temperature to reduce deterministic loops",
                "Add explicit step-by-step reasoning requirements",
            ],
            FailureType.memory_failure: [
                "Implement context summarization for long conversations",
                "Add selective context retention based on importance",
                "Use external memory (vector DB) for long-term information",
                "Implement conversation pruning strategies",
                "Add context window monitoring and warnings",
            ],
            FailureType.environment_drift: [
                "Add health checks before operations",
                "Implement retry logic with exponential backoff",
                "Add circuit breaker for external dependencies",
                "Monitor and alert on environment changes",
                "Add graceful degradation for service unavailability",
            ],
        }
        return suggestions.get(
            failure_type, ["Run tardis replay --from <failure-2> to inspect context"]
        )

    def report(self, return_dict: bool = False):
        """Generate comprehensive autopsy report

        Args:
            return_dict: If True, return structured data instead of printing

        Returns:
            If return_dict is True, returns a dict with failure_type, details, confidence,
            statistics, evidence, and suggestions. Otherwise returns None after printing.
        """
        failure_type, details, confidence = self.classify()

        # Build report data
        report_data = {
            "trace_id": self.trace.id,
            "failure_type": failure_type.value,
            "confidence": confidence,
            "details": details,
            "statistics": {
                "total_steps": len(self.trace.steps),
                "duration_seconds": self.trace.get_duration_seconds(),
                "total_cost_usd": self.trace.total_cost_usd,
                "total_tokens": self.trace.total_tokens,
                "success": self.trace.success,
            },
            "step_breakdown": dict(Counter(s.type.value for s in self.trace.steps)),
            "evidence": [(e[0], str(e[1])) for e in self.evidence],
            "suggestions": self.generate_fix_suggestions(failure_type),
        }

        if return_dict:
            return report_data

        # Print formatted report
        print(f"\n[ AUTOPSY REPORT ] Trace {self.trace.id}")
        print("=" * 50)
        print(f"Failure Type: {failure_type.value}")
        print(f"Confidence: {confidence:.1%}")
        print(f"Details: {details}")

        # Show trace statistics
        print("\n[ TRACE STATISTICS ]")
        print(f"Total steps: {len(self.trace.steps)}")
        print(f"Duration: {self.trace.get_duration_seconds():.2f}s")
        print(f"Total cost: ${self.trace.total_cost_usd:.4f}")
        print(f"Total tokens: {self.trace.total_tokens}")
        print(f"Success: {self.trace.success}")

        # Show step breakdown
        print("\n[ STEP BREAKDOWN ]")
        step_types = Counter(s.type.value for s in self.trace.steps)
        for step_type, count in step_types.most_common():
            print(f"  {step_type}: {count}")

        # Show evidence
        if self.evidence:
            print("\n[ EVIDENCE ]")
            for evidence_type, evidence_data in self.evidence:
                print(f"  {evidence_type}: {evidence_data}")

        # Show fix suggestions
        print("\n[ SUGGESTED FIXES ]")
        suggestions = self.generate_fix_suggestions(failure_type)
        for i, suggestion in enumerate(suggestions, 1):
            print(f"  {i}. {suggestion}")

        # Search for similar failures in LanceDB
        store = FailurePatternStore()
        similar = store.search_similar(self.trace, limit=3)
        if similar:
            print("\n[ SIMILAR PAST FAILURES (LanceDB) ]")
            for i, s in enumerate(similar, 1):
                dist = s.get("_distance", 1.0)
                sim_pct = max(0, int((1.0 - dist) * 100)) if dist <= 1.0 else 0
                print(
                    f"  {i}. [{s['failure_type']}] {s['description'][:120]} (similarity: {sim_pct}%, trace: {s['trace_id']})"
                )
            print(f"  Run 'tardis similar {self.trace.id}' for full search results.")

        # Index this failure for future searches
        store.index_trace(self.trace)

        # Show next steps
        print("\n[ NEXT STEPS ]")
        print(
            f"  1. Run: tardis replay {self.trace.id} --from {max(0, len(self.trace.steps) - 5)}"
        )
        print(f"  2. Examine the causal graph: tardis show {self.trace.id}")
        print(f"  3. Search for similar patterns: tardis similar {self.trace.id}")
        print(
            f"  4. If needed, export for training: tardis export {self.trace.id} --format negative-pair"
        )

        return failure_type, details, confidence
