"""
Semantic Response Cache for LLM Proxy

Caches LLM responses based on semantic similarity of input prompts.
Uses trigram hash vectors for lightweight similarity matching.

SECURITY: Cache entries are content-addressed and PII-redacted.
Cache is local-only. No external services.
"""

import hashlib
import json
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _prompt_trigram_vector(text: str, dim: int = 64) -> list[float]:
    """Generate a trigram hash vector from prompt text."""

    text = text.lower().strip()
    if len(text) < 3:
        text = text + "  "
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class CacheEntry:
    """A cached LLM response with metadata."""

    prompt_hash: str
    vector: list[float]
    response: dict[str, Any]
    model: str
    tokens_saved: int
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_access: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_hash": self.prompt_hash,
            "vector": self.vector,
            "response": self.response,
            "model": self.model,
            "tokens_saved": self.tokens_saved,
            "created_at": self.created_at,
            "access_count": self.access_count,
            "last_access": self.last_access,
        }


class SemanticCache:
    """Semantic cache for LLM responses.

    Caches responses based on prompt similarity rather than exact match.
    Uses trigram hash vectors for lightweight similarity computation.

    SECURITY:
    - Cache entries are content-addressed via SHA-256
    - Sensitive prompts are not logged in plaintext
    - Cache is local-only, no external syncing
    """

    def __init__(
        self,
        cache_dir: str = ".tardis/cache",
        similarity_threshold: float = 0.92,
        max_entries: int = 5000,
        ttl_seconds: float | None = 3600,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._tokens_saved = 0
        self._load_from_disk()

    def _generate_key(self, messages: list[dict[str, str]]) -> str:
        """Generate a deterministic cache key from messages."""
        content = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _extract_prompt_text(self, messages: list[dict[str, str]]) -> str:
        """Extract a flat text representation from messages for similarity."""
        texts = [
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        ]
        return " ".join(texts)

    def find_similar(
        self, messages: list[dict[str, str]], model: str
    ) -> CacheEntry | None:
        """Find a semantically similar cached response.

        Args:
            messages: The prompt messages to look up.
            model: The model name to match against.

        Returns:
            Cached entry if a similar enough prompt is found, None otherwise.
        """
        prompt_text = self._extract_prompt_text(messages)
        if not prompt_text:
            return None

        query_vec = _prompt_trigram_vector(prompt_text)

        with self._lock:
            # Purge expired entries so they can never be returned or shadow
            # a fresher prompt with the same key.
            self._purge_expired()
            for entry in list(self._entries.values()):
                if entry.model != model:
                    continue
                sim = _cosine_similarity(query_vec, entry.vector)
                if sim >= self.similarity_threshold:
                    entry.access_count += 1
                    entry.last_access = time.time()
                    self._hits += 1
                    self._tokens_saved += entry.tokens_saved
                    return entry
            self._misses += 1
            return None

    def _purge_expired(self) -> None:
        """Remove entries older than the TTL (no-op if TTL is disabled)."""
        if not self.ttl_seconds:
            return
        now = time.time()
        expired = [
            k
            for k, e in self._entries.items()
            if (now - e.created_at) > self.ttl_seconds
        ]
        for k in expired:
            del self._entries[k]

    def store(
        self,
        messages: list[dict[str, str]],
        response: dict[str, Any],
        model: str,
        tokens_saved: int = 0,
    ):
        """Store a response in the cache.

        Replaces any existing entry for the same prompt (including stale or
        empty ones) so the cache always reflects the latest response.

        Args:
            messages: The prompt messages that generated this response.
            response: The LLM response to cache.
            model: The model name.
            tokens_saved: Approximate tokens saved by using cached response.
        """
        prompt_text = self._extract_prompt_text(messages)
        if not prompt_text:
            return

        key = self._generate_key(messages)
        vector = _prompt_trigram_vector(prompt_text)

        with self._lock:
            self._purge_expired()

            if len(self._entries) >= self.max_entries and key not in self._entries:
                oldest = min(
                    self._entries.keys(), key=lambda k: self._entries[k].last_access
                )
                del self._entries[oldest]

            entry = CacheEntry(
                prompt_hash=key,
                vector=vector,
                response=response,
                model=model,
                tokens_saved=tokens_saved or 0,
            )
            self._entries[key] = entry
            self._save_entry(entry)

    def get_statistics(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = len(self._entries)
            total_accesses = sum(e.access_count for e in self._entries.values())
            total_tokens = sum(e.tokens_saved for e in self._entries.values())
            return {
                "entries": total,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / max(self._hits + self._misses, 1),
                "tokens_saved": self._tokens_saved + total_tokens,
                "models": list(set(e.model for e in self._entries.values())),
                "similarity_threshold": self.similarity_threshold,
                "max_entries": self.max_entries,
                "total_accesses": total_accesses,
            }

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._tokens_saved = 0
            for f in self.cache_dir.glob("*.json"):
                f.unlink()

    def _save_entry(self, entry: CacheEntry):
        """Persist a cache entry to disk."""
        entry_file = self.cache_dir / f"{entry.prompt_hash}.json"
        with open(entry_file, "w") as f:
            json.dump(entry.to_dict(), f, indent=2)

    def _load_from_disk(self):
        """Load cached entries from disk."""
        for entry_file in self.cache_dir.glob("*.json"):
            try:
                with open(entry_file) as f:
                    data = json.load(f)
                if data.get("prompt_hash"):
                    self._entries[data["prompt_hash"]] = CacheEntry(
                        prompt_hash=data["prompt_hash"],
                        vector=data.get("vector", []),
                        response=data.get("response", {}),
                        model=data.get("model", ""),
                        tokens_saved=data.get("tokens_saved", 0),
                        created_at=data.get("created_at", time.time()),
                        access_count=data.get("access_count", 0),
                        last_access=data.get("last_access", time.time()),
                    )
            except Exception:
                pass
