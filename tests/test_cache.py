"""Tests for the pluggable cache backend layer."""

from __future__ import annotations

from pygaeb.cache import CacheBackend, InMemoryCache, SQLiteCache


class TestInMemoryCache:
    def test_put_and_get(self):
        cache = InMemoryCache()
        cache.put("k1", '{"a": 1}')
        assert cache.get("k1") == '{"a": 1}'

    def test_miss_returns_none(self):
        cache = InMemoryCache()
        assert cache.get("missing") is None

    def test_overwrite(self):
        cache = InMemoryCache()
        cache.put("k1", "v1")
        cache.put("k1", "v2")
        assert cache.get("k1") == "v2"

    def test_delete(self):
        cache = InMemoryCache()
        cache.put("k1", "v1")
        cache.delete("k1")
        assert cache.get("k1") is None

    def test_delete_nonexistent_is_noop(self):
        cache = InMemoryCache()
        cache.delete("nope")

    def test_clear(self):
        cache = InMemoryCache()
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert cache.get("k1") is None
        assert len(cache) == 0

    def test_keys(self):
        cache = InMemoryCache()
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        assert set(cache.keys()) == {"k1", "k2"}

    def test_len(self):
        cache = InMemoryCache()
        assert len(cache) == 0
        cache.put("k1", "v1")
        assert len(cache) == 1

    def test_close_is_noop(self):
        cache = InMemoryCache()
        cache.close()

    def test_satisfies_protocol(self):
        assert isinstance(InMemoryCache(), CacheBackend)


class TestSQLiteCache:
    def test_put_and_get(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        cache.put("k1", '{"a": 1}')
        assert cache.get("k1") == '{"a": 1}'
        cache.close()

    def test_miss_returns_none(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        assert cache.get("missing") is None
        cache.close()

    def test_overwrite(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        cache.put("k1", "v1")
        cache.put("k1", "v2")
        assert cache.get("k1") == "v2"
        cache.close()

    def test_delete(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        cache.put("k1", "v1")
        cache.delete("k1")
        assert cache.get("k1") is None
        cache.close()

    def test_clear(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert len(cache) == 0
        cache.close()

    def test_keys(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        assert set(cache.keys()) == {"k1", "k2"}
        cache.close()

    def test_len(self, tmp_path):
        cache = SQLiteCache(str(tmp_path))
        cache.put("k1", "v1")
        assert len(cache) == 1
        cache.close()

    def test_persistence_across_instances(self, tmp_path):
        c1 = SQLiteCache(str(tmp_path))
        c1.put("k1", "persistent-value")
        c1.close()

        c2 = SQLiteCache(str(tmp_path))
        assert c2.get("k1") == "persistent-value"
        c2.close()

    def test_satisfies_protocol(self, tmp_path):
        assert isinstance(SQLiteCache(str(tmp_path)), CacheBackend)

    def test_creates_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir"
        cache = SQLiteCache(str(nested))
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"
        cache.close()

    def test_home_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        cache = SQLiteCache("~/test-cache")
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"
        cache.close()
