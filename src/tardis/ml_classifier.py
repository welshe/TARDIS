"""
ML-Assisted Failure Classification Engine

Uses scikit-learn (when available) or a lightweight statistical classifier
to classify failure types from trace features with higher accuracy than
the heuristic-only approach in autopsy.classifier.

SECURITY: No external model loading. Only sklearn if installed (optional dep).
All training data stays local. No data exfiltration.
"""

import json
import math
import threading
from pathlib import Path
from typing import Any

from .models import FailureType, StepType, Trace
from .store.lancedb_store import _trigram_hash_vector

_HAS_SKLEARN = False
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import Pipeline

    _HAS_SKLEARN = True
except ImportError:
    pass


VECTOR_DIM = 128
_ACCUMULATOR_TYPES = {
    StepType.llm_call: "llm_calls",
    StepType.tool_call: "tool_calls",
    StepType.error: "errors",
    StepType.dom_snapshot: "dom_snapshots",
    StepType.accessibility_snapshot: "acc_snapshots",
}


def _extract_features(trace: Trace) -> dict[str, float]:
    """Extract numerical feature vector from a trace for ML classification."""
    features = {}
    total_steps = len(trace.steps)
    features["total_steps"] = float(total_steps)
    features["total_cost"] = trace.total_cost_usd
    features["total_tokens"] = float(trace.total_tokens)
    features["duration_seconds"] = trace.get_duration_seconds()

    for stype, key in _ACCUMULATOR_TYPES.items():
        count = len([s for s in trace.steps if s.type == stype])
        features[key] = float(count)
        features[f"{key}_ratio"] = count / max(total_steps, 1)

    error_steps = trace.get_error_steps()
    features["error_count"] = float(len(error_steps))
    features["error_ratio"] = len(error_steps) / max(total_steps, 1)

    tool_calls = trace.get_steps_by_type(StepType.tool_call)
    tool_failures = [s for s in tool_calls if not s.success]
    features["tool_failure_count"] = float(len(tool_failures))
    features["tool_failure_ratio"] = len(tool_failures) / max(len(tool_calls), 1)

    llm_calls = trace.get_steps_by_type(StepType.llm_call)
    if llm_calls:
        durations = [s.duration_ms or 0 for s in llm_calls]
        features["avg_llm_duration_ms"] = sum(durations) / len(durations)
        features["max_llm_duration_ms"] = float(max(durations))
        hashes = [s.hash for s in llm_calls if s.hash]
        features["llm_hash_repetition_ratio"] = (
            (1.0 - (len(set(hashes)) / max(len(hashes), 1))) if hashes else 0.0
        )
    else:
        features["avg_llm_duration_ms"] = 0.0
        features["max_llm_duration_ms"] = 0.0
        features["llm_hash_repetition_ratio"] = 0.0

    dom_steps = trace.get_steps_by_type(StepType.dom_snapshot)
    features["dom_snapshot_count"] = float(len(dom_steps))
    acc_steps = trace.get_steps_by_type(StepType.accessibility_snapshot)
    features["acc_snapshot_count"] = float(len(acc_steps))
    features["snapshot_count"] = float(len(dom_steps) + len(acc_steps))

    return features


def _features_to_vector(features: dict[str, float]) -> list[float]:
    """Convert feature dict to a fixed-length vector for ML."""
    keys = sorted(features.keys())
    return [features[k] for k in keys]


_FEATURE_KEYS = [
    "total_steps",
    "total_cost",
    "total_tokens",
    "duration_seconds",
    "llm_calls",
    "tool_calls",
    "errors",
    "dom_snapshots",
    "acc_snapshots",
    "llm_calls_ratio",
    "tool_calls_ratio",
    "errors_ratio",
    "dom_snapshots_ratio",
    "acc_snapshots_ratio",
    "error_count",
    "error_ratio",
    "tool_failure_count",
    "tool_failure_ratio",
    "avg_llm_duration_ms",
    "max_llm_duration_ms",
    "llm_hash_repetition_ratio",
    "dom_snapshot_count",
    "acc_snapshot_count",
    "snapshot_count",
]


class StatisticalClassifier:
    """Lightweight statistical classifier that does not require sklearn.

    Uses trigram hash vectors and cosine similarity against known failure
    prototype vectors. Falls back to heuristic analysis when no training
    data is available.
    """

    def __init__(self):
        self._prototypes: dict[FailureType, list[float]] = {}
        self._trained = False
        self._lock = threading.Lock()

    def train(self, traces: list[tuple[Trace, FailureType]]):
        """Train from known labeled traces."""
        with self._lock:
            by_type: dict[FailureType, list[list[float]]] = {}
            for trace, label in traces:
                text = self._trace_to_text(trace)
                vec = _trigram_hash_vector(text, VECTOR_DIM)
                if label not in by_type:
                    by_type[label] = []
                by_type[label].append(vec)

            for ftype, vecs in by_type.items():
                if vecs:
                    avg = [
                        sum(v[i] for v in vecs) / len(vecs) for i in range(VECTOR_DIM)
                    ]
                    self._prototypes[ftype] = avg

            self._trained = True

    def classify(self, trace: Trace) -> tuple[FailureType, float]:
        """Classify a trace. Returns (failure_type, confidence)."""
        if not self._trained or not self._prototypes:
            return FailureType.unknown, 0.0

        text = self._trace_to_text(trace)
        vec = _trigram_hash_vector(text, VECTOR_DIM)

        best_type = FailureType.unknown
        best_score = -1.0

        for ftype, proto in self._prototypes.items():
            sim = self._cosine_similarity(vec, proto)
            if sim > best_score:
                best_score = sim
                best_type = ftype

        return best_type, max(0.0, min(1.0, best_score))

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _trace_to_text(self, trace: Trace) -> str:
        parts = []
        error_steps = trace.get_error_steps()
        if error_steps:
            parts.append(str(error_steps[-1].output))
        steps_text = " ".join(
            f"{s.type.value}:{str(s.output)[:100]}" for s in trace.steps[-5:]
        )
        parts.append(steps_text)
        return " | ".join(parts)

    @property
    def is_trained(self) -> bool:
        return self._trained


