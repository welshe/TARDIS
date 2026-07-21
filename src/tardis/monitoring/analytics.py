from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_MODEL_USAGE_KEYS = 100
_MAX_MODEL_NAME_LEN = 128


def _validate_timestamp(value: float) -> float:
    v = float(value)
    if v <= 0:
        raise ValueError(f"Timestamp must be a positive float, got {v}")
    return v


def _validate_period(value: int, name: str = "period") -> int:
    v = int(value)
    if v < 0:
        raise ValueError(f"{name} must be non-negative, got {v}")
    return v


def _sanitize_model_usage(raw: dict[str, Any]) -> dict[str, int]:
    """Cap model_usage dict to prevent memory exhaustion from untrusted collector data."""
    result: dict[str, int] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k:
            continue
        # Truncate overly long model names
        key = k[:_MAX_MODEL_NAME_LEN]
        if len(result) >= _MAX_MODEL_USAGE_KEYS and key not in result:
            continue
        try:
            result[key] = result.get(key, 0) + int(v)
        except (ValueError, TypeError):
            continue
    return result


@dataclass
class MetricSnapshot:
    timestamp: float
    total_steps: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error_count: int = 0
    error_rate: float = 0.0
    active_traces: int = 0
    anomaly_count: int = 0
    avg_latency_ms: float = 0.0
    model_usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_steps": self.total_steps,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "active_traces": self.active_traces,
            "anomaly_count": self.anomaly_count,
            "avg_latency_ms": self.avg_latency_ms,
            "model_usage": dict(self.model_usage),
        }


class MetricHistory:
    def __init__(self, max_snapshots: int = 3600):
        if not isinstance(max_snapshots, int) or max_snapshots < 1:
            raise ValueError(f"max_snapshots must be a positive integer, got {max_snapshots!r}")
        if max_snapshots > 1_000_000:
            raise ValueError(f"max_snapshots too large ({max_snapshots}), max is 1_000_000")
        self._max_snapshots = max_snapshots
        self._snapshots: deque = deque()
        self._lock: threading.RLock = threading.RLock()

    def record(self, snapshot: MetricSnapshot) -> None:
        if not isinstance(snapshot, MetricSnapshot):
            raise TypeError(f"Expected MetricSnapshot, got {type(snapshot)}")
        _validate_timestamp(snapshot.timestamp)
        with self._lock:
            self._snapshots.append(snapshot)
            while len(self._snapshots) > self._max_snapshots:
                self._snapshots.popleft()

    def get_range(self, start_time: float, end_time: float) -> list[MetricSnapshot]:
        if start_time > end_time:
            return []
        with self._lock:
            return [s for s in self._snapshots if start_time <= s.timestamp <= end_time]

    def get_latest(self) -> MetricSnapshot | None:
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_summary(self, period_seconds: int = 300) -> dict[str, Any]:
        period_seconds = _validate_period(period_seconds, "period_seconds")
        cutoff = datetime.now().timestamp() - period_seconds
        period_data: list[MetricSnapshot] = []
        with self._lock:
            for s in reversed(self._snapshots):
                if s.timestamp >= cutoff:
                    period_data.append(s)
                else:
                    break
        if not period_data:
            return {}

        def _agg(values):
            return min(values), max(values), sum(values) / len(values)

        steps_vals = [s.total_steps for s in period_data]
        tokens_vals = [s.total_tokens for s in period_data]
        cost_vals = [s.total_cost_usd for s in period_data]
        err_rate_vals = [s.error_rate for s in period_data]
        err_count_vals = [s.error_count for s in period_data]
        lat_vals = [s.avg_latency_ms for s in period_data]
        active_vals = [s.active_traces for s in period_data]
        anomaly_vals = [s.anomaly_count for s in period_data]

        model_usage: dict[str, int] = {}
        for s in period_data:
            for model_name, tokens in s.model_usage.items():
                model_usage[model_name] = model_usage.get(model_name, 0) + tokens
        top_models = sorted(model_usage, key=model_usage.get, reverse=True)[:5]

        return {
            "period_seconds": period_seconds,
            "num_snapshots": len(period_data),
            "steps": {"min": min(steps_vals), "max": max(steps_vals), "avg": sum(steps_vals) / len(steps_vals)},
            "tokens": _agg(tokens_vals),
            "cost_usd": _agg(cost_vals),
            "error_rate": {"min": min(err_rate_vals), "max": max(err_rate_vals), "avg": sum(err_rate_vals) / len(err_rate_vals)},
            "error_count": {"min": min(err_count_vals), "max": max(err_count_vals), "avg": sum(err_count_vals) / len(err_count_vals)},
            "avg_latency_ms": _agg(lat_vals),
            "active_traces": _agg(active_vals),
            "anomaly_count": {"min": min(anomaly_vals), "max": max(anomaly_vals), "avg": sum(anomaly_vals) / len(anomaly_vals)},
            "top_models": top_models,
            "total_anomalies_in_period": sum(anomaly_vals),
        }

    def get_trend(self, metric_name: str, period_seconds: int = 3600) -> dict[str, Any]:
        period_seconds = _validate_period(period_seconds, "period_seconds")
        cutoff = datetime.now().timestamp() - period_seconds
        x: list[float] = []
        y: list[float] = []
        seen: int = 0
        with self._lock:
            for s in self._snapshots:
                if s.timestamp >= cutoff:
                    x.append(float(seen))
                    seen += 1
                    y.append(s._get_metric_value(metric_name))
        if not y:
            return {"direction": "stable", "slope": 0.0, "r_squared": 0.0, "datapoints": 0}
        return _linear_regression(x, y)

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._snapshots)


