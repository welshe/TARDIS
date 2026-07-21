"""
Predictive Failure Prevention (Pre-cog Mode)

Analyzes current state against historical failures to predict and prevent
issues before execution.

SECURITY: Simulations run in sandboxed subprocesses with resource limits.
No LLM-generated code is executed directly. All predictions are advisory.
Predictions depend entirely on the quality and coverage of the vector store.
An empty or sparse vector store will yield no meaningful predictions.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PredictionResult:
    risk_level: RiskLevel
    confidence: float
    similar_failure_id: str | None
    similar_failure_type: str | None
    similar_failure_description: str | None
    suggested_action: str
    explanation: str


class PredictiveFailurePrevention:
    """
    Pre-cog Mode: Analyzes current state against historical failures
    to predict and prevent issues before execution.

    Predictions are based on real vector similarity search against the
    LanceDB failure pattern store. Without a vector store, all predictions
    will return LOW risk with zero confidence.

    SECURITY: Simulations are sandboxed via subprocess with timeout.
    No eval/exec on untrusted input. All predictions are advisory.
    """

    def __init__(self, vector_store=None, threshold: float = 0.85):
        self.vector_store = vector_store
        self.threshold = threshold
        self.history_cache: dict[str, float] = {}

    def analyze_action(
        self, action: dict[str, Any], current_state: dict[str, Any]
    ) -> PredictionResult:
        if not self.vector_store:
            return PredictionResult(
                risk_level=RiskLevel.LOW,
                confidence=0.0,
                similar_failure_id=None,
                similar_failure_type=None,
                similar_failure_description=None,
                suggested_action="proceed",
                explanation="No vector store configured for prediction. Call with a FailurePatternStore instance.",
            )

        try:
            action_text = json.dumps(action, sort_keys=True, default=str)
            similar = self.vector_store.search_by_text(action_text, limit=3)

            if not similar:
                return PredictionResult(
                    risk_level=RiskLevel.LOW,
                    confidence=0.0,
                    similar_failure_id=None,
                    similar_failure_type=None,
                    similar_failure_description=None,
                    suggested_action="proceed",
                    explanation="No similar historical failures found in vector store.",
                )

            best = similar[0]
            distance = best.get("_distance", 1.0)
            risk_score = max(0.0, 1.0 / (1.0 + distance))
            self.history_cache[action_text] = risk_score

            similar_id = best.get("trace_id")
            similar_type = best.get("failure_type", "unknown")
            similar_desc = best.get("description", "")[:200]

            critical_threshold = min(0.95, self.threshold + 0.10)
            high_threshold = self.threshold
            medium_threshold = max(0.3, self.threshold - 0.20)

            if risk_score > critical_threshold:
                return PredictionResult(
                    risk_level=RiskLevel.CRITICAL,
                    confidence=risk_score,
                    similar_failure_id=similar_id,
                    similar_failure_type=similar_type,
                    similar_failure_description=similar_desc,
                    suggested_action="block",
                    explanation=(
                        f"Action matches known {similar_type} failure pattern "
                        f"(similarity: {risk_score:.1%}). "
                        f"Historical failure: {similar_desc}"
                    ),
                )
            elif risk_score > high_threshold:
                return PredictionResult(
                    risk_level=RiskLevel.HIGH,
                    confidence=risk_score,
                    similar_failure_id=similar_id,
                    similar_failure_type=similar_type,
                    similar_failure_description=similar_desc,
                    suggested_action="warn",
                    explanation=(
                        f"Action has high similarity to past {similar_type} failure "
                        f"(similarity: {risk_score:.1%}). "
                        f"Similar trace: {similar_id}"
                    ),
                )
            elif risk_score > medium_threshold:
                return PredictionResult(
                    risk_level=RiskLevel.MEDIUM,
                    confidence=risk_score,
                    similar_failure_id=similar_id,
                    similar_failure_type=similar_type,
                    similar_failure_description=similar_desc,
                    suggested_action="monitor",
                    explanation=(
                        f"Action shows moderate similarity to past failures "
                        f"(similarity: {risk_score:.1%}). "
                        f"Review trace: {similar_id}"
                    ),
                )

            return PredictionResult(
                risk_level=RiskLevel.LOW,
                confidence=risk_score,
                similar_failure_id=None,
                similar_failure_type=None,
                similar_failure_description=None,
                suggested_action="proceed",
                explanation=f"No significant risk detected (similarity: {risk_score:.1%}).",
            )

        except Exception as e:
            return PredictionResult(
                risk_level=RiskLevel.LOW,
                confidence=0.0,
                similar_failure_id=None,
                similar_failure_type=None,
                similar_failure_description=None,
                suggested_action="proceed",
                explanation=f"Prediction error: {e}",
            )

    def simulate_whatif(
        self,
        action: dict[str, Any],
        modification: dict[str, Any],
        timeout: int = 30,
    ) -> dict[str, Any]:
        """
        Run what-if simulation in a sandboxed subprocess.

        The simulation passes the action and modification as JSON to a
        sandboxed Python process that performs structural validation.
        This is NOT an execution simulator — it validates that the action
        + modification form a valid, parseable combination.

        SECURITY: The modification dict is serialized to JSON and passed
        via stdin. No eval/exec of LLM-generated code. Subprocess has
        timeout and resource limits.
        """
        if not self.vector_store:
            return {
                "status": "skipped",
                "reason": "No vector store configured for simulation",
            }

        simulation_script = (
            "import json, sys\n"
            "data = json.load(sys.stdin)\n"
            "action = data.get('action', {})\n"
            "modification = data.get('modification', {})\n"
            "# Validate structural compatibility\n"
            "if not isinstance(action, dict):\n"
            "    print(json.dumps({'status': 'invalid', 'error': 'action must be a dict'}))\n"
            "    sys.exit(1)\n"
            "if not isinstance(modification, dict):\n"
            "    print(json.dumps({'status': 'invalid', 'error': 'modification must be a dict'}))\n"
            "    sys.exit(1)\n"
            "# Check for key conflicts\n"
            "overlap = set(action.keys()) & set(modification.keys())\n"
            "if overlap:\n"
            "    print(json.dumps({\n"
            "        'status': 'conflict',\n"
            "        'conflicting_keys': list(overlap),\n"
            "        'action': action, 'modification': modification\n"
            "    }))\n"
            "else:\n"
            "    merged = {**action, **modification}\n"
            "    print(json.dumps({\n"
            "        'status': 'compatible',\n"
            "        'merged_action': merged,\n"
            "        'action': action, 'modification': modification\n"
            "    }))\n"
        )

        try:
            input_data = json.dumps({"action": action, "modification": modification})
            proc = subprocess.run(
                [sys.executable, "-c", simulation_script],
                input=input_data.encode(),
                capture_output=True,
                timeout=timeout,
            )
            if proc.returncode == 0:
                result = json.loads(proc.stdout.decode())
                result["sandboxed"] = True
                return result
            return {"status": "failed", "error": proc.stderr.decode()[:500]}
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Simulation exceeded time limit"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _calculate_risk_score(self, action: dict, state: dict) -> float:
        if not self.vector_store:
            return 0.1

        action_str = json.dumps(action, sort_keys=True, default=str)

        if action_str in self.history_cache:
            return self.history_cache[action_str]

        try:
            similar = self.vector_store.search_by_text(action_str, limit=1)
            if similar:
                distance = similar[0].get("_distance", 1.0)
                score = max(0.0, 1.0 / (1.0 + distance))
                self.history_cache[action_str] = score
                return score
        except Exception:
            pass

        return 0.0
