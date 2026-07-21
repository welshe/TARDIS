"""Tests for Production Intelligence / Shadow Mode."""

import pytest

from tardis.production.shadow_mode import ProductionIntelligence, ShadowModeStatus


class TestProductionIntelligence:
    def test_init(self):
        pi = ProductionIntelligence()
        assert pi.mode == ShadowModeStatus.PASSIVE

    def test_set_mode(self):
        pi = ProductionIntelligence()
        pi.set_mode(ShadowModeStatus.ACTIVE)
        assert pi.mode == ShadowModeStatus.ACTIVE

    def test_record_trace_passive(self):
        pi = ProductionIntelligence()
        trace = {"id": "t1", "steps": []}
        pi.record_trace(trace)  # Should not raise
        assert len(pi._trace_hashes) == 1

    def test_record_trace_dedup(self):
        pi = ProductionIntelligence()
        trace = {"id": "t1", "steps": []}
        pi.record_trace(trace)
        pi.record_trace(trace)  # Duplicate
        assert len(pi._trace_hashes) == 1

    def test_record_trace_type_error(self):
        pi = ProductionIntelligence()
        with pytest.raises(TypeError, match="must be a dict"):
            pi.record_trace("not a dict")

    def test_record_trace_active(self):
        pi = ProductionIntelligence()
        pi.set_mode(ShadowModeStatus.ACTIVE)
        trace = {"id": "t1", "steps": [{"type": "llm_call", "hash": "a"}]}
        pi.record_trace(trace)
        assert len(pi._trace_hashes) == 1

    def test_record_trace_blocking_normal(self):
        pi = ProductionIntelligence()
        pi.set_mode(ShadowModeStatus.BLOCKING)
        trace = {"id": "t1", "steps": []}
        pi.record_trace(trace)  # No anomaly, should pass

    def test_record_trace_blocking_anomaly(self):
        pi = ProductionIntelligence()
        pi.set_mode(ShadowModeStatus.BLOCKING)
        trace = {"id": "t1", "failure_type": "crash", "steps": []}
        with pytest.raises(RuntimeError, match="anomaly detected"):
            pi.record_trace(trace)

    def test_analyze_no_anomaly(self):
        pi = ProductionIntelligence()
        result = pi._analyze({"id": "t1", "steps": []})
        assert not result["anomalous"]

    def test_analyze_failure_type(self):
        pi = ProductionIntelligence()
        result = pi._analyze({"failure_type": "timeout"})
        assert result["anomalous"]
        assert result["anomalies"][0]["type"] == "failure_detected"

    def test_analyze_slow_execution(self):
        pi = ProductionIntelligence()
        result = pi._analyze({"duration_ms": 600000})
        assert result["anomalous"]
        assert result["anomalies"][0]["type"] == "slow_execution"

    def test_analyze_loop_suspected(self):
        pi = ProductionIntelligence()
        hashes = [{"hash": "same"} for _ in range(10)]
        result = pi._analyze({"steps": hashes})
        assert result["anomalous"]
        types = [a["type"] for a in result["anomalies"]]
        assert "loop_suspected" in types

    def test_generate_regression_suite_no_store(self):
        pi = ProductionIntelligence()
        assert pi.generate_regression_suite() == []

    def test_generate_regression_suite_with_store(self):
        class FakeStore:
            def list_traces(self):
                return [
                    {
                        "id": "t1",
                        "success": False,
                        "failure_type": "timeout",
                        "steps": [{"type": "error"}, {"type": "llm_call"}],
                    },
                    {"id": "t2", "success": True, "steps": []},
                ]

        pi = ProductionIntelligence(store=FakeStore())
        tests = pi.generate_regression_suite()
        assert len(tests) == 1
        assert tests[0]["failure_type"] == "timeout"

    def test_statistics(self):
        pi = ProductionIntelligence()
        stats = pi.get_statistics()
        assert stats["mode"] == "passive"
        assert stats["traces_recorded"] == 0

    def test_is_anomalous(self):
        pi = ProductionIntelligence()
        assert not pi._is_anomalous({"steps": []})
        assert pi._is_anomalous({"failure_type": "crash"})
