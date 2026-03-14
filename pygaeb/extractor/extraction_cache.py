"""Extraction cache — domain wrapper over a pluggable CacheBackend."""

from __future__ import annotations

import json
import logging
from typing import Any

from pygaeb.cache import CacheBackend, InMemoryCache

logger = logging.getLogger("pygaeb.extractor")


class ExtractionCache:
    """Caches structured extraction results keyed by (item_hash + schema_hash).

    Wraps any CacheBackend (default: InMemoryCache — no disk I/O).
    """

    def __init__(self, backend: CacheBackend | None = None) -> None:
        self._backend = backend if backend is not None else InMemoryCache()

    def get(self, cache_key: str) -> tuple[dict[str, Any], float] | None:
        """Retrieve cached extraction. Returns (data_dict, completeness) or None."""
        raw = self._backend.get(f"ext:{cache_key}")
        if raw is None:
            return None
        entry = json.loads(raw)
        return entry["data"], entry["completeness"]

    def put(
        self,
        cache_key: str,
        schema_name: str,
        schema_hash: str,
        data: dict[str, Any],
        completeness: float,
    ) -> None:
        entry = {
            "schema_name": schema_name,
            "schema_hash": schema_hash,
            "data": data,
            "completeness": completeness,
        }
        self._backend.put(f"ext:{cache_key}", json.dumps(entry, default=str))

    def stats(self) -> list[dict]:
        """Aggregate counts by schema name and hash."""
        agg: dict[tuple[str, str], dict[str, Any]] = {}
        all_keys = self._backend.keys()
        for key in all_keys:
            if not key.startswith("ext:"):
                continue
            raw = self._backend.get(key)
            if raw is None:
                continue
            entry = json.loads(raw)
            group_key = (entry["schema_name"], entry["schema_hash"])
            if group_key not in agg:
                agg[group_key] = {"count": 0, "total_completeness": 0.0}
            agg[group_key]["count"] += 1
            agg[group_key]["total_completeness"] += entry["completeness"]

        return [
            {
                "schema_name": sn,
                "schema_hash": sh,
                "count": v["count"],
                "avg_completeness": round(v["total_completeness"] / v["count"], 2),
            }
            for (sn, sh), v in agg.items()
        ]

    def clear(self, schema_name: str | None = None) -> None:
        all_keys = self._backend.keys()
        if schema_name is None:
            for key in all_keys:
                if key.startswith("ext:"):
                    self._backend.delete(key)
        else:
            for key in all_keys:
                if not key.startswith("ext:"):
                    continue
                raw = self._backend.get(key)
                if raw:
                    entry = json.loads(raw)
                    if entry.get("schema_name") == schema_name:
                        self._backend.delete(key)

    def close(self) -> None:
        self._backend.close()
