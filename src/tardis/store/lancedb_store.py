"""
LanceDB-backed vector store for failure pattern similarity search.

Stores failure traces as embeddings for fast similarity search, enabling
the autopsy system to find similar past failures and provide richer diagnostics.

Uses character n-gram feature hashing for vector generation when no ML
library is available. Falls back gracefully if LanceDB is not installed.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import Trace

VECTOR_DIM = 128
_WHITESPACE = re.compile(r"\s+")


def _trigram_hash_vector(text: str, dim: int = VECTOR_DIM) -> list[float]:
    """
    Generate a normalized feature vector from character trigrams.

    Uses a hashing trick: each trigram is hashed to a dimension index,
    then the vector is L2-normalized. This gives a simple but effective
    representation for similarity search without ML dependencies.
    """
    text = _WHITESPACE.sub(" ", text.lower()).strip()
    if len(text) < 3:
        text = text + "  "  # pad for trigrams

    counts = [0.0] * dim

    for i in range(len(text) - 2):
        trigram = text[i : i + 3]
        h = hashlib.md5(trigram.encode()).digest()
        idx = struct.unpack("<I", h[:4])[0] % dim
        counts[idx] += 1.0

    magnitude = sum(c * c for c in counts) ** 0.5
    if magnitude > 0:
        return [c / magnitude for c in counts]
    return counts


def _extract_failure_text(trace: Trace) -> str:
    """Extract a human-readable failure summary from a trace for embedding."""
    parts = []

    error_steps = trace.get_error_steps()
    if error_steps:
        last_error = error_steps[-1]
        err_out = str(last_error.output)
        if err_out and err_out != "{}":
            parts.append(err_out[:500])

    if not parts:
        last = trace.steps[-1]
        parts.append(f"{last.type.value}: {str(last.output)[:300]}")

    if trace.failure_type:
        parts.insert(0, str(trace.failure_type.value))

    return " | ".join(parts)


@dataclass
class FailurePatternStore:
    """
    Vector store for failure patterns backed by LanceDB.

    Indexes failure traces so the autopsy system can find similar past
    failures and provide context-aware diagnostics.

    Usage:
        store = FailurePatternStore()
        store.index_trace(trace)
        similar = store.search_similar(trace, limit=5)
    """

    db_path: str = ".tardis/lancedb"
    table_name: str = "failure_patterns"
    vector_dim: int = VECTOR_DIM

    _db: Any | None = field(default=None, repr=False)
    _table: Any | None = field(default=None, repr=False)
    _available: bool = field(default=False, repr=False)

    def __post_init__(self):
        self._ensure_dir()
        self._try_connect()

    def _ensure_dir(self):
        Path(self.db_path).mkdir(parents=True, exist_ok=True)

    def _try_connect(self):
        try:
            import lancedb
            import pyarrow as pa  # noqa: F401

            self._db = lancedb.connect(self.db_path)
            self._available = True
        except ImportError:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _ensure_table(self):
        if self._table is not None:
            return
        import pyarrow as pa

        try:
            self._table = self._db.open_table(self.table_name)
        except Exception:
            schema = pa.schema(
                [
                    pa.field("trace_id", pa.string()),
                    pa.field("failure_type", pa.string()),
                    pa.field("description", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), self.vector_dim)),
                    pa.field("timestamp", pa.float64()),
                    pa.field("step_count", pa.int32()),
                    pa.field("total_cost_usd", pa.float32()),
                ]
            )
            self._table = self._db.create_table(self.table_name, schema=schema)

    def index_trace(self, trace: Trace) -> bool:
        """
        Index a failed trace into the vector store.

        Returns True if the trace was indexed, False if skipped (no failure
        or LanceDB unavailable).
        """
        if not self._available:
            return False

        if trace.success and not trace.get_error_steps():
            return False

        if not re.match(r"^[a-zA-Z0-9_-]{1,128}$", trace.id):
            return False

        self._ensure_table()

        text = _extract_failure_text(trace)
        vector = _trigram_hash_vector(text)

        rows = [
            {
                "trace_id": trace.id,
                "failure_type": trace.failure_type.value
                if trace.failure_type
                else "unknown",
                "description": text[:1000],
                "vector": vector,
                "timestamp": trace.created_at,
                "step_count": len(trace.steps),
                "total_cost_usd": float(trace.total_cost_usd or 0.0),
            }
        ]

        self._table.add(rows)
        return True

    def search_similar(self, trace: Trace, limit: int = 5) -> list[dict]:
        """
        Search for traces similar to the given failed trace.

        Returns list of dicts with keys: trace_id, failure_type, description,
        timestamp, step_count, _distance.
        """
        if not self._available:
            return self._fallback_search(trace, limit)

        self._ensure_table()

        text = _extract_failure_text(trace)
        vector = _trigram_hash_vector(text)

        try:
            results = self._table.search(vector).limit(limit).to_list()
            return [
                {
                    "trace_id": r["trace_id"],
                    "failure_type": r["failure_type"],
                    "description": r["description"],
                    "timestamp": r["timestamp"],
                    "step_count": r["step_count"],
                    "_distance": r.get("_distance", 1.0),
                }
                for r in results
                if r["trace_id"] != trace.id
            ]
        except Exception:
            return []

    def search_by_text(self, text: str, limit: int = 5) -> list[dict]:
        """Search for failures similar to a description string."""
        if not self._available:
            return []

        self._ensure_table()
        vector = _trigram_hash_vector(text)

        try:
            results = self._table.search(vector).limit(limit).to_list()
            return [
                {
                    "trace_id": r["trace_id"],
                    "failure_type": r["failure_type"],
                    "description": r["description"],
                    "timestamp": r["timestamp"],
                    "step_count": r["step_count"],
                    "_distance": r.get("_distance", 1.0),
                }
                for r in results
            ]
        except Exception:
            return []

    def _fallback_search(self, trace: Trace, limit: int = 5) -> list[dict]:
        """Simple O(n) search when LanceDB is not available."""
        # Return empty list - SQLite handles trace storage,
        # vector search requires LanceDB
        return []

    def delete_trace(self, trace_id: str) -> bool:
        if not self._available:
            return False
        self._ensure_table()
        try:
            if not re.match(r"^[a-zA-Z0-9_-][a-zA-Z0-9_-]*$", trace_id):
                raise ValueError(
                    "Invalid trace_id format: must be alphanumeric with hyphens/underscores only"
                )
            import pyarrow as pa

            table = self._table.to_arrow()
            mask = pa.compute.equal(table.column("trace_id"), trace_id)
            filtered = pa.compute.filter(table, pa.compute.invert(mask))
            self._db.drop_table(self.table_name)
            self._table = self._db.create_table(self.table_name, filtered)
            return True
        except Exception:
            return False

    def count(self) -> int:
        if not self._available:
            return 0
        try:
            self._ensure_table()
            return self._table.count_rows()
        except Exception:
            return 0

    def list_all(self, limit: int = 50) -> list[dict]:
        if not self._available:
            return []
        self._ensure_table()
        try:
            return self._table.to_pandas().head(limit).to_dict("records")
        except Exception:
            return []
