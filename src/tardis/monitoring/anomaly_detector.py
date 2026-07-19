"""Real-time anomaly detection for TARDIS traces.

Detects statistical anomalies in token usage, latency, error rates, and tool failures
as traces are being recorded, enabling proactive failure prevention.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Deque
from collections import deque
import threading
from datetime import datetime

from ..models import Trace, Step, StepType


class AnomalyType(Enum):
    """Types of detectable anomalies."""
    TOKEN_SPIKE = "token_spike"
    LATENCY_SPIKE = "latency_spike"
    ERROR_RATE_SURGE = "error_rate_surge"
    TOOL_FAILURE_CLUSTER = "tool_failure_cluster"
    LOOP_DETECTED = "loop_detected"
    CONTEXT_OVERFLOW_RISK = "context_overflow_risk"
    COST_ANOMALY = "cost_anomaly"
    GROUNDING_DRIFT = "grounding_drift"


@dataclass
class AnomalyEvent:
    """Represents a detected anomaly."""
    anomaly_type: AnomalyType
    severity: float  # 0.0 to 1.0
    description: str
    step_index: int
    trace_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    evidence: Dict = field(default_factory=dict)
    suggested_action: str = ""
    
    def to_dict(self) -> dict:
        return {
            "type": self.anomaly_type.value,
            "severity": self.severity,
            "description": self.description,
            "step_index": self.step_index,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat(),
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
        }


class AnomalyDetector:
    """Statistical anomaly detector for TARDIS traces.
    
    Uses rolling windows, z-scores, and exponential moving averages to detect
    anomalies in real-time as steps are added to a trace.
    """
    
    def __init__(self, window_size: int = 20, z_threshold: float = 2.5):
        self.window_size = window_size
        self.z_threshold = z_threshold
        
        # Rolling windows for different metrics
        self._token_counts: Deque[int] = deque(maxlen=window_size)
        self._latencies: Deque[float] = deque(maxlen=window_size)
        self._costs: Deque[float] = deque(maxlen=window_size)
        self._error_flags: Deque[bool] = deque(maxlen=window_size)
        self._tool_failures: Deque[bool] = deque(maxlen=window_size)
        
        # Running statistics
        self._token_mean = 0.0
        self._token_std = 1.0
        self._latency_mean = 0.0
        self._latency_std = 1.0
        self._cost_mean = 0.0
        self._cost_std = 1.0
        
        # State tracking
        self._consecutive_errors = 0
        self._recent_tool_failures = 0
        self._hash_history: Deque[str] = deque(maxlen=50)
        self._total_tokens = 0
        self._context_limit = 128000  # GPT-4 Turbo context window
        
        self._lock = threading.Lock()
        self._callbacks: List[callable] = []
    
    def register_callback(self, callback: callable):
        """Register a callback to be called when an anomaly is detected."""
        self._callbacks.append(callback)
    
    def _notify(self, anomaly: AnomalyEvent):
        """Notify all registered callbacks of an anomaly."""
        for callback in self._callbacks:
            try:
                callback(anomaly)
            except Exception:
                pass  # Never let callback errors break detection
    
    def _update_stats(self, values: Deque[float]) -> tuple:
        """Calculate mean and std for a rolling window."""
        if len(values) < 3:
            return (0.0, 1.0)
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0
        return (mean, std)
    
    def _z_score(self, value: float, mean: float, std: float) -> float:
        """Calculate z-score for a value."""
        if std < 1e-6:
            return 0.0
        return abs(value - mean) / std
    
    def process_step(self, step: Step, trace_id: str, step_index: int) -> List[AnomalyEvent]:
        """Process a step and detect any anomalies.
        
        Returns a list of detected anomaly events.
        """
        anomalies = []
        
        with self._lock:
            # Extract metrics from step
            token_count = 0
            latency = 0.0
            cost = 0.0
            is_error = False
            is_tool_failure = False
            
            if step.step_type == StepType.llm_call:
                metadata = step.metadata or {}
                token_count = metadata.get("total_tokens", 0)
                latency = metadata.get("duration", 0.0)
                cost = metadata.get("cost", 0.0)
                self._total_tokens += token_count
                
                # Check for hash repetition (loop detection)
                response_hash = metadata.get("response_hash", "")
                if response_hash:
                    if response_hash in self._hash_history:
                        anomalies.append(self._create_anomaly(
                            AnomalyType.LOOP_DETECTED,
                            step_index,
                            trace_id,
                            f"LLM response hash repeated - possible infinite loop",
                            {"hash": response_hash, "history_count": len(self._hash_history)},
                            "Review agent logic for termination conditions"
                        ))
                    self._hash_history.append(response_hash)
                
                self._token_counts.append(token_count)
                self._latencies.append(latency)
                self._costs.append(cost)
                
                # Update running stats
                self._token_mean, self._token_std = self._update_stats(self._token_counts)
                self._latency_mean, self._latency_std = self._update_stats(self._latencies)
                self._cost_mean, self._cost_std = self._update_stats(self._costs)
                
                # Check for token spikes
                if len(self._token_counts) >= 5:
                    z = self._z_score(token_count, self._token_mean, self._token_std)
                    if z > self.z_threshold:
                        severity = min(1.0, (z - self.z_threshold) / 3.0)
                        anomalies.append(self._create_anomaly(
                            AnomalyType.TOKEN_SPIKE,
                            step_index,
                            trace_id,
                            f"Token usage spike: {token_count} tokens (z={z:.2f})",
                            {"tokens": token_count, "mean": self._token_mean, "z_score": z},
                            "Check if LLM is generating excessive output or stuck in reasoning loop"
                        ))
                
                # Check for latency spikes
                if len(self._latencies) >= 5:
                    z = self._z_score(latency, self._latency_mean, self._latency_std)
                    if z > self.z_threshold:
                        severity = min(1.0, (z - self.z_threshold) / 3.0)
                        anomalies.append(self._create_anomaly(
                            AnomalyType.LATENCY_SPIKE,
                            step_index,
                            trace_id,
                            f"Latency spike: {latency:.2f}s (z={z:.2f})",
                            {"latency": latency, "mean": self._latency_mean, "z_score": z},
                            "Check API status or network connectivity"
                        ))
                
                # Check for cost anomalies
                if len(self._costs) >= 5:
                    z = self._z_score(cost, self._cost_mean, self._cost_std)
                    if z > self.z_threshold:
                        severity = min(1.0, (z - self.z_threshold) / 3.0)
                        anomalies.append(self._create_anomaly(
                            AnomalyType.COST_ANOMALY,
                            step_index,
                            trace_id,
                            f"Cost anomaly: ${cost:.4f} (z={z:.2f})",
                            {"cost": cost, "mean": self._cost_mean, "z_score": z},
                            "Review token usage and model selection"
                        ))
            
            elif step.step_type == StepType.error:
                is_error = True
                self._consecutive_errors += 1
                
                if self._consecutive_errors >= 3:
                    severity = min(1.0, 0.5 + (self._consecutive_errors - 3) * 0.15)
                    anomalies.append(self._create_anomaly(
                        AnomalyType.ERROR_RATE_SURGE,
                        step_index,
                        trace_id,
                        f"Consecutive error streak: {self._consecutive_errors} errors",
                        {"consecutive_errors": self._consecutive_errors},
                        "Agent may be in degraded state - consider intervention"
                    ))
            
            elif step.step_type == StepType.tool_call:
                output = step.output or {}
                if output.get("success") is False or "error" in output:
                    is_tool_failure = True
                    self._recent_tool_failures += 1
                else:
                    self._recent_tool_failures = max(0, self._recent_tool_failures - 1)
                
                # Check for tool failure clustering
                if self._recent_tool_failures >= 3:
                    severity = min(1.0, 0.4 + (self._recent_tool_failures - 3) * 0.15)
                    anomalies.append(self._create_anomaly(
                        AnomalyType.TOOL_FAILURE_CLUSTER,
                        step_index,
                        trace_id,
                        f"Tool failure cluster: {self._recent_tool_failures} recent failures",
                        {"recent_failures": self._recent_tool_failures},
                        "Check tool implementation and environment state"
                    ))
            
            elif step.step_type == StepType.dom_snapshot:
                # Check for grounding drift (layout shifts)
                output = step.output or {}
                layout_shift = output.get("layout_shift_score", 0)
                if layout_shift > 0.3:  # 30% layout change
                    severity = min(1.0, layout_shift)
                    anomalies.append(self._create_anomaly(
                        AnomalyType.GROUNDING_DRIFT,
                        step_index,
                        trace_id,
                        f"Significant layout drift detected: {layout_shift:.1%}",
                        {"layout_shift": layout_shift},
                        "Page may have reloaded or dynamic content changed - re-ground agent"
                    ))
            
            # Reset error counter on success
            if not is_error:
                self._consecutive_errors = 0
            
            # Check context overflow risk
            if self._total_tokens > self._context_limit * 0.8:
                severity = (self._total_tokens - self._context_limit * 0.8) / (self._context_limit * 0.2)
                severity = min(1.0, severity)
                anomalies.append(self._create_anomaly(
                    AnomalyType.CONTEXT_OVERFLOW_RISK,
                    step_index,
                    trace_id,
                    f"Context window at {self._total_tokens/self._context_limit:.1%} capacity",
                    {"total_tokens": self._total_tokens, "limit": self._context_limit},
                    "Consider truncating conversation history or summarizing"
                ))
        
        # Notify callbacks
        for anomaly in anomalies:
            self._notify(anomaly)
        
        return anomalies
    
    def _create_anomaly(self, anomaly_type: AnomalyType, step_index: int, 
                       trace_id: str, description: str, evidence: dict, 
                       suggested_action: str) -> AnomalyEvent:
        """Create an anomaly event with calculated severity."""
        base_severity = {
            AnomalyType.TOKEN_SPIKE: 0.5,
            AnomalyType.LATENCY_SPIKE: 0.4,
            AnomalyType.ERROR_RATE_SURGE: 0.7,
            AnomalyType.TOOL_FAILURE_CLUSTER: 0.6,
            AnomalyType.LOOP_DETECTED: 0.8,
            AnomalyType.CONTEXT_OVERFLOW_RISK: 0.6,
            AnomalyType.COST_ANOMALY: 0.5,
            AnomalyType.GROUNDING_DRIFT: 0.5,
        }.get(anomaly_type, 0.5)
        
        return AnomalyEvent(
            anomaly_type=anomaly_type,
            severity=base_severity,
            description=description,
            step_index=step_index,
            trace_id=trace_id,
            evidence=evidence,
            suggested_action=suggested_action,
        )
    
    def reset(self):
        """Reset all statistics and state."""
        with self._lock:
            self._token_counts.clear()
            self._latencies.clear()
            self._costs.clear()
            self._error_flags.clear()
            self._tool_failures.clear()
            self._hash_history.clear()
            self._token_mean = 0.0
            self._token_std = 1.0
            self._latency_mean = 0.0
            self._latency_std = 1.0
            self._cost_mean = 0.0
            self._cost_std = 1.0
            self._consecutive_errors = 0
            self._recent_tool_failures = 0
            self._total_tokens = 0
    
    def get_summary(self) -> dict:
        """Get current statistical summary."""
        with self._lock:
            return {
                "token_stats": {"mean": self._token_mean, "std": self._token_std, "window": len(self._token_counts)},
                "latency_stats": {"mean": self._latency_mean, "std": self._latency_std, "window": len(self._latencies)},
                "cost_stats": {"mean": self._cost_mean, "std": self._cost_std, "window": len(self._costs)},
                "consecutive_errors": self._consecutive_errors,
                "recent_tool_failures": self._recent_tool_failures,
                "total_tokens": self._total_tokens,
                "context_utilization": self._total_tokens / self._context_limit,
            }
