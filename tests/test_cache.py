"""Tests for the Semantic Response Cache."""

import tempfile

from tardis.capture.cache import (
    SemanticCache,
    _cosine_similarity,
    _prompt_trigram_vector,
)


def _make_cache(**kwargs):
    """Create a SemanticCache with a temp directory for test isolation."""
    tmpdir = tempfile.mkdtemp(prefix="tardis_test_cache_")
    kwargs.setdefault("cache_dir", tmpdir)
    return SemanticCache(**kwargs)


class TestVectorSimilarity:
    def test_same_prompt_high_similarity(self):
        v1 = _prompt_trigram_vector("Hello, how are you doing today?")
        v2 = _prompt_trigram_vector("Hello, how are you doing today?")
        sim = _cosine_similarity(v1, v2)
        assert sim > 0.99

    def test_different_prompts_low_similarity(self):
        v1 = _prompt_trigram_vector("What is the capital of France?")
        v2 = _prompt_trigram_vector("rm -rf / delete everything")
        sim = _cosine_similarity(v1, v2)
        assert sim < 0.5

    def test_similar_prompts_high_similarity(self):
        v1 = _prompt_trigram_vector("Write Python code to sort a list")
        v2 = _prompt_trigram_vector("Write Python code to sort an array")
        sim = _cosine_similarity(v1, v2)
        assert sim > 0.5


class TestSemanticCache:
    def test_miss_on_empty(self):
        cache = _make_cache(similarity_threshold=0.9, max_entries=100)
        result = cache.find_similar(
            [{"role": "user", "content": "hello"}],
            model="gpt-4o",
        )
        assert result is None
        assert cache.get_statistics()["misses"] == 1

    def test_store_and_hit(self):
        cache = _make_cache(similarity_threshold=0.9, max_entries=100)
        messages = [{"role": "user", "content": "What is 2+2?"}]
        response = {"content": "4", "model": "gpt-4o"}

        cache.store(messages, response, model="gpt-4o", tokens_saved=50)
        result = cache.find_similar(messages, model="gpt-4o")
        assert result is not None
        assert cache.get_statistics()["hits"] == 1

    def test_different_model_no_hit(self):
        cache = _make_cache(similarity_threshold=0.9, max_entries=100)
        messages = [{"role": "user", "content": "What is 2+2?"}]

        cache.store(messages, {"content": "4"}, model="gpt-4o", tokens_saved=50)
        result = cache.find_similar(messages, model="gpt-3.5-turbo")
        assert result is None

    def test_similar_prompt_hit(self):
        cache = _make_cache(similarity_threshold=0.7, max_entries=100)
        messages1 = [{"role": "user", "content": "Write Python to sort a list"}]
        messages2 = [{"role": "user", "content": "Write Python code to sort an array"}]

        cache.store(
            messages1, {"content": "use sorted()"}, model="gpt-4o", tokens_saved=50
        )
        result = cache.find_similar(messages2, model="gpt-4o")
        assert result is not None

    def test_ttl_expiry(self):
        import time

        cache = _make_cache(
            similarity_threshold=0.9, max_entries=100, ttl_seconds=0.001
        )
        messages = [{"role": "user", "content": "Hello"}]

        cache.store(messages, {"content": "Hi"}, model="gpt-4o", tokens_saved=10)
        time.sleep(0.01)
        result = cache.find_similar(messages, model="gpt-4o")
        assert result is None

    def test_max_entries_eviction(self):
        cache = _make_cache(similarity_threshold=0.99, max_entries=2)
        for i in range(5):
            msg = [{"role": "user", "content": f"Query {i}"}]
            cache.store(
                msg, {"content": f"Response {i}"}, model="gpt-4o", tokens_saved=10
            )

        stats = cache.get_statistics()
        assert stats["entries"] <= 2

    def test_clear(self):
        cache = _make_cache(similarity_threshold=0.9, max_entries=100)
        messages = [{"role": "user", "content": "Hello"}]
        cache.store(messages, {"content": "Hi"}, model="gpt-4o")
        cache.clear()
        assert cache.get_statistics()["entries"] == 0

    def test_statistics(self):
        cache = _make_cache(similarity_threshold=0.9, max_entries=100)
        messages = [{"role": "user", "content": "Hello"}]

        cache.store(messages, {"content": "Hi"}, model="gpt-4o", tokens_saved=10)
        cache.find_similar(messages, model="gpt-4o")
        cache.find_similar([{"role": "user", "content": "World"}], model="gpt-4o")

        stats = cache.get_statistics()
        assert stats["entries"] > 0
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["tokens_saved"] >= 10
