from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Trace
from ..store.lancedb_store import FailurePatternStore, _trigram_hash_vector
from ..store.sqlite_store import Store

_WHITESPACE = re.compile(r"\s+")
_MAX_QUERY_LENGTH = 2000


def _expand_query(query: str) -> str:
    """Expand a natural language query with failure-related synonyms."""
    expansions = {
        "stuck": "stuck loop repeated infinite hang",
        "loop": "loop repeated repetition cycle infinite iteration",
        "timeout": "timeout timed out timing out slow hung",
        "error": "error failure exception crash fault bug",
        "crash": "crash crashed segfault panic abort",
        "auth": "authentication unauthorized forbidden login credential",
        "rate": "rate limit throttled quota exceeded",
        "token": "token context length exceeded overflow",
        "grounding": "grounding element not found selector missing layout",
        "tool": "tool call invocation function failed broken",
        "memory": "memory context overflow oom exhausted",
        "api": "api endpoint server 429 500 503 gateway",
        "permission": "permission denied access forbidden authorization",
    }
    parts = [query]
    query_lower = query.lower()
    for key, synonyms in expansions.items():
        if key in query_lower:
            parts.append(synonyms)
    return " ".join(parts)


@dataclass
class SearchResult:
    trace_id: str
    failure_type: str
    description: str
    score: float
    match_field: str = "vector"
    matched_terms: list[str] = field(default_factory=list)
    trace: Trace | None = None

    @property
    def confidence_pct(self) -> int:
        return min(99, max(0, int(self.score * 100)))


class PromptTraceSearcher:
    """Search failure traces using natural language prompts.

    Uses LanceDB vector store for semantic similarity, with query expansion
    and relevance scoring. Falls back to keyword-based search when LanceDB
    is not available.
    """

    def __init__(
        self,
        vector_store: FailurePatternStore | None = None,
        store: Store | None = None,
        min_score: float = 0.15,
    ):
        self.vector_store = vector_store or FailurePatternStore()
        self.store = store or Store()
        self.min_score = min_score

    def search(
        self,
        query: str,
        limit: int = 10,
        failure_type: str | None = None,
        load_traces: bool = False,
    ) -> list[SearchResult]:
        if not query or not query.strip():
            return []
        query = query[:_MAX_QUERY_LENGTH]
        limit = max(1, min(limit, 100))
        expanded = _expand_query(query)
        query_vector = _trigram_hash_vector(expanded)

        if self.vector_store.available:
            return self._vector_search(query, expanded, query_vector, limit, failure_type, load_traces)

        return self._keyword_fallback(query, limit, failure_type, load_traces)

    def _vector_search(
        self,
        query: str,
        expanded: str,
        query_vector: list[float],
        limit: int,
        failure_type: str | None,
        load_traces: bool,
    ) -> list[SearchResult]:
        try:
            raw = self.vector_store._table.search(query_vector).limit(limit * 2).to_list()
        except Exception:
            return self._keyword_fallback(query, limit, failure_type, load_traces)

        results = []
        terms = set(query.lower().split())

        for r in raw:
            if failure_type and r.get("failure_type") != failure_type:
                continue

            desc = r.get("description", "")
            dist = float(r.get("_distance", 1.0))
            dist = min(1.0, max(0.0, dist))
            score = 1.0 - dist

            if score < self.min_score:
                continue

            matched = [t for t in terms if t in desc.lower()]

            results.append(SearchResult(
                trace_id=r.get("trace_id", "unknown"),
                failure_type=r.get("failure_type", "unknown"),
                description=desc[:500],
                score=score,
                match_field="vector",
                matched_terms=matched,
            ))

        results.sort(key=lambda x: x.score, reverse=True)
        results = results[:limit]

        if load_traces:
            for r in results:
                r.trace = self.store.get_trace(r.trace_id)

        return results

    def _keyword_fallback(
        self,
        query: str,
        limit: int,
        failure_type: str | None,
        load_traces: bool,
    ) -> list[SearchResult]:
        traces = self.store.list_traces()
        query_terms = set(query.lower().split())
        results = []

        for t_data in traces:
            trace = self.store.get_trace(t_data["id"])
            if trace is None:
                continue

            if failure_type and trace.failure_type and trace.failure_type.value != failure_type:
                continue

            text = self._trace_to_text(trace)
            score = self._keyword_score(query_terms, text)
            if score <= 0:
                continue
            score = min(0.95, score)

            matched = [t for t in query_terms if t in text.lower()]

            results.append(SearchResult(
                trace_id=trace.id,
                failure_type=trace.failure_type.value if trace.failure_type else "unknown",
                description=text[:500],
                score=score,
                match_field="keyword",
                matched_terms=matched,
                trace=trace if load_traces else None,
            ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def _trace_to_text(self, trace: Trace) -> str:
        parts = []
        if trace.failure_type:
            parts.append(trace.failure_type.value)
        for s in trace.steps[-5:]:
            parts.append(f"{s.type.value}: {str(s.output)[:200]}")
            if not s.success:
                parts.append(f"error: {s.error_type or 'unknown'}")
        return " | ".join(parts)

    def _keyword_score(self, query_terms: set[str], text: str) -> float:
        text_lower = text.lower()
        matches = sum(1 for t in query_terms if t in text_lower)
        if matches == 0:
            return 0.0
        return matches / len(query_terms) * min(1.0, len(text) / 100.0)
