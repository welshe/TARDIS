"""Live monitoring dashboard for TARDIS traces.

Provides real-time visualization and alerting for trace metrics,
anomaly detection, and agent health monitoring.
"""

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..models import Step, StepType, Trace
from .anomaly_detector import AnomalyDetector, AnomalyEvent


@dataclass
class MonitorConfig:
    """Configuration for the live monitor."""

    refresh_interval: float = 1.0  # seconds
    anomaly_threshold: float = 0.7  # severity threshold for alerts
    max_history: int = 1000  # max events to keep in history
    enable_alerts: bool = True
    alert_callback: Callable[[AnomalyEvent], None] | None = None
    log_file: str | None = None


class LiveMonitor:
    """Real-time monitoring dashboard for TARDIS traces.

    Combines anomaly detection with live metrics visualization,
    alerting, and historical analysis.
    """

    def __init__(self, config: MonitorConfig | None = None):
        self.config = config or MonitorConfig()
        self.detector = AnomalyDetector()
        self.detector.register_callback(self._on_anomaly)

        self._active_traces: dict[str, Trace] = {}
        self._anomaly_history: list[AnomalyEvent] = []
        self._metrics_history: list[dict] = []
        self._alerts: list[AnomalyEvent] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

        # Metrics aggregation
        self._total_steps = 0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._error_count = 0
        self._start_time = datetime.now()

    def start(self):
        """Start the monitoring background thread."""
        if self._running:
            return self

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Stop the monitoring background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _monitor_loop(self):
        """Background monitoring loop."""
        while self._running:
            try:
                self._collect_metrics()
                time.sleep(self.config.refresh_interval)
            except Exception:
                pass  # Never crash the monitor

    def _collect_metrics(self):
        """Collect current metrics from all active traces."""
        with self._lock:
            metrics = {
                "timestamp": datetime.now().isoformat(),
                "active_traces": len(self._active_traces),
                "total_steps": self._total_steps,
                "total_tokens": self._total_tokens,
                "total_cost": self._total_cost,
                "error_count": self._error_count,
                "anomaly_count": len(self._anomaly_history),
                "alert_count": len(self._alerts),
                "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            }
            self._metrics_history.append(metrics)

            # Trim history
            if len(self._metrics_history) > self.config.max_history:
                self._metrics_history = self._metrics_history[
                    -self.config.max_history :
                ]

    def _on_anomaly(self, anomaly: AnomalyEvent):
        """Handle detected anomaly."""
        with self._lock:
            self._anomaly_history.append(anomaly)

            # Trim history
            if len(self._anomaly_history) > self.config.max_history:
                self._anomaly_history = self._anomaly_history[
                    -self.config.max_history :
                ]

            # Generate alert if severity exceeds threshold
            if (
                self.config.enable_alerts
                and anomaly.severity >= self.config.anomaly_threshold
            ):
                self._alerts.append(anomaly)

                if self.config.alert_callback:
                    try:
                        self.config.alert_callback(anomaly)
                    except Exception:
                        pass

                # Log to file if configured
                if self.config.log_file:
                    try:
                        with open(self.config.log_file, "a") as f:
                            f.write(json.dumps(anomaly.to_dict()) + "\n")
                    except Exception:
                        pass

    def attach_trace(self, trace: Trace):
        """Attach a trace for monitoring."""
        with self._lock:
            self._active_traces[trace.id] = trace

    def detach_trace(self, trace_id: str):
        """Detach a trace from monitoring."""
        with self._lock:
            self._active_traces.pop(trace_id, None)

    def process_step(
        self, step: Step, trace_id: str, step_index: int
    ) -> list[AnomalyEvent]:
        """Process a step through the anomaly detector."""
        with self._lock:
            self._total_steps += 1

            # Extract token and cost info
            self._total_tokens += step.token_count.get("total_tokens", 0)
            self._total_cost += step.cost_usd or 0.0

            if step.type == StepType.error:
                self._error_count += 1

        # Call detector outside self._lock to prevent deadlock if
        # detector callbacks re-enter LiveMonitor methods.
        anomalies = self.detector.process_step(step, trace_id, step_index)
        return anomalies

    def get_dashboard_data(self) -> dict:
        """Get current dashboard data for visualization."""
        with self._lock:
            return {
                "status": {
                    "running": self._running,
                    "uptime_seconds": (
                        datetime.now() - self._start_time
                    ).total_seconds(),
                    "active_traces": len(self._active_traces),
                },
                "metrics": {
                    "total_steps": self._total_steps,
                    "total_tokens": self._total_tokens,
                    "total_cost": self._total_cost,
                    "error_count": self._error_count,
                    "errors_per_step": self._error_count / max(1, self._total_steps),
                },
                "anomalies": {
                    "total": len(self._anomaly_history),
                    "by_type": self._count_by_type(self._anomaly_history),
                    "recent": [a.to_dict() for a in self._anomaly_history[-10:]],
                },
                "alerts": {
                    "total": len(self._alerts),
                    "unresolved": len(
                        [
                            a
                            for a in self._alerts
                            if a.severity >= self.config.anomaly_threshold
                        ]
                    ),
                    "recent": [a.to_dict() for a in self._alerts[-5:]],
                },
                "traces": list(self._active_traces.keys()),
            }

    def _count_by_type(self, anomalies: list[AnomalyEvent]) -> dict[str, int]:
        """Count anomalies by type."""
        counts: dict[str, int] = {}
        for a in anomalies:
            key = a.anomaly_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_summary_report(self) -> str:
        """Generate a text summary report."""
        with self._lock:
            uptime = (datetime.now() - self._start_time).total_seconds()
            lines = [
                "=" * 60,
                "TARDIS LIVE MONITOR SUMMARY",
                "=" * 60,
                f"Uptime: {uptime:.0f}s",
                f"Active Traces: {len(self._active_traces)}",
                f"Total Steps: {self._total_steps}",
                f"Total Tokens: {self._total_tokens:,}",
                f"Total Cost: ${self._total_cost:.4f}",
                f"Error Count: {self._error_count}",
                f"Error Rate: {self._error_count / max(1, self._total_steps) * 100:.2f}%",
                "",
                "ANOMALIES:",
                f"  Total Detected: {len(self._anomaly_history)}",
            ]

            by_type = self._count_by_type(self._anomaly_history)
            for atype, count in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"  - {atype}: {count}")

            lines.extend(
                [
                    "",
                    "ALERTS:",
                    f"  Total Alerts: {len(self._alerts)}",
                ]
            )

            if self._alerts:
                lines.append("  Recent:")
                for alert in self._alerts[-3:]:
                    lines.append(f"    [{alert.severity:.1f}] {alert.description[:50]}")

            lines.append("=" * 60)
            return "\n".join(lines)

    def reset(self):
        """Reset all monitoring state."""
        with self._lock:
            self._active_traces.clear()
            self._anomaly_history.clear()
            self._metrics_history.clear()
            self._alerts.clear()
            self._total_steps = 0
            self._total_tokens = 0
            self._total_cost = 0.0
            self._error_count = 0
            self._start_time = datetime.now()
            self.detector.reset()
