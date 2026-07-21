"""Tests for the dashboard analytics module."""

import time

import pytest

from tardis.monitoring.analytics import (
    AnalyticsCollector,
    MetricHistory,
    MetricSnapshot,
    TrendAnalyzer,
)

# ---------------------------------------------------------------------------
# MetricSnapshot
# ---------------------------------------------------------------------------


class TestMetricSnapshot:
    def test_creation_defaults(self):
        snap = MetricSnapshot(timestamp=1.0)
        assert snap.timestamp == 1.0
        assert snap.total_steps == 0
        assert snap.total_tokens == 0
        assert snap.total_cost_usd == 0.0
        assert snap.error_count == 0
        assert snap.error_rate == 0.0
        assert snap.active_traces == 0
        assert snap.anomaly_count == 0
        assert snap.avg_latency_ms == 0.0
        assert snap.model_usage == {}

    def test_creation_custom_fields(self):
        snap = MetricSnapshot(
            timestamp=100.0,
            total_steps=50,
            total_tokens=10000,
            total_cost_usd=0.42,
            error_count=3,
            error_rate=0.06,
            active_traces=2,
            anomaly_count=1,
            avg_latency_ms=123.5,
            model_usage={"gpt-4": 7000, "gpt-3.5": 3000},
        )
        assert snap.total_steps == 50
        assert snap.model_usage["gpt-4"] == 7000
        assert snap.model_usage["gpt-3.5"] == 3000

    def test_to_dict_serialization(self):
        snap = MetricSnapshot(
            timestamp=50.0,
            total_steps=10,
            model_usage={"model_a": 100},
        )
        d = snap.to_dict()
        assert d["timestamp"] == 50.0
        assert d["total_steps"] == 10
        assert d["model_usage"] == {"model_a": 100}
        assert len(d) == 10

    def test_to_dict_model_usage_is_copy(self):
        snap = MetricSnapshot(timestamp=1.0, model_usage={"m": 1})
        d = snap.to_dict()
        d["model_usage"]["m"] = 999
        assert snap.model_usage["m"] == 1

    def test_invalid_timestamp_negative_rejected_by_history(self):
        h = MetricHistory()
        with pytest.raises(ValueError, match="positive float"):
            h.record(MetricSnapshot(timestamp=-1.0))

    def test_invalid_timestamp_zero_rejected_by_history(self):
        h = MetricHistory()
        with pytest.raises(ValueError, match="positive float"):
            h.record(MetricSnapshot(timestamp=0.0))


# ---------------------------------------------------------------------------
# MetricHistory
# ---------------------------------------------------------------------------


class TestMetricHistory:
    def test_record_and_get_latest(self):
        h = MetricHistory()
        s1 = MetricSnapshot(timestamp=10.0)
        s2 = MetricSnapshot(timestamp=20.0)
        h.record(s1)
        h.record(s2)
        assert h.get_latest() is s2

    def test_get_latest_empty(self):
        h = MetricHistory()
        assert h.get_latest() is None

    def test_get_range(self):
        h = MetricHistory()
        s1 = MetricSnapshot(timestamp=10.0)
        s2 = MetricSnapshot(timestamp=20.0)
        s3 = MetricSnapshot(timestamp=30.0)
        h.record(s1)
        h.record(s2)
        h.record(s3)
        result = h.get_range(10.0, 25.0)
        assert len(result) == 2
        assert result[0].timestamp == 10.0
        assert result[1].timestamp == 20.0

    def test_get_range_inverted(self):
        h = MetricHistory()
        h.record(MetricSnapshot(timestamp=10.0))
        assert h.get_range(20.0, 10.0) == []

    def test_get_range_no_match(self):
        h = MetricHistory()
        h.record(MetricSnapshot(timestamp=5.0))
        assert h.get_range(10.0, 20.0) == []

    def test_clear(self):
        h = MetricHistory()
        h.record(MetricSnapshot(timestamp=1.0))
        h.record(MetricSnapshot(timestamp=2.0))
        h.clear()
        assert h.count() == 0
        assert h.get_latest() is None

    def test_count(self):
        h = MetricHistory()
        assert h.count() == 0
        h.record(MetricSnapshot(timestamp=1.0))
        assert h.count() == 1
        h.record(MetricSnapshot(timestamp=2.0))
        assert h.count() == 2

    def test_max_snapshots_pruning(self):
        h = MetricHistory(max_snapshots=3)
        for i in range(1, 6):
            h.record(MetricSnapshot(timestamp=float(i)))
        assert h.count() == 3
        assert h.get_latest().timestamp == 5.0
        oldest = h.get_range(0.0, 100.0)
        assert oldest[0].timestamp == 3.0

    def test_record_rejects_non_snapshot(self):
        h = MetricHistory()
        with pytest.raises(TypeError, match="Expected MetricSnapshot"):
            h.record("not a snapshot")

    def test_get_summary_with_recent_data(self):
        h = MetricHistory()
        now = time.time()
        for i in range(5):
            h.record(MetricSnapshot(
                timestamp=now + i,
                total_steps=10 * (i + 1),
                total_tokens=100 * (i + 1),
                total_cost_usd=0.01 * (i + 1),
                error_rate=0.001 * (i + 1),
                error_count=i,
                avg_latency_ms=50.0 + i,
                active_traces=i,
                anomaly_count=i,
                model_usage={"gpt-4": 100 * (i + 1)},
            ))
        summary = h.get_summary(period_seconds=300)
        assert summary["num_snapshots"] == 5
        assert summary["total_anomalies_in_period"] == 10
        assert summary["steps"]["min"] == 10
        assert summary["steps"]["max"] == 50
        assert summary["steps"]["avg"] == 30.0
        assert "gpt-4" in summary["top_models"]

    def test_get_summary_empty(self):
        h = MetricHistory()
        assert h.get_summary() == {}

    def test_get_trend_increasing(self):
        h = MetricHistory()
        now = time.time()
        for i in range(10):
            h.record(MetricSnapshot(timestamp=now + i, total_steps=i * 10))
        trend = h.get_trend("total_steps", period_seconds=300)
        assert trend["direction"] == "increasing"
        assert trend["slope"] > 0

    def test_get_trend_decreasing(self):
        h = MetricHistory()
        now = time.time()
        for i in range(10):
            h.record(MetricSnapshot(timestamp=now + i, total_steps=(10 - i) * 10))
        trend = h.get_trend("total_steps", period_seconds=300)
        assert trend["direction"] == "decreasing"
        assert trend["slope"] < 0

    def test_get_trend_stable(self):
        h = MetricHistory()
        now = time.time()
        for i in range(10):
            h.record(MetricSnapshot(timestamp=now + i, total_steps=100))
        trend = h.get_trend("total_steps", period_seconds=300)
        assert trend["direction"] == "stable"
        assert trend["slope"] == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# TrendAnalyzer
