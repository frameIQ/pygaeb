"""Tests for the classification layer (cache, confidence, taxonomy)."""



from pygaeb.cache import SQLiteCache
from pygaeb.classifier.cache import ClassificationCache, compute_hash
from pygaeb.classifier.confidence import apply_confidence_flag
from pygaeb.classifier.taxonomy import (
    ALL_TRADES,
    get_subtypes,
    is_valid_element_type,
    is_valid_trade,
)
from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import ClassificationResult


class TestTaxonomy:
    def test_all_trades_populated(self):
        assert len(ALL_TRADES) >= 9

    def test_structural_is_valid(self):
        assert is_valid_trade("Structural")

    def test_invalid_trade(self):
        assert not is_valid_trade("Nonexistent")

    def test_wall_in_structural(self):
        assert is_valid_element_type("Structural", "Wall")

    def test_subtypes_for_wall(self):
        subtypes = get_subtypes("Structural", "Wall")
        assert "Interior Wall" in subtypes
        assert "Exterior Wall" in subtypes


class TestConfidence:
    def test_high_confidence_auto_classified(self):
        result = ClassificationResult(confidence=0.95)
        flagged = apply_confidence_flag(result)
        assert flagged.flag == ClassificationFlag.AUTO_CLASSIFIED

    def test_medium_confidence_spot_check(self):
        result = ClassificationResult(confidence=0.75)
        flagged = apply_confidence_flag(result)
        assert flagged.flag == ClassificationFlag.NEEDS_SPOT_CHECK

    def test_low_confidence_needs_review(self):
        result = ClassificationResult(confidence=0.40)
        flagged = apply_confidence_flag(result)
        assert flagged.flag == ClassificationFlag.NEEDS_REVIEW

    def test_manual_override_preserved(self):
        result = ClassificationResult(
            confidence=0.40,
            flag=ClassificationFlag.MANUAL_OVERRIDE,
        )
        flagged = apply_confidence_flag(result)
        assert flagged.flag == ClassificationFlag.MANUAL_OVERRIDE


class TestCache:
    """Test ClassificationCache with default InMemoryCache backend."""

    def test_put_and_get(self):
        cache = ClassificationCache()
        result = ClassificationResult(
            trade="Structural",
            element_type="Wall",
            confidence=0.9,
        )
        h = compute_hash("test short text", "test long text")
        cache.put(h, "v1", result)

        retrieved = cache.get(h, "v1")
        assert retrieved is not None
        assert retrieved.trade == "Structural"
        assert retrieved.cached is True

    def test_cache_miss(self):
        cache = ClassificationCache()
        h = compute_hash("nonexistent", "text")
        assert cache.get(h, "v1") is None

    def test_different_prompt_version(self):
        cache = ClassificationCache()
        result = ClassificationResult(trade="Structural", confidence=0.9)
        h = compute_hash("text", "more")
        cache.put(h, "v1", result)
        assert cache.get(h, "v2") is None

    def test_stats(self):
        cache = ClassificationCache()
        result = ClassificationResult(trade="Structural", confidence=0.9)
        cache.put(compute_hash("a", "b"), "v1", result)
        cache.put(compute_hash("c", "d"), "v1", result)
        stats = cache.stats()
        assert len(stats) == 1
        assert stats[0]["count"] == 2


class TestCacheWithSQLiteBackend:
    """Test ClassificationCache with opt-in SQLiteCache backend."""

    def test_put_and_get_sqlite(self, tmp_path):
        backend = SQLiteCache(str(tmp_path))
        cache = ClassificationCache(backend)
        result = ClassificationResult(
            trade="Structural", element_type="Wall", confidence=0.9,
        )
        h = compute_hash("test short text", "test long text")
        cache.put(h, "v1", result)

        retrieved = cache.get(h, "v1")
        assert retrieved is not None
        assert retrieved.trade == "Structural"
        assert retrieved.cached is True
        cache.close()

    def test_persistence_across_instances(self, tmp_path):
        backend1 = SQLiteCache(str(tmp_path))
        cache1 = ClassificationCache(backend1)
        result = ClassificationResult(trade="MEP", confidence=0.85)
        h = compute_hash("pipe", "copper")
        cache1.put(h, "v1", result)
        cache1.close()

        backend2 = SQLiteCache(str(tmp_path))
        cache2 = ClassificationCache(backend2)
        retrieved = cache2.get(h, "v1")
        assert retrieved is not None
        assert retrieved.trade == "MEP"
        cache2.close()


class TestComputeHash:
    def test_deterministic(self):
        h1 = compute_hash("hello", "world")
        h2 = compute_hash("hello", "world")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = compute_hash("hello", "world")
        h2 = compute_hash("goodbye", "world")
        assert h1 != h2
