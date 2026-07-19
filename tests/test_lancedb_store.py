import pytest
from tardis.store.lancedb_store import (
    FailurePatternStore,
    _trigram_hash_vector,
    _extract_failure_text,
    VECTOR_DIM,
)
from tardis.models import Trace, Step, StepType, FailureType
import math


class TestTrigramHashVector:
    def test_dimension(self):
        v = _trigram_hash_vector("hello world")
        assert len(v) == VECTOR_DIM

    def test_unit_vector(self):
        v = _trigram_hash_vector("hello world")
        magnitude = math.sqrt(sum(c * c for c in v))
        assert abs(magnitude - 1.0) < 1e-6

    def test_short_text(self):
        v = _trigram_hash_vector("ab")
        assert len(v) == VECTOR_DIM
        magnitude = math.sqrt(sum(c * c for c in v))
        assert abs(magnitude - 1.0) < 1e-6

    def test_empty_text(self):
        v = _trigram_hash_vector("")
        assert len(v) == VECTOR_DIM

    def test_similar_texts_closer(self):
        a = _trigram_hash_vector("timeout error in API call to server")
        b = _trigram_hash_vector("timeout error in API call to backend")
        c = _trigram_hash_vector("the quick brown fox jumps over")
        dist_ab = sum((x - y) ** 2 for x, y in zip(a, b))
        dist_ac = sum((x - y) ** 2 for x, y in zip(a, c))
        assert dist_ab < dist_ac, "similar texts should have lower distance"

    def test_different_texts_far(self):
        a = _trigram_hash_vector("aaaaaaaaaaaaaaaaaaaaaaaa")
        b = _trigram_hash_vector("bbbbbbbbbbbbbbbbbbbbbbbb")
        c = _trigram_hash_vector("aaaaaaaaaaaaaaaaaaaaaaab")
        dist_ab = sum((x - y) ** 2 for x, y in zip(a, b))
        dist_ac = sum((x - y) ** 2 for x, y in zip(a, c))
        assert dist_ac < dist_ab, "similar texts should be closer"


class TestExtractFailureText:
    def test_error_steps_present(self):
        trace = Trace()
        trace.add_step(Step(
            trace_id=trace.id, index=0, type=StepType.error,
            output={"message": "something went wrong with the server"},
            success=False,
        ))
        text = _extract_failure_text(trace)
        assert "something went wrong" in text

    def test_fallback_to_last_step(self):
        trace = Trace()
        trace.add_step(Step(
            trace_id=trace.id, index=0, type=StepType.llm_call,
            output={"completion": "I think we should try again"},
        ))
        text = _extract_failure_text(trace)
        assert "llm_call" in text or "try again" in text

    def test_includes_failure_type(self):
        trace = Trace()
        trace.failure_type = FailureType.tool_failure
        trace.add_step(Step(
            trace_id=trace.id, index=0, type=StepType.error,
            output={"message": "tool error"},
            success=False,
        ))
        text = _extract_failure_text(trace)
        assert "tool_failure" in text


class TestFailurePatternStore:
    def test_store_creation(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        assert store.vector_dim == VECTOR_DIM

    def test_index_skips_successful_trace(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        trace = Trace()
        trace.add_step(Step(
            trace_id=trace.id, index=0, type=StepType.llm_call,
            input={}, output={}, success=True,
        ))
        result = store.index_trace(trace)
        if store.available:
            assert not result

    def test_search_similar_graceful_degradation(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        trace = Trace()
        trace.add_step(Step(
            trace_id=trace.id, index=0, type=StepType.error,
            output={"message": "test error"},
            success=False,
        ))
        results = store.search_similar(trace, limit=3)
        assert isinstance(results, list)
        if store.available:
            store.delete_trace(trace.id)

    def test_search_by_text(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        results = store.search_by_text("timeout error", limit=3)
        assert isinstance(results, list)

    def test_count(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        count = store.count()
        assert isinstance(count, int)

    def test_list_all(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        results = store.list_all(limit=5)
        assert isinstance(results, list)

    def test_delete_nonexistent(self):
        store = FailurePatternStore(db_path=".tardis/test_lancedb")
        result = store.delete_trace("nonexistent-id-12345")
        if store.available:
            assert result
        else:
            assert not result

    def test_available_property(self):
        store = FailurePatternStore()
        assert isinstance(store.available, bool)