class TrendAnalyzer:
    @staticmethod
    def linear_regression(x: list[float], y: list[float]) -> dict[str, Any]:
        return _linear_regression(x, y)

    @staticmethod
    def moving_average(values: list[float], window: int) -> list[float]:
        if window < 1:
            raise ValueError(f"window must be >= 1, got {window}")
        if len(values) <= window:
            return values[:]
        result: list[float] = []
        half = window // 2
        for i in range(len(values)):
            start = max(0, i - half)
            end = min(len(values), i + half + 1)
            if end - start < 2:
                result.append(values[i])
            else:
                subset = values[start:end]
                result.append(sum(subset) / len(subset))
        return result

    @staticmethod
    def detect_anomalies_zscore(values: list[float], threshold: float = 3.0) -> list[int]:
        if len(values) < 3:
            return []
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        std = math.sqrt(variance) if variance > 0 else 1e-10
        return [i for i, val in enumerate(values) if abs(val - mean) / std > threshold]

    @staticmethod
    def forecast_next(values: list[float], periods: int = 5) -> list[float]:
        if len(values) < 2 or periods < 1:
            return []
        x = list(range(len(values)))
        model = _linear_regression(x, values)
        slope = model["slope"]
        intercept = model["intercept"]
        last_idx = len(values) - 1
        return [intercept + slope * (last_idx + i + 1) for i in range(periods)]


def _linear_regression(x: list[float], y: list[float]) -> dict[str, Any]:
    n = len(x)
    if n != len(y):
        raise ValueError(f"x and y must have the same length, got {n} vs {len(y)}")
    if n == 0:
        return {"direction": "stable", "slope": 0.0, "intercept": 0.0, "r_squared": 0.0, "datapoints": 0}
    if n == 1:
        return {"direction": "stable", "slope": 0.0, "intercept": y[0], "r_squared": 1.0, "datapoints": 1}

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(a * b for a, b in zip(x, y))
    sum_xx = sum(a * a for a in x)

    denom = n * sum_xx - sum_x * sum_x
    if abs(denom) < 1e-15:
        return {"direction": "stable", "slope": 0.0, "intercept": sum_y / n, "r_squared": 0.0, "datapoints": n}

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    sy = sum_y / n
    ss_tot = sum((yi - sy) ** 2 for yi in y)
    ss_res = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, y))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    direction = "stable"
    thresh = abs(slope) * 0.01 + 1e-10
    if slope > thresh:
        direction = "increasing"
    elif slope < -thresh:
        direction = "decreasing"

    return {
        "direction": direction,
        "slope": slope,
        "intercept": intercept,
        "r_squared": max(0.0, min(1.0, r_squared)),
        "datapoints": n,
    }


_metric_registry: dict[str, Callable] = {
    "total_steps": lambda s: s.total_steps,
    "total_tokens": lambda s: s.total_tokens,
    "total_cost_usd": lambda s: s.total_cost_usd,
    "error_count": lambda s: s.error_count,
    "error_rate": lambda s: s.error_rate,
    "active_traces": lambda s: s.active_traces,
    "anomaly_count": lambda s: s.anomaly_count,
    "avg_latency_ms": lambda s: s.avg_latency_ms,
}


def _metric_value_getter(self: MetricSnapshot, name: str) -> float:
    fn = _metric_registry.get(name or "")
    if fn is None:
        raise ValueError(f"Unknown metric name '{name}'. Valid options: {list(_metric_registry)}")
    return float(fn(self))


MetricSnapshot._get_metric_value = _metric_value_getter


