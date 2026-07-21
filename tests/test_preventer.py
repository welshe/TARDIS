"""Tests for the predictive failure prevention system."""

from tardis.predictive.preventer import (
    PredictionResult,
    PredictiveFailurePrevention,
    RiskLevel,
)


class TestPredictiveFailurePrevention:
    def test_init_no_store(self):
        pp = PredictiveFailurePrevention()
        assert pp.vector_store is None

    def test_analyze_action_no_store(self):
        pp = PredictiveFailurePrevention()
        result = pp.analyze_action({"action": "click"}, {})
        assert result.risk_level == RiskLevel.LOW
        assert result.confidence == 0.0
        assert result.suggested_action == "proceed"

    def test_analyze_action_with_store_no_results(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return []

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.analyze_action({"action": "click"}, {})
        assert result.risk_level == RiskLevel.LOW
        assert result.confidence == 0.0

    def test_analyze_action_critical_risk(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return [
                    {
                        "trace_id": "t1",
                        "failure_type": "crash",
                        "description": "segfault in handler",
                        "_distance": 0.04,
                    }
                ]

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.analyze_action({"action": "trigger"}, {})
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.confidence > 0.9
        assert result.suggested_action == "block"

    def test_analyze_action_high_risk(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return [
                    {
                        "trace_id": "t2",
                        "failure_type": "timeout",
                        "description": "API timeout",
                        "_distance": 0.1,
                    }
                ]

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.analyze_action({"action": "call_api"}, {})
        assert result.risk_level == RiskLevel.HIGH
        assert result.suggested_action == "warn"

    def test_analyze_action_medium_risk(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return [
                    {
                        "trace_id": "t3",
                        "failure_type": "error",
                        "description": "transient error",
                        "_distance": 0.3,
                    }
                ]

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.analyze_action({"action": "query"}, {})
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.suggested_action == "monitor"

    def test_analyze_action_low_risk(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return [
                    {
                        "trace_id": "t4",
                        "failure_type": "minor",
                        "description": "minor issue",
                        "_distance": 0.8,
                    }
                ]

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.analyze_action({"action": "safe"}, {})
        assert result.risk_level == RiskLevel.LOW
        assert result.suggested_action == "proceed"

    def test_analyze_action_store_exception(self):
        class BadStore:
            def search_by_text(self, text, limit=3):
                raise RuntimeError("DB error")

        pp = PredictiveFailurePrevention(vector_store=BadStore())
        result = pp.analyze_action({"action": "test"}, {})
        assert result.risk_level == RiskLevel.LOW
        assert "error" in result.explanation.lower()

    def test_simulate_whatif_no_store(self):
        pp = PredictiveFailurePrevention()
        result = pp.simulate_whatif({"a": 1}, {"b": 2})
        assert result["status"] == "skipped"

    def test_simulate_whatif_compatible(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return []

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.simulate_whatif({"a": 1}, {"b": 2})
        assert result["status"] == "compatible"
        assert result["sandboxed"] is True
        assert result["merged_action"] == {"a": 1, "b": 2}

    def test_simulate_whatif_conflict(self):
        class FakeStore:
            def search_by_text(self, text, limit=3):
                return []

        pp = PredictiveFailurePrevention(vector_store=FakeStore())
        result = pp.simulate_whatif({"a": 1}, {"a": 2})
        assert result["status"] == "conflict"
        assert "a" in result["conflicting_keys"]

    def test_calculate_risk_score_no_store(self):
        pp = PredictiveFailurePrevention()
        assert pp._calculate_risk_score({}, {}) == 0.1

    def test_calculate_risk_score_cached(self):
        pp = PredictiveFailurePrevention(vector_store=True)
        pp.history_cache['{"a": 1}'] = 0.75
        assert pp._calculate_risk_score({"a": 1}, {}) == 0.75


class TestPredictionResult:
    def test_fields(self):
        result = PredictionResult(
            risk_level=RiskLevel.HIGH,
            confidence=0.8,
            similar_failure_id="t1",
            similar_failure_type="timeout",
            similar_failure_description="API timeout",
            suggested_action="warn",
            explanation="high risk",
        )
        assert result.risk_level == RiskLevel.HIGH
        assert result.confidence == 0.8


class TestRiskLevel:
    def test_values(self):
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"
