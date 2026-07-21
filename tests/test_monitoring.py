"""Tests for the monitoring subsystem (anomaly_detector, live_monitor, dashboard)."""

import pytest

from tardis.models import Step, StepType
from tardis.monitoring.anomaly_detector import (
    AnomalyDetector,
    AnomalyEvent,
    AnomalyType,
)
from tardis.monitoring.dashboard import DashboardServer
from tardis.monitoring.live_monitor import LiveMonitor, MonitorConfig

# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------


def _make_step(
    step_type=StepType.llm_call,
    token_count=100,
    duration_ms=50,
    cost_usd=0.001,
    hash_val="h1",
    success=True,
    output=None,
):
    return Step(
        trace_id="mon_test",
        index=0,
        type=step_type,
        token_count={"total_tokens": token_count},
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        hash=hash_val,
        success=success,
        output=output or {},
    )


class TestAnomalyDetector:
    def test_init(self):
        det = AnomalyDetector(window_size=10, z_threshold=2.0)
        assert det.window_size == 10
        assert det.z_threshold == 2.0

    def test_process_normal_step(self):
        det = AnomalyDetector()
        step = _make_step()
        anomalies = det.process_step(step, "t1", 0)
        assert isinstance(anomalies, list)

    def test_process_error_step(self):
        det = AnomalyDetector()
        for i in range(5):
            step = _make_step(step_type=StepType.error, success=False)
            anomalies = det.process_step(step, "t1", i)
        # After 3+ consecutive errors, should detect ERROR_RATE_SURGE
        types = [a.anomaly_type for a in anomalies]
        assert AnomalyType.ERROR_RATE_SURGE in types

    def test_loop_detection(self):
        det = AnomalyDetector()
        # Same hash repeated
        for i in range(3):
            step = _make_step(hash_val="same_hash")
            anomalies = det.process_step(step, "t1", i)
        types = [a.anomaly_type for a in anomalies]
        assert AnomalyType.LOOP_DETECTED in types

    def test_callback_registered(self):
        det = AnomalyDetector()
        captured = []
        det.register_callback(lambda a: captured.append(a))
        # Trigger a loop detection
        for i in range(3):
            step = _make_step(hash_val="loop")
            det.process_step(step, "t1", i)
        assert len(captured) > 0

    def test_callback_exception_swallows(self):
        det = AnomalyDetector()
        det.register_callback(lambda a: 1 / 0)
        for i in range(3):
            step = _make_step(hash_val="loop")
            det.process_step(step, "t1", i)

    def test_reset(self):
        det = AnomalyDetector()
        step = _make_step()
        det.process_step(step, "t1", 0)
        det.reset()
        summary = det.get_summary()
        assert summary["total_tokens"] == 0

    def test_get_summary(self):
        det = AnomalyDetector()
        summary = det.get_summary()
        assert "token_stats" in summary
        assert "context_utilization" in summary

    def test_tool_failure_cluster(self):
        det = AnomalyDetector()
        for i in range(5):
            step = _make_step(
                step_type=StepType.tool_call,
                output={"success": False, "error": "fail"},
            )
            anomalies = det.process_step(step, "t1", i)
        types = [a.anomaly_type for a in anomalies]
        assert AnomalyType.TOOL_FAILURE_CLUSTER in types

    def test_token_spike_detection(self):
        det = AnomalyDetector(z_threshold=1.0)
        # Build baseline with small tokens
        for i in range(6):
            step = _make_step(token_count=100)
            det.process_step(step, "t1", i)
        # Now a large spike
        spike = _make_step(token_count=10000)
        anomalies = det.process_step(spike, "t1", 6)
        types = [a.anomaly_type for a in anomalies]
        assert AnomalyType.TOKEN_SPIKE in types


class TestAnomalyEvent:
    def test_to_dict(self):
        event = AnomalyEvent(
            anomaly_type=AnomalyType.TOKEN_SPIKE,
            severity=0.8,
            description="test spike",
            step_index=5,
            trace_id="t1",
            evidence={"tokens": 1000},
            suggested_action="review",
        )
        d = event.to_dict()
        assert d["type"] == "token_spike"
        assert d["severity"] == 0.8
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# LiveMonitor
# ---------------------------------------------------------------------------


