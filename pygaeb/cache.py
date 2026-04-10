"""Pluggable cache backends — in-memory (default) and SQLite (opt-in persistent).

Usage:
    # Default: in-memory, no disk, no surprises
    classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")

    # Opt-in: persistent SQLite
    from pygaeb.cache import SQLiteCache
    classifier = LLMClassifier(model="...", cache=SQLiteCache("~/.pygaeb/cache"))

    # Bring your own: any object implementing CacheBackend protocol
    classifier = LLMClassifier(model="...", cache=my_redis_cache)
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections import OrderedDict
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger("pygaeb.cache")


@runtime_checkable
class CacheBackend(Protocol):
    """Minimal key-value cache protocol. Implement this to bring your own backend."""

    def get(self, key: str) -> str | None:
        """Return the stored JSON string for key, or None on miss."""
        ...

    def put(self, key: str, value: str) -> None:
        """Store a JSON string under key."""
        ...

    def delete(self, key: str) -> None:
        """Remove a single key."""
        ...

    def clear(self) -> None:
        """Remove all entries."""
        ...

    def keys(self) -> list[str]:
        """Return all stored keys."""
        ...

    def close(self) -> None:
        """Release any resources (connections, file handles)."""
        ...


class InMemoryCache:
    """Default cache — LRU-bounded ``OrderedDict``, zero disk I/O.

    *maxsize* limits the number of entries.  When the limit is reached the
    least-recently-used entry is evicted.  Pass ``0`` to disable the limit.
    """

    def __init__(self, maxsize: int = 10_000) -> None:
        self._store: OrderedDict[str, str] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> str | None:
        value = self._store.get(key)
        if value is not None:
            self._store.move_to_end(key)
        return value

    def put(self, key: str, value: str) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if self._maxsize > 0 and len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def keys(self) -> list[str]:
        return list(self._store.keys())

    def close(self) -> None:
        pass

    def __len__(self) -> int:
        return len(self._store)


class SQLiteCache:
    """Opt-in persistent cache backed by SQLite. WAL mode for concurrent safety.

    Usage:
        cache = SQLiteCache("~/.pygaeb/cache")   # directory path
        cache = SQLiteCache("/tmp/my-cache")
    """

    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = Path(cache_dir).expanduser()
        self._cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._db_path = self._cache_dir / "pygaeb_cache.db"
        self._conn: sqlite3.Connection | None = None
        self._ensure_db()
        # Restrict DB file permissions — cache may contain business-sensitive data
        if self._db_path.exists():
            self._db_path.chmod(0o600)

    def _ensure_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv_cache "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def get(self, key: str) -> str | None:
        conn = self._get_conn()
        cursor = conn.execute("SELECT value FROM kv_cache WHERE key = ?", (key,))
        try:
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            cursor.close()

    def put(self, key: str, value: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO kv_cache (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()

    def delete(self, key: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
        conn.commit()

    def clear(self) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM kv_cache")
        conn.commit()

    def keys(self) -> list[str]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT key FROM kv_cache")
        try:
            return [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()

    def close(self) -> None:
        if self._conn:
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SQLiteCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    def __len__(self) -> int:
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM kv_cache")
        try:
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()
