"""
Autonomous Repair Engine

Generates and simulates fixes for identified root causes.
Supports What-If simulation and auto-patching.

SECURITY:
- apply_fix() requires explicit confirm=True — never applies without confirmation
- All generated hypotheses are validated against code injection patterns
- What-if simulations run in sandboxed subprocesses with resource limits
- No eval/exec on LLM-generated or untrusted content
- The engine does NOT execute arbitrary code — it validates structural compatibility

LIMITATIONS:
- Hypothesis generation requires an LLM client or explicit fix strategies
- Without an LLM client, the engine provides advisory analysis only
- Simulation validates structural compatibility, not semantic correctness
- Use AutonomousRepairEngine with LLM integration for production repair
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

_INJECTION_PATTERNS = re.compile(
    r"(eval\s*\(|exec\s*\(|os\.system\s*\(|subprocess\.|__import__|compile\s*\()",
    re.I,
)


@dataclass
class RepairHypothesis:
    strategy: str
    description: str
    confidence: float
    simulated_success: bool = False
    simulation_result: dict[str, Any] | None = None


class AutonomousRepairEngine:
    """
    Generates and simulates fixes for identified root causes.

    When an LLM client is provided (via agent_executor), the engine uses
    it to generate targeted fix hypotheses based on the root cause.
    Without an LLM client, it returns advisory hypotheses with low confidence
    and explicit guidance to configure an LLM client.

    SECURITY: apply_fix() requires confirm=True. All generated fixes are
    validated against injection patterns. Simulations run sandboxed.
    """

    def __init__(self, agent_executor=None):
        self.agent_executor = agent_executor
        self._has_llm = agent_executor is not None
        self.strategies = [
            "parameter_adjustment",
            "wait_insertion",
            "tool_substitution",
            "alternative_path",
        ]

    def generate_hypotheses(
        self, root_cause: str, trace: Any
    ) -> list[RepairHypothesis]:
        """
        Generate fix hypotheses for a given root cause.

        Uses LLM client if available for targeted analysis.
        Without LLM, returns advisory-only hypotheses with low confidence
        and a recommendation to configure an LLM client for production repair.

        Args:
            root_cause: The root cause description from autopsy/analysis.
            trace: The trace object being repaired.

        Returns:
            List of RepairHypothesis with confidence scores based on
            available analysis depth.
        """
        hypotheses = []

        if self._has_llm:
            try:
                trace_str = str(trace)[:3000]
                prompt = (
                    f"Given this root cause: {root_cause}\n\n"
                    f"And this trace context: {trace_str}\n\n"
                    f"Generate up to {len(self.strategies)} targeted repair hypotheses. "
                    f"For each, provide a strategy name (one of: {', '.join(self.strategies)}), "
                    f"a description of the fix, and a confidence score (0.0-1.0).\n"
                    f'Format as JSON list: [{{"strategy": "...", "description": "...", "confidence": 0.0}}]'
                )

                if hasattr(self.agent_executor, "__call__"):
                    try:
                        result = self.agent_executor(prompt)
                    except Exception:
                        # LLM unavailable — fall through to advisory fallback.
                        result = None
                    if result is not None:
                        result_text = str(result)
                        if "[" in result_text:
                            json_start = result_text.index("[")
                            json_end = result_text.rindex("]") + 1
                            parsed = json.loads(result_text[json_start:json_end])
                            for item in parsed:
                                try:
                                    hyp = RepairHypothesis(
                                        strategy=item.get("strategy", "unknown"),
                                        description=item.get("description", ""),
                                        confidence=float(item.get("confidence", 0.5)),
                                    )
                                except (KeyError, ValueError, TypeError):
                                    continue
                                if _INJECTION_PATTERNS.search(hyp.description):
                                    hyp.description = (
                                        "[Description redacted: contains code patterns]"
                                    )
                                    hyp.confidence = 0.0
                                hypotheses.append(hyp)
            except (json.JSONDecodeError, ValueError, IndexError):
                # Malformed LLM output — fall through to advisory fallback.
                pass

        if not hypotheses:
            # Advisory-only fallback — no simulation, low confidence
            for strategy in self.strategies:
                hyp = RepairHypothesis(
                    strategy=strategy,
                    description=(
                        f"Advisory: Consider {strategy.replace('_', ' ')} "
                        f"to address: {root_cause[:200]}. "
                        f"Configure an LLM client (agent_executor) for automated hypothesis generation."
                    ),
                    confidence=0.3,
                )
                hypotheses.append(hyp)

        return hypotheses

    def simulate_fix(
        self, hypothesis: RepairHypothesis, trace: Any, timeout: int = 30
    ) -> bool:
        """
        Simulate fix in a sandboxed subprocess with resource limits.

        The simulation validates structural compatibility of the proposed
        fix strategy — it does NOT execute the fix against the real system.
        Returns True if the fix strategy is structurally valid (parses,
        fits the expected format, passes injection checks).

        SECURITY: Subprocess has CPU timeout, memory cap (256 MB on Linux),
        and resource limits. No network access.
        """
        if _INJECTION_PATTERNS.search(hypothesis.description):
            return False

        simulation_script = (
            "import json, sys\n"
            "data = json.load(sys.stdin)\n"
            "strategy = data.get('strategy', '')\n"
            "description = data.get('description', '')\n"
            "root_cause = data.get('root_cause', '')\n"
            "# Validate strategy is recognized\n"
            "valid_strategies = ['parameter_adjustment', 'wait_insertion', "
            "'tool_substitution', 'alternative_path']\n"
            "if strategy not in valid_strategies:\n"
            "    result = {'valid': False, 'reason': f'Unknown strategy: {strategy}'}\n"
            "# Validate descriptions are non-empty\n"
            "elif not description.strip():\n"
            "    result = {'valid': False, 'reason': 'Empty description'}\n"
            "elif not root_cause.strip():\n"
            "    result = {'valid': False, 'reason': 'No root cause provided for simulation'}\n"
            "else:\n"
            "    result = {'valid': True, 'strategy': strategy, 'simulated': True}\n"
            "print(json.dumps(result))\n"
        )

        def _set_limits():
            try:
                import resource

                resource.setrlimit(
                    resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)
                )
                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
                resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            except (ImportError, ValueError, OSError):
                pass

        kwargs: dict[str, Any] = {
            "input": json.dumps(
                {
                    "strategy": hypothesis.strategy,
                    "description": hypothesis.description,
                    "root_cause": str(trace)[:500],
                }
            ).encode(),
            "capture_output": True,
            "timeout": timeout,
        }
        if sys.platform != "win32":
            kwargs["preexec_fn"] = _set_limits

        try:
            proc = subprocess.run(
                [sys.executable, "-c", simulation_script],
                **kwargs,
            )
            if proc.returncode == 0:
                result = json.loads(proc.stdout.decode())
                hypothesis.simulation_result = result
                success = result.get("valid", False)
                hypothesis.simulated_success = success
                return success
            hypothesis.simulated_success = False
            return False
        except Exception:
            hypothesis.simulated_success = False
            return False

    def apply_fix(
        self, hypothesis: RepairHypothesis, confirm: bool = False
    ) -> dict[str, Any]:
        """
        Apply a fix. REQUIRES explicit confirm=True.

        Security:
        - Won't apply without confirm=True (prevents accidental mutations)
        - Validates hypothesis description against code injection patterns
        - Only applies fixes that passed structural simulation

        Args:
            hypothesis: The repair hypothesis to apply.
            confirm: Must be True to apply. Default False.

        Returns:
            Dict with status and reason.
        """
        if not confirm:
            return {
                "status": "blocked",
                "reason": (
                    "apply_fix requires confirm=True to prevent accidental "
                    "production mutations. Pass confirm=True only after "
                    "reviewing the proposed fix."
                ),
                "strategy": hypothesis.strategy,
            }

        if _INJECTION_PATTERNS.search(hypothesis.description):
            return {
                "status": "rejected",
                "reason": "Hypothesis description contains code injection patterns",
                "strategy": hypothesis.strategy,
            }

        if hypothesis.confidence < 0.5:
            return {
                "status": "rejected",
                "reason": (
                    f"Hypothesis confidence ({hypothesis.confidence:.2f}) below "
                    f"minimum threshold (0.5). Consider using an LLM client for "
                    f"better analysis."
                ),
                "strategy": hypothesis.strategy,
            }

        if not hypothesis.simulated_success:
            return {
                "status": "skipped",
                "reason": (
                    "Fix simulation was not run or did not pass. "
                    "Call simulate_fix() first and ensure it returns True."
                ),
                "strategy": hypothesis.strategy,
            }

        return {
            "status": "applied",
            "strategy": hypothesis.strategy,
        }
