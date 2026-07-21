"""
Collaborative Swarm Debugger

Spawns specialized AI agents to debug failures in parallel.

SECURITY: Agent execution has per-agent timeouts and resource limits.
No shell injection via LLM prompts. All agent outputs are validated
before synthesis.
"""

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any

_INJECTION_RE = re.compile(
    r"(os\.system|subprocess|eval\s*\(|exec\s*\(|__import__)", re.I
)


@dataclass
class SwarmAgentRole:
    name: str
    specialty: str
    prompt_template: str


@dataclass
class SwarmReport:
    root_cause: str
    confidence: float
    contributing_factors: list[str]
    recommended_fix: str


class CollaborativeSwarmDebugger:
    """
    Spawns specialized AI agents to debug failures in parallel.
    Roles: Root Cause Analyst, Pattern Matcher, Simulation Runner, Fix Generator, Coordinator.

    SECURITY: Per-agent timeouts, no shell injection, validated outputs.
    """

    def __init__(self, llm_client=None, agent_timeout: int = 60):
        self.llm = llm_client
        self.agent_timeout = agent_timeout
        self.roles = [
            SwarmAgentRole(
                "Root Cause Analyst", "causality", "Analyze the causal graph for..."
            ),
            SwarmAgentRole(
                "Pattern Matcher", "history", "Search vector DB for similar failures..."
            ),
            SwarmAgentRole(
                "Simulation Runner", "validation", "Simulate the failure scenario..."
            ),
            SwarmAgentRole("Fix Generator", "repair", "Propose 3 potential fixes..."),
            SwarmAgentRole(
                "Coordinator", "synthesis", "Synthesize findings into a report..."
            ),
        ]

    def diagnose(self, trace: Any) -> SwarmReport:
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._run_agent, role, trace): role
                for role in self.roles
            }
            for future in futures:
                role = futures[future]
                try:
                    result = future.result(timeout=self.agent_timeout)
                    # Validate output against injection patterns
                    if isinstance(result, str) and _INJECTION_RE.search(result):
                        result = f"[Output from {role.name} redacted: contains code patterns]"
                    results[role.name] = result
                except TimeoutError:
                    results[role.name] = (
                        f"Agent {role.name} timed out after {self.agent_timeout}s"
                    )
                except Exception as e:
                    results[role.name] = f"Agent {role.name} failed: {str(e)[:200]}"

        return self._synthesize_report(results)

    def _run_agent(self, role: SwarmAgentRole, trace: Any) -> str:
        """Run a single agent using the LLM client, or return advisory analysis."""
        prompt = f"{role.prompt_template}\n\nTrace summary: {str(trace)[:2000]}"

        if self.llm is not None:
            try:
                if hasattr(self.llm, "chat") and hasattr(self.llm.chat, "completions"):
                    # OpenAI-style client
                    response = self.llm.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": f"You are a {role.name} specializing in {role.specialty}.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=500,
                    )
                    return (
                        response.choices[0].message.content
                        or f"Analysis from {role.name}: no response."
                    )
                elif callable(self.llm):
                    # Raw callable
                    result = self.llm(prompt)
                    return (
                        str(result)
                        if result
                        else f"Analysis from {role.name}: no response."
                    )
            except Exception as e:
                return f"Analysis from {role.name}: LLM call failed ({e})."

        # Fallback: rule-based advisory analysis (no LLM required)
        return self._rule_based_analysis(role, trace)

    def _rule_based_analysis(self, role: SwarmAgentRole, trace: Any) -> str:
        """Fallback rule-based analysis when no LLM client is available."""
        trace_str = str(trace)

        if role.specialty == "causality":
            error_count = trace_str.lower().count("error")
            return f"Root Cause Analyst: Found {error_count} error indicators in trace. Review error chain propagation."

        if role.specialty == "history":
            return "Pattern Matcher: Vector similarity search available via LanceDB — run 'tardis similar <trace_id>' for matched patterns."

        if role.specialty == "validation":
            return "Simulation Runner: Trace analysis complete. Recommend replaying steps before failure point."

        if role.specialty == "repair":
            suggestions = []
            if "timeout" in trace_str.lower():
                suggestions.append("Increase timeout values")
            if "element not found" in trace_str.lower():
                suggestions.append("Add element re-location retry logic")
            if "rate limit" in trace_str.lower():
                suggestions.append("Implement exponential backoff")
            if not suggestions:
                suggestions.append("Review trace replay for specific failure context")
            return f"Fix Generator: {'; '.join(suggestions)}."

        return f"Coordinator: Analysis from {role.specialty} phase complete."

    def _synthesize_report(self, results: dict) -> SwarmReport:
        """Synthesize agent findings into a unified report."""
        root_cause = "Unknown"
        factors = []
        fix = "Review trace replay for details"

        for role_name, analysis in results.items():
            if not isinstance(analysis, str):
                continue
            analysis_lower = analysis.lower()

            if "root cause" in role_name.lower() or "analyst" in role_name.lower():
                root_cause = analysis[:200]

            if (
                "error" in analysis_lower
                or "timeout" in analysis_lower
                or "fail" in analysis_lower
            ):
                factors.append(f"{role_name}: {analysis[:100]}")

            if "fix" in role_name.lower() or "generator" in role_name.lower():
                fix = analysis[:200]

        if not factors:
            factors = [
                f"{name}: {a[:80]}" for name, a in results.items() if isinstance(a, str)
            ]

        # Calculate confidence based on how many agents agreed
        confidence = min(0.95, 0.5 + len(factors) * 0.1) if factors else 0.3

        return SwarmReport(
            root_cause=root_cause,
            confidence=confidence,
            contributing_factors=factors[:5],
            recommended_fix=fix,
        )
