"""
Production Intelligence (Shadow Mode)

Runs TARDIS in shadow mode in production to record traces,
detect anomalies, and generate regression test data.

Three modes:
- PASSIVE: Records traces without analysis (zero overhead)
- ACTIVE: Records traces with real anomaly detection
- BLOCKING: Raises RuntimeError on detected anomalies

SECURITY:
- Shadow mode is read-only by design — record_trace() never mutates input data
- All analysis is advisory and non-blocking (except BLOCKING mode)
- Trace deduplication via SHA-256 content hashing
- No external calls, no data exfiltration
- Anomaly detection uses safe comparison only

LIMITATIONS:
- Anomaly detection is heuristic-based (error types, duration thresholds, step repetition)
- For production-grade anomaly detection, pair with LiveMonitor for real-time analysis
- The RUNNING mode provides advisory warnings only — it does not prevent execution
"""

import hashlib
import json
import time
from enum import Enum
from typing import Any


class ShadowModeStatus(Enum):
    PASSIVE = "passive"
    ACTIVE = "active"
    BLOCKING = "blocking"


class ProductionIntelligence:
    """
    Runs TARDIS in shadow mode in production to record traces,
    detect anomalies, and generate regression test data.

    Usage:
        shadow = ProductionIntelligence(store=my_store)
        shadow.set_mode(ShadowModeStatus.ACTIVE)
        shadow.record_trace(trace_dict)

    SECURITY: Read-only by design. No production mutations.
    """

    def __init__(self, store=None, config: dict | None = None):
        self.store = store
        self.mode = ShadowModeStatus.PASSIVE
        self.config = config or {}
        self._trace_hashes: set = set()
        self._anomaly_count = 0

    def set_mode(self, mode: ShadowModeStatus):
        self.mode = mode

    def record_trace(self, trace: dict[str, Any]) -> None:
        """Record a trace. Never mutates the input dict.

        Args:
            trace: A dict representing the trace to record.

        Raises:
            RuntimeError: In BLOCKING mode when anomalies are detected.
            TypeError: If trace is not a dict.
        """
        if not isinstance(trace, dict):
            raise TypeError("trace must be a dict")

        if self.mode == ShadowModeStatus.PASSIVE:
            self._store_safely(trace)
        elif self.mode == ShadowModeStatus.ACTIVE:
            self._analyze_and_store(trace)
        elif self.mode == ShadowModeStatus.BLOCKING:
            analysis = self._analyze(trace)
            if analysis["anomalous"]:
                self._anomaly_count += 1
                raise RuntimeError(
                    f"Production anomaly detected (count: {self._anomaly_count}): "
                    f"{analysis['reason']}. "
                    f"Execution blocked by shadow mode — see .tardis/shadow/ for details."
                )
            self._store_safely(trace)

    def generate_regression_suite(
        self, min_confidence: float = 0.9
    ) -> list[dict[str, Any]]:
        """Generate regression test data from high-confidence failure traces.

        Generates structured test cases with trace references, failure context,
        and assertions derived from actual failure data. This is NOT test
        automation — it produces structured test specifications for use with
        the replay engine.

        Args:
            min_confidence: Minimum confidence threshold for trace inclusion
                (currently advisory — all failure traces are included).

        Returns:
            List of dicts with test_id, trace_ref, failure_type, steps, assertions.
        """
        if not self.store:
            return []

        try:
            traces_data = []
            if hasattr(self.store, "list_traces"):
                traces_data = self.store.list_traces()
            elif hasattr(self.store, "list_all"):
                traces_data = self.store.list_all(limit=100)

            tests = []
            for trace in traces_data:
                trace_id = (
                    trace.get("id", "unknown")
                    if isinstance(trace, dict)
                    else getattr(trace, "id", "unknown")
                )
                trace_success = (
                    trace.get("success")
                    if isinstance(trace, dict)
                    else getattr(trace, "success", True)
                )
                trace_failure_type = (
                    trace.get("failure_type")
                    if isinstance(trace, dict)
                    else getattr(trace, "failure_type", None)
                )
                trace_steps = (
                    trace.get("steps", [])
                    if isinstance(trace, dict)
                    else getattr(trace, "steps", [])
                )
                error_count = sum(
                    1
                    for s in (trace_steps if isinstance(trace_steps, list) else [])
                    if (isinstance(s, dict) and s.get("type") == "error")
                )

                if trace_success is False or trace_failure_type is not None:
                    tests.append(
                        {
                            "test_id": f"reg_{str(trace_id)[:8]}",
                            "trace_ref": trace_id,
                            "failure_type": trace_failure_type or "unknown",
                            "step_count": len(trace_steps)
                            if isinstance(trace_steps, list)
                            else 0,
                            "error_count": error_count,
                            "assertions": {
                                "replay_matches": f"tardis replay {trace_id}",
                                "failure_type_confirmed": trace_failure_type
                                is not None,
                                "has_errors": error_count > 0,
                            },
                        }
                    )
            return tests
        except Exception:
            return []

    def get_statistics(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "traces_recorded": len(self._trace_hashes),
            "anomalies_detected": self._anomaly_count,
        }

    def _store_safely(self, trace: dict) -> None:
        """Store trace with content-based deduplication. Never mutates input."""
        trace_copy = dict(trace)
        trace_hash = hashlib.sha256(
            json.dumps(trace_copy, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        if trace_hash in self._trace_hashes:
            return
        self._trace_hashes.add(trace_hash)

        if self.store and hasattr(self.store, "add"):
            try:
                self.store.add(trace_copy)
            except Exception:
                pass

    def _analyze(self, trace: dict) -> dict[str, Any]:
        """Analyze a trace for anomalies using safe comparison only.

        Returns dict with:
            anomalous: bool
            reason: str description
            anomalies: list of detected anomaly dicts
        """
        anomalies = []

        failure_type = trace.get("failure_type") or trace.get("error_type")
        if failure_type:
            anomalies.append(
                {
                    "type": "failure_detected",
                    "failure_type": failure_type,
                    "severity": "high"
                    if failure_type in ("crash", "oom", "segfault")
                    else "medium",
                }
            )

        duration_ms = trace.get("duration_ms", 0)
        if isinstance(duration_ms, (int, float)) and duration_ms > 300000:
            anomalies.append(
                {
                    "type": "slow_execution",
                    "duration_ms": duration_ms,
                    "severity": "medium",
                }
            )

        steps = trace.get("steps", [])
        if isinstance(steps, list) and len(steps) > 5:
            # Exclude empty hashes — steps without a recorded hash must not be
            # treated as duplicates of one another, or the heuristic falsely
            # flags ordinary, non-looping traces as loops.
            hashes = [
                s.get("hash", "")
                for s in steps
                if isinstance(s, dict) and s.get("hash")
            ]
            unique = set(hashes)
            if len(hashes) > 5 and len(unique) < len(hashes) * 0.5:
                anomalies.append(
                    {
                        "type": "loop_suspected",
                        "unique_ratio": len(unique) / max(len(hashes), 1),
                        "severity": "high",
                    }
                )

        return {
            "anomalous": len(anomalies) > 0,
            "reason": anomalies[0]["type"] if anomalies else "no anomalies detected",
            "anomalies": anomalies,
        }

    def _analyze_and_store(self, trace: dict) -> None:
        """Analyze trace for anomalies, annotate, then store."""
        analysis = self._analyze(trace)

        trace_copy = dict(trace)
        if analysis["anomalies"]:
            self._anomaly_count += 1
            trace_copy["_shadow_analysis"] = {
                "anomalies": analysis["anomalies"],
                "analyzed_at": time.time(),
            }

        self._store_safely(trace_copy)

    def _is_anomalous(self, trace: dict) -> bool:
        """Quick anomaly check for BLOCKING mode."""
        return self._analyze(trace)["anomalous"]