class TestLiveMonitor:
    def test_init(self):
        monitor = LiveMonitor()
        assert not monitor._running

    def test_custom_config(self):
        config = MonitorConfig(refresh_interval=0.5, anomaly_threshold=0.9)
        monitor = LiveMonitor(config=config)
        assert monitor.config.anomaly_threshold == 0.9

    def test_start_stop(self):
        monitor = LiveMonitor()
        monitor.start()
        assert monitor._running
        monitor.stop()
        assert not monitor._running

    def test_start_idempotent(self):
        monitor = LiveMonitor()
        monitor.start()
        monitor.start()  # Should not raise
        monitor.stop()

    def test_attach_detach_trace(self):
        from tardis.models import Trace

        monitor = LiveMonitor()
        trace = Trace(id="test_trace")
        monitor.attach_trace(trace)
        assert "test_trace" in monitor._active_traces
        monitor.detach_trace("test_trace")
        assert "test_trace" not in monitor._active_traces

    def test_process_step(self):
        monitor = LiveMonitor()
        step = _make_step()
        anomalies = monitor.process_step(step, "t1", 0)
        assert isinstance(anomalies, list)
        assert monitor._total_steps == 1

    def test_process_error_step(self):
        monitor = LiveMonitor()
        step = _make_step(step_type=StepType.error, success=False)
        monitor.process_step(step, "t1", 0)
        assert monitor._error_count == 1

    def test_get_dashboard_data(self):
        monitor = LiveMonitor()
        data = monitor.get_dashboard_data()
        assert "status" in data
        assert "metrics" in data
        assert "anomalies" in data

    def test_get_summary_report(self):
        monitor = LiveMonitor()
        report = monitor.get_summary_report()
        assert "TARDIS LIVE MONITOR SUMMARY" in report

    def test_reset(self):
        monitor = LiveMonitor()
        step = _make_step()
        monitor.process_step(step, "t1", 0)
        monitor.reset()
        assert monitor._total_steps == 0

    def test_alert_callback(self):
        alerts = []
        config = MonitorConfig(
            enable_alerts=True,
            anomaly_threshold=0.0,
            alert_callback=lambda a: alerts.append(a),
        )
        monitor = LiveMonitor(config=config)
        # Force an anomaly
        event = AnomalyEvent(
            anomaly_type=AnomalyType.TOKEN_SPIKE,
            severity=1.0,
            description="test",
            step_index=0,
            trace_id="t1",
        )
        monitor._on_anomaly(event)
        assert len(alerts) == 1

    def test_log_file(self, tmp_path):
        log_file = str(tmp_path / "alerts.jsonl")
        config = MonitorConfig(
            enable_alerts=True,
            anomaly_threshold=0.0,
            log_file=log_file,
        )
        monitor = LiveMonitor(config=config)
        event = AnomalyEvent(
            anomaly_type=AnomalyType.ERROR_RATE_SURGE,
            severity=1.0,
            description="test error",
            step_index=0,
            trace_id="t1",
        )
        monitor._on_anomaly(event)
        import json

        with open(log_file) as f:
            data = json.loads(f.readline())
        assert data["type"] == "error_rate_surge"


# ---------------------------------------------------------------------------
# DashboardServer
# ---------------------------------------------------------------------------


class TestDashboardServer:
    def test_init(self):
        server = DashboardServer(port=0)
        assert server.port == 0

    def test_get_status_data_no_monitor(self):
        server = DashboardServer()
        data = server.get_status_data()
        assert data["metrics"]["total_steps"] == 0

    def test_get_status_data_with_monitor(self):
        monitor = LiveMonitor()
        server = DashboardServer(monitor=monitor)
        data = server.get_status_data()
        assert "metrics" in data

    def test_url_property(self):
        server = DashboardServer(host="127.0.0.1", port=8080)
        assert server.url == "http://127.0.0.1:8080"

    def test_non_loopback_warning(self):
        with pytest.warns(UserWarning, match="non-loopback"):
            DashboardServer(host="0.0.0.0", port=9090)