# ---------------------------------------------------------------------------


class TestTrendAnalyzer:
    def test_linear_regression_positive_slope(self):
        result = TrendAnalyzer.linear_regression(
            [0.0, 1.0, 2.0, 3.0, 4.0],
            [0.0, 2.0, 4.0, 6.0, 8.0],
        )
        assert result["direction"] == "increasing"
        assert result["slope"] == pytest.approx(2.0)
        assert result["r_squared"] == pytest.approx(1.0)

    def test_linear_regression_negative_slope(self):
        result = TrendAnalyzer.linear_regression(
            [0.0, 1.0, 2.0, 3.0],
            [0.0, -1.0, -2.0, -3.0],
        )
        assert result["direction"] == "decreasing"
        assert result["slope"] == pytest.approx(-1.0)

    def test_linear_regression_stable(self):
        result = TrendAnalyzer.linear_regression(
            [0.0, 1.0, 2.0, 3.0],
            [5.0, 5.0, 5.0, 5.0],
        )
        assert result["direction"] == "stable"
        assert result["slope"] == pytest.approx(0.0, abs=1e-10)

    def test_linear_regression_empty(self):
        result = TrendAnalyzer.linear_regression([], [])
        assert result["direction"] == "stable"
        assert result["slope"] == 0.0
        assert result["datapoints"] == 0

    def test_linear_regression_single_point(self):
        result = TrendAnalyzer.linear_regression([1.0], [7.0])
        assert result["direction"] == "stable"
        assert result["intercept"] == 7.0
        assert result["r_squared"] == 1.0
        assert result["datapoints"] == 1

    def test_linear_regression_mismatched_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            TrendAnalyzer.linear_regression([1.0, 2.0], [1.0])

    def test_moving_average_window3(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = TrendAnalyzer.moving_average(values, window=3)
        assert len(result) == 5
        assert result[1] == pytest.approx(2.0)
        assert result[2] == pytest.approx(3.0)
        assert result[3] == pytest.approx(4.0)

    def test_moving_average_empty(self):
        assert TrendAnalyzer.moving_average([], window=3) == []

    def test_moving_average_window_exceeds_length(self):
        values = [1.0, 2.0]
        result = TrendAnalyzer.moving_average(values, window=5)
        assert result == [1.0, 2.0]

    def test_moving_average_window1_passthrough(self):
        values = [10.0, 20.0, 30.0]
        result = TrendAnalyzer.moving_average(values, window=1)
        assert result == [10.0, 20.0, 30.0]

    def test_moving_average_invalid_window(self):
        with pytest.raises(ValueError, match="window must be >= 1"):
            TrendAnalyzer.moving_average([1.0], window=0)

    def test_detect_anomalies_clear_outlier(self):
        values = [1.0, 1.1, 1.0, 1.0, 1.2, 100.0]
        anomalies = TrendAnalyzer.detect_anomalies_zscore(values, threshold=2.0)
        assert len(anomalies) >= 1
        assert 5 in anomalies

    def test_detect_anomalies_normal_data(self):
        values = [10.0, 10.1, 9.9, 10.0, 10.05, 9.95]
        assert TrendAnalyzer.detect_anomalies_zscore(values) == []

    def test_detect_anomalies_empty(self):
        assert TrendAnalyzer.detect_anomalies_zscore([]) == []

    def test_detect_anomalies_too_few_points(self):
        assert TrendAnalyzer.detect_anomalies_zscore([1.0, 2.0]) == []

    def test_forecast_next_linear(self):
        values = [0.0, 2.0, 4.0, 6.0, 8.0]
        forecast = TrendAnalyzer.forecast_next(values, periods=3)
        assert len(forecast) == 3
        assert forecast[0] == pytest.approx(10.0)
        assert forecast[1] == pytest.approx(12.0)
        assert forecast[2] == pytest.approx(14.0)

    def test_forecast_next_insufficient_data(self):
        assert TrendAnalyzer.forecast_next([1.0]) == []
        assert TrendAnalyzer.forecast_next([], periods=3) == []

    def test_forecast_next_zero_periods(self):
        assert TrendAnalyzer.forecast_next([1.0, 2.0], periods=0) == []


# ---------------------------------------------------------------------------
# AnalyticsCollector
# ---------------------------------------------------------------------------


class TestAnalyticsCollector:
    def test_snapshot_calls_collectors(self):
        collector = AnalyticsCollector()
        collector.register_collector(lambda: {"total_steps": 42, "total_tokens": 500})
        snap = collector.snapshot()
        assert isinstance(snap, MetricSnapshot)
        assert snap.total_steps == 42
        assert snap.total_tokens == 500

    def test_snapshot_collector_exception_handled(self):
        collector = AnalyticsCollector()
        collector.register_collector(lambda: 1 / 0)
        snap = collector.snapshot()
        assert isinstance(snap, MetricSnapshot)

    def test_snapshot_merges_multiple_collectors(self):
        collector = AnalyticsCollector()
        collector.register_collector(lambda: {"total_steps": 10})
        collector.register_collector(lambda: {"total_tokens": 200})
        snap = collector.snapshot()
        assert snap.total_steps == 10
        assert snap.total_tokens == 200

    def test_start_stop_lifecycle(self):
        collector = AnalyticsCollector(interval=0.1)
        collector.start()
        assert collector._running
        assert collector._thread is not None
        collector.stop()
        assert not collector._running
        assert collector._thread is None

    def test_start_idempotent(self):
        collector = AnalyticsCollector(interval=0.1)
        collector.start()
        collector.start()
        assert collector._running
        collector.stop()

    def test_get_history(self):
        collector = AnalyticsCollector()
        h = collector.get_history()
        assert isinstance(h, MetricHistory)
        assert h is collector.history

    def test_get_dashboard_analytics_keys(self):
        collector = AnalyticsCollector()
        analytics = collector.get_dashboard_analytics()
        expected_keys = {
            "latest", "trends", "recent_anomalies",
            "model_usage_breakdown", "hourly_summary", "total_snapshots",
        }
        assert expected_keys <= set(analytics.keys())

    def test_get_dashboard_data_is_alias(self):
        collector = AnalyticsCollector()
        assert collector.get_dashboard_data() == collector.get_dashboard_analytics()

    def test_background_collection(self):
        collector = AnalyticsCollector(interval=0.05)
        collector.register_collector(lambda: {"total_steps": 1})
        collector.start()
        time.sleep(0.3)
        collector.stop()
        assert collector.history.count() >= 1

    def test_record_anomaly(self):
        collector = AnalyticsCollector()
        collector.record_anomaly({"type": "spike", "severity": 0.9})
        analytics = collector.get_dashboard_analytics()
        assert len(analytics["recent_anomalies"]) == 1

    def test_record_anomaly_bounded(self):
        collector = AnalyticsCollector()
        for i in range(150):
            collector.record_anomaly({"type": "x", "i": i})
        analytics = collector.get_dashboard_analytics()
        assert len(analytics["recent_anomalies"]) <= 10


# ---------------------------------------------------------------------------
# Security / Edge Cases
# ---------------------------------------------------------------------------


class TestSecurityAndEdgeCases:
    def test_history_bounded_by_max_snapshots(self):
        h = MetricHistory(max_snapshots=5)
        for i in range(100):
            h.record(MetricSnapshot(timestamp=float(i + 1)))
        assert h.count() == 5

    def test_collector_error_does_not_crash_snapshot(self):
        c = AnalyticsCollector()
        c.register_collector(lambda: 1 / 0)
        c.register_collector(lambda: {"total_steps": 99})
        snap = c.snapshot()
        assert snap.total_steps == 99

    def test_snapshot_non_dict_model_usage_fallback(self):
        c = AnalyticsCollector()
        c.register_collector(lambda: {"model_usage": "bad"})
        snap = c.snapshot()
        assert snap.model_usage == {}

    def test_invalid_timestamp_rejected(self):
        h = MetricHistory()
        with pytest.raises(ValueError):
            h.record(MetricSnapshot(timestamp=-1.0))

    def test_linear_regression_all_same_y(self):
        result = TrendAnalyzer.linear_regression(
            [0.0, 1.0, 2.0], [5.0, 5.0, 5.0],
        )
        assert result["slope"] == pytest.approx(0.0, abs=1e-10)
        assert result["direction"] == "stable"
        assert result["intercept"] == pytest.approx(5.0)
