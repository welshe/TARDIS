"""Tests for the ML-Assisted Failure Classification Engine."""

from tardis.ml_classifier import (
    MLFailureClassifier,
    StatisticalClassifier,
    _extract_features,
)
from tardis.models import FailureType, Step, StepType, Trace


def _make_failure_trace(
    failure_type: FailureType, error_text: str = "error", n_errors: int = 1
) -> Trace:
    trace = Trace()
    trace.add_step(
        Step(trace_id="test", index=0, type=StepType.llm_call, input={}, output={})
    )
    trace.add_step(
        Step(trace_id="test", index=1, type=StepType.tool_call, input={}, output={})
    )
    for i in range(n_errors):
        trace.add_step(
            Step(
                trace_id="test",
                index=2 + i,
                type=StepType.error,
                input={},
                output={"error": error_text},
            )
        )
    trace.failure_type = failure_type
    return trace


class TestFeatureExtraction:
    def test_extracts_basic_features(self):
        trace = _make_failure_trace(FailureType.tool_failure)
        features = _extract_features(trace)
        assert features["total_steps"] == 3
        assert features["llm_calls"] == 1.0
        assert features["tool_calls"] == 1.0
        assert features["error_count"] == 1.0
        assert features["total_cost"] >= 0.0

    def test_extracts_llm_hash_features(self):
        trace = Trace()
        trace.add_step(
            Step(
                trace_id="t",
                index=0,
                type=StepType.llm_call,
                input={},
                output={},
                hash="same",
            )
        )
        trace.add_step(
            Step(
                trace_id="t",
                index=1,
                type=StepType.llm_call,
                input={},
                output={},
                hash="same",
            )
        )
        features = _extract_features(trace)
        assert features["llm_hash_repetition_ratio"] > 0.0


class TestStatisticalClassifier:
    def test_classify_unknown_when_untrained(self):
        clf = StatisticalClassifier()
        trace = _make_failure_trace(FailureType.tool_failure)
        ftype, conf = clf.classify(trace)
        assert ftype == FailureType.unknown
        assert conf == 0.0

    def test_train_and_classify(self):
        clf = StatisticalClassifier()
        traces = [
            (
                _make_failure_trace(
                    FailureType.grounding_failure, "element not found", 2
                ),
                FailureType.grounding_failure,
            ),
            (
                _make_failure_trace(FailureType.tool_failure, "EBUSY", 3),
                FailureType.tool_failure,
            ),
            (
                _make_failure_trace(FailureType.reasoning_failure, "loop detected", 1),
                FailureType.reasoning_failure,
            ),
        ]
        clf.train(traces)
        assert clf.is_trained

        result_type, confidence = clf.classify(
            _make_failure_trace(FailureType.grounding_failure, "element not found", 2)
        )
        assert result_type in FailureType
        assert 0.0 <= confidence <= 1.0


class TestMLFailureClassifier:
    def test_classify_unknown_untrained(self):
        clf = MLFailureClassifier()
        trace = _make_failure_trace(FailureType.tool_failure)
        ftype, conf = clf.classify(trace)
        assert ftype == FailureType.unknown
        assert conf == 0.0

    def test_train_requires_minimum_samples(self):
        clf = MLFailureClassifier()
        trace = _make_failure_trace(FailureType.tool_failure)
        clf.train([(trace, FailureType.tool_failure)])
        assert not clf.is_trained

    def test_train_and_classify(self):
        clf = MLFailureClassifier()
        traces = [
            (
                _make_failure_trace(
                    FailureType.grounding_failure, "element not found", 2
                ),
                FailureType.grounding_failure,
            ),
            (
                _make_failure_trace(FailureType.tool_failure, "EBUSY", 3),
                FailureType.tool_failure,
            ),
            (
                _make_failure_trace(FailureType.reasoning_failure, "loop", 1),
                FailureType.reasoning_failure,
            ),
            (
                _make_failure_trace(FailureType.environment_drift, "rate limit", 2),
                FailureType.environment_drift,
            ),
        ]
        clf.train(traces)
        assert clf.is_trained

        ftype, conf = clf.classify(
            _make_failure_trace(FailureType.grounding_failure, "element not found", 2)
        )
        assert ftype in FailureType
        assert conf > 0.0

    def test_save_and_load_model(self, tmp_path):
        import os

        original_dir = os.getcwd()
        try:
            os.chdir(tmp_path)
            clf = MLFailureClassifier()
            traces = [
                (
                    _make_failure_trace(FailureType.grounding_failure, "element", 2),
                    FailureType.grounding_failure,
                ),
                (
                    _make_failure_trace(FailureType.tool_failure, "EBUSY", 3),
                    FailureType.tool_failure,
                ),
                (
                    _make_failure_trace(FailureType.reasoning_failure, "loop", 1),
                    FailureType.reasoning_failure,
                ),
                (
                    _make_failure_trace(FailureType.environment_drift, "rate", 2),
                    FailureType.environment_drift,
                ),
            ]
            clf.train(traces)
            clf.save_model("test_model")
            assert (tmp_path / ".tardis" / "models" / "test_model.json").exists()

            clf2 = MLFailureClassifier()
            assert clf2.load_model("test_model")
            assert clf2.is_trained
        finally:
            os.chdir(original_dir)

    def test_backend_property(self):
        clf = MLFailureClassifier()
        assert clf.backend == "none"

        traces = [
            (
                _make_failure_trace(FailureType.grounding_failure, "element", 2),
                FailureType.grounding_failure,
            ),
            (
                _make_failure_trace(FailureType.tool_failure, "EBUSY", 3),
                FailureType.tool_failure,
            ),
            (
                _make_failure_trace(FailureType.reasoning_failure, "loop", 1),
                FailureType.reasoning_failure,
            ),
            (
                _make_failure_trace(FailureType.environment_drift, "rate", 2),
                FailureType.environment_drift,
            ),
        ]
        clf.train(traces)
        assert clf.backend in ("statistical", "sklearn")