class AnalyticsCollector:
    def __init__(self, interval: float = 1.0):
        self.history = MetricHistory()
        self._collectors: list[Callable[[], dict[str, Any]]] = []
        self._interval: float = interval
        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._lock: threading.RLock = threading.RLock()
        self._anomaly_list: list[dict[str, Any]] = []
        self._anomaly_list_max: int = 100

    def start(self) -> AnalyticsCollector:
        with self._lock:
            if self._running:
                return self
            self._running = True
            self._thread = threading.Thread(target=self._collection_loop, daemon=True, name="analytics-collector")
            self._thread.start()
        return self

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _collection_loop(self) -> None:
        while self._running:
            try:
                snap = self.snapshot()
                if snap.timestamp > 0:
                    self.history.record(snap)
            except Exception:
                logger.exception("Analytics collection failed")
            try:
                import time as _time
                _time.sleep(self._interval)
            except Exception:
                pass

    def register_collector(self, fn: Callable[[], dict[str, Any]]) -> None:
        with self._lock:
            self._collectors.append(fn)

    def record_anomaly(self, anomaly_dict: dict[str, Any]) -> None:
        with self._lock:
            self._anomaly_list.append(anomaly_dict)
            if len(self._anomaly_list) > self._anomaly_list_max:
                self._anomaly_list = self._anomaly_list[-self._anomaly_list_max:]

    def snapshot(self) -> MetricSnapshot:
        merged: dict[str, Any] = {}
        for collector_fn in self._collectors:
            try:
                data = collector_fn()
                if isinstance(data, dict):
                    merged.update(data)
            except Exception:
                logger.exception("Analytics collector callback failed")
        now = datetime.now().timestamp()
        model_usage_raw = merged.get("model_usage", {})
        if not isinstance(model_usage_raw, dict):
            model_usage_raw = {}
        err_cnt = int(merged.get("error_count", 0))
        total_steps = int(merged.get("total_steps", 1))
        return MetricSnapshot(
            timestamp=_validate_timestamp(now),
            total_steps=int(merged.get("total_steps", 0)),
            total_tokens=int(merged.get("total_tokens", 0)),
            total_cost_usd=float(merged.get("total_cost_usd", merged.get("total_cost", 0.0))),
            error_count=err_cnt,
            error_rate=float(merged.get("error_rate", err_cnt / (total_steps if total_steps > 0 else 1))),
            active_traces=int(merged.get("active_traces", 0)),
            anomaly_count=int(merged.get("anomaly_count", 0)),
            avg_latency_ms=float(merged.get("avg_latency_ms", 0.0)),
            model_usage=_sanitize_model_usage(model_usage_raw),
        )

    def get_history(self) -> MetricHistory:
        return self.history

    def get_dashboard_analytics(self) -> dict[str, Any]:
        now = datetime.now().timestamp()
        anomaly_events: list[dict[str, Any]] = []
        with self._lock:
            if self._anomaly_list:
                anomaly_events = self._anomaly_list[-10:]
        latest = self.history.get_latest()
        trends: dict[str, Any] = {}
        for metric_name in ["total_cost_usd", "total_tokens", "error_count", "avg_latency_ms"]:
            try:
                trends[metric_name] = self.history.get_trend(metric_name)
            except Exception:
                logger.exception("Failed to compute trend for %s", metric_name)
                trends[metric_name] = {"direction": "stable", "slope": 0.0, "r_squared": 0.0, "datapoints": 0}
        # Use public API instead of reaching into history internals
        model_usage_breakdown: dict[str, int] = {}
        one_hour_ago = now - 3600
        recent_snapshots = self.history.get_range(one_hour_ago, now)
        for s in recent_snapshots:
            for model_name, model_tokens in s.model_usage.items():
                if model_name and isinstance(model_tokens, (int, float)):
                    if len(model_usage_breakdown) >= _MAX_MODEL_USAGE_KEYS and model_name not in model_usage_breakdown:
                        continue
                    model_usage_breakdown[model_name] = model_usage_breakdown.get(model_name, 0) + int(model_tokens)
        pie_data = [{"name": name, "tokens": count} for name, count in sorted(model_usage_breakdown.items(), key=lambda x: x[1], reverse=True)]
        hourly_summary = self.history.get_summary(period_seconds=3600)
        return {
            "latest": latest.to_dict() if latest else {},
            "trends": trends,
            "recent_anomalies": anomaly_events,
            "model_usage_breakdown": pie_data,
            "hourly_summary": hourly_summary,
            "total_snapshots": self.history.count(),
        }

    def get_dashboard_data(self) -> dict[str, Any]:
        return self.get_dashboard_analytics()


__all__ = [
    "MetricSnapshot",
    "MetricHistory",
    "TrendAnalyzer",
    "AnalyticsCollector",
]
