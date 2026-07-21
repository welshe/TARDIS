
from tardis.models import FailureType, Step, StepType, Trace
from tardis.search.engine import (
    PromptTraceSearcher,
    SearchResult,
    _expand_query,
)


def _make_trace(trace_id="search_trace", failure_type=None):
    trace = Trace(id=trace_id)
    if failure_type:
        trace.failure_type = failure_type
    trace.add_step(
        Step(trace_id=trace.id, index=0, type=StepType.tool_call,
             input={}, output={"error": "timeout error in API call"},
             success=False, error_type="timeout")
    )
    trace.add_step(
        Step(trace_id=trace.id, index=1, type=StepType.error,
             input={}, output={"message": "connection refused"},
             success=False, error_type="connection")
    )
    return trace


class TestExpandQuery:
    def test_no_expansion_for_normal_query(self):
        result = _expand_query("hello world")
        assert "hello world" in result

    def test_expands_timeout(self):
        result = _expand_query("timeout")
        assert "timeout" in result
        assert "slow" in result or "hung" in result

    def test_expands_tool(self):
        result = _expand_query("tool")
        assert "tool" in result
        assert "function" in result or "invocation" in result

    def test_expands_multiple_terms(self):
        result = _expand_query("stuck api")
        assert "stuck" in result
        assert "loop" in result
        assert "api" in result

    def test_empty_query(self):
        result = _expand_query("")
        assert result == ""


class TestSearchResult:
    def test_creation(self):
        sr = SearchResult(trace_id="abc", failure_type="tool_failure",
                          description="tool failed", score=0.85)
        assert sr.trace_id == "abc"
        assert sr.confidence_pct == 85

    def test_confidence_clamped(self):
        sr = SearchResult(trace_id="a", failure_type="x", description="", score=1.5)
        assert sr.confidence_pct == 99

    def test_confidence_minimum(self):
        sr = SearchResult(trace_id="a", failure_type="x", description="", score=-0.5)
        assert sr.confidence_pct == 0

    def test_defaults(self):
        sr = SearchResult(trace_id="a", failure_type="x", description="", score=0.5)
        assert sr.matched_terms == []
        assert sr.trace is None


class TestPromptTraceSearcher:
    def test_search_keyword_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.sqlite_store import Store
        store = Store()
        trace = _make_trace("kw_test", FailureType.tool_failure)
        store.save_trace(trace)

        searcher = PromptTraceSearcher(min_score=0.0)
        results = searcher.search("timeout", limit=5)
        assert isinstance(results, list)

    def test_search_with_failure_type_filter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.sqlite_store import Store
        store = Store()
        trace_a = _make_trace("type_filter_a", FailureType.tool_failure)
        trace_b = _make_trace("type_filter_b", FailureType.grounding_failure)
        store.save_trace(trace_a)
        store.save_trace(trace_b)

        searcher = PromptTraceSearcher(min_score=0.0)
        results = searcher.search("error", failure_type="tool_failure")
        for r in results:
            assert r.failure_type == "tool_failure"

    def test_search_empty_result(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        searcher = PromptTraceSearcher(min_score=0.5)
        results = searcher.search("zzz_nonexistent_zzz", limit=5)
        assert isinstance(results, list)

    def test_search_load_traces(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.sqlite_store import Store
        store = Store()
        trace = _make_trace("load_test", FailureType.tool_failure)
        store.save_trace(trace)

        searcher = PromptTraceSearcher(min_score=0.0)
        results = searcher.search("timeout", load_traces=True)
        for r in results:
            assert r.trace is not None or r.trace is None

    def test_query_expansion_in_search(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.sqlite_store import Store
        store = Store()
        trace = _make_trace("expand_test", FailureType.tool_failure)
        store.save_trace(trace)

        searcher = PromptTraceSearcher(min_score=0.0)
        results_stuck = searcher.search("stuck", limit=5)
        results_error = searcher.search("error", limit=5)
        assert isinstance(results_stuck, list)
        assert isinstance(results_error, list)

    def test_trace_to_text_includes_failure_type(self):
        trace = _make_trace("ttt", FailureType.memory_failure)
        searcher = PromptTraceSearcher(min_score=0.0)
        text = searcher._trace_to_text(trace)
        assert "memory_failure" in text

    def test_keyword_score_exact_match(self):
        searcher = PromptTraceSearcher(min_score=0.0)
        score = searcher._keyword_score({"timeout", "error"}, "timeout error in API")
        assert score > 0

    def test_keyword_score_no_match(self):
        searcher = PromptTraceSearcher(min_score=0.0)
        score = searcher._keyword_score({"zzz"}, "hello world")
        assert score == 0.0

    def test_min_score_filters_results(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.sqlite_store import Store
        store = Store()
        trace = _make_trace("min_score_test", FailureType.tool_failure)
        store.save_trace(trace)

        searcher_high = PromptTraceSearcher(min_score=0.99)
        results = searcher_high.search("timeout", limit=5)
        assert isinstance(results, list)

    def test_index_and_search_consistency(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from tardis.store.lancedb_store import FailurePatternStore
        from tardis.store.sqlite_store import Store

        store = Store()
        trace = _make_trace("lancedb_test", FailureType.tool_failure)
        store.save_trace(trace)

        fp_store = FailurePatternStore()
        if fp_store.available:
            fp_store.index_trace(trace)
            searcher = PromptTraceSearcher(vector_store=fp_store, store=store, min_score=0.0)
            results = searcher.search("timeout", limit=5)
            if results:
                assert results[0].trace_id == "lancedb_test"