class SklearnClassifier:
    """Advanced classifier using scikit-learn when available.

    Falls back to StatisticalClassifier if sklearn is not installed.
    """

    def __init__(self):
        self._statistical = StatisticalClassifier()
        self._pipeline: Any = None
        self._label_map: dict[int, FailureType] = {}
        self._reverse_map: dict[FailureType, int] = {}
        self._trained = False
        self._lock = threading.Lock()

    def train(self, traces: list[tuple[Trace, FailureType]]):
        """Train the model on labeled traces."""
        self._statistical.train(traces)

        if not _HAS_SKLEARN:
            self._trained = self._statistical.is_trained
            return

        with self._lock:
            unique_labels = sorted(
                set(label for _, label in traces), key=lambda x: x.value
            )
            self._label_map = {i: ft for i, ft in enumerate(unique_labels)}
            self._reverse_map = {ft: i for i, ft in self._label_map.items()}

            X_texts = []  # noqa: N806
            y_labels = []
            for trace, label in traces:
                X_texts.append(self._statistical._trace_to_text(trace))
                y_labels.append(self._reverse_map[label])

            self._pipeline = Pipeline(
                [
                    ("tfidf", TfidfVectorizer(max_features=500, ngram_range=(1, 3))),
                    (
                        "clf",
                        RandomForestClassifier(
                            n_estimators=100,
                            max_depth=10,
                            random_state=42,
                            class_weight="balanced",
                        ),
                    ),
                ]
            )
            self._pipeline.fit(X_texts, y_labels)
            self._trained = True

    def classify(self, trace: Trace) -> tuple[FailureType, float]:
        """Classify using sklearn (if available) or statistical fallback."""
        if not self._trained:
            return FailureType.unknown, 0.0

        if self._pipeline is not None:
            with self._lock:
                text = [self._statistical._trace_to_text(trace)]
                try:
                    probs = self._pipeline.predict_proba(text)[0]
                    pred_idx = int(self._pipeline.predict(text)[0])
                    confidence = float(max(probs))
                    return self._label_map.get(
                        pred_idx, FailureType.unknown
                    ), confidence
                except Exception:
                    return self._statistical.classify(trace)

        return self._statistical.classify(trace)

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def uses_sklearn(self) -> bool:
        return self._pipeline is not None


class MLFailureClassifier:
    """High-level ML-assisted failure classifier.

    Wraps both statistical and sklearn-based classifiers.
    Auto-selects the best available implementation.

    Usage:
        classifier = MLFailureClassifier()
        classifier.train(labeled_traces)
        failure_type, confidence = classifier.classify(trace)
    """

    def __init__(self, model_dir: str = ".tardis/models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._classifier = SklearnClassifier()
        self._trained = False

    def train(self, traces: list[tuple[Trace, FailureType]]):
        """Train the classifier on labeled traces.

        Args:
            traces: List of (Trace, FailureType) pairs.
        """
        if len(traces) < 2:
            self._trained = False
            return
        self._classifier.train(traces)
        self._trained = True

    def classify(self, trace: Trace) -> tuple[FailureType, float]:
        """Classify a trace.

        Returns:
            Tuple of (failure_type, confidence) where confidence is 0.0-1.0.
        """
        if not self._trained:
            return FailureType.unknown, 0.0
        return self._classifier.classify(trace)

    def save_model(self, name: str = "failure_classifier"):
        """Persist trained model state to disk."""
        model_file = self.model_dir / f"{name}.json"
        state = {
            "trained": self._trained,
            "uses_sklearn": getattr(self._classifier, "uses_sklearn", False),
            "statistical_prototypes": {
                k.value: v
                for k, v in getattr(
                    self._classifier, "_statistical", self._classifier
                )._prototypes.items()
            }
            if self._trained
            else {},
        }
        with open(model_file, "w") as f:
            json.dump(state, f, indent=2)

    def load_model(self, name: str = "failure_classifier") -> bool:
        """Load trained model state from disk."""
        model_file = self.model_dir / f"{name}.json"
        if not model_file.exists():
            return False
        try:
            with open(model_file) as f:
                state = json.load(f)
            self._trained = state.get("trained", False)
            prototypes = state.get("statistical_prototypes", {})
            if prototypes:
                stat_clf = getattr(self._classifier, "_statistical", self._classifier)
                for ftype_str, vec in prototypes.items():
                    if (
                        not isinstance(vec, list)
                        or len(vec) != VECTOR_DIM
                        or not all(isinstance(x, (int, float)) for x in vec)
                    ):
                        # Skip malformed prototypes rather than silently
                        # loading a vector with the wrong dimension.
                        continue
                    stat_clf._prototypes[FailureType(ftype_str)] = vec
                if stat_clf._prototypes:
                    stat_clf._trained = True
                    self._classifier._trained = True
                    self._trained = True
            return True
        except Exception:
            return False

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def backend(self) -> str:
        if self._classifier.uses_sklearn:
            return "sklearn"
        if self._classifier.is_trained:
            return "statistical"
        return "none"
