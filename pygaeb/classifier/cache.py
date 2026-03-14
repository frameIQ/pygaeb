"""Classification cache — domain wrapper over a pluggable CacheBackend."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from pygaeb.cache import CacheBackend, InMemoryCache
from pygaeb.models.item import ClassificationResult

logger = logging.getLogger("pygaeb.classifier")


class ClassificationCache:
    """Caches classification results keyed by (text_hash, prompt_version).

    Wraps any CacheBackend (default: InMemoryCache — no disk I/O).
    """

    def __init__(self, backend: CacheBackend | None = None) -> None:
        self._backend = backend if backend is not None else InMemoryCache()

    def get(
        self, text_hash: str, prompt_version: str
    ) -> ClassificationResult | None:
        key = _make_key(text_hash, prompt_version)
        raw = self._backend.get(key)
        if raw is None:
            return None
        result = ClassificationResult(**json.loads(raw))
        result.cached = True
        return result

    def put(
        self,
        text_hash: str,
        prompt_version: str,
        result: ClassificationResult,
        is_override: bool = False,
    ) -> None:
        key = _make_key(text_hash, prompt_version)
        data = result.model_dump(exclude={"cached"})
        data["_is_override"] = is_override
        self._backend.put(key, json.dumps(data))

    def save_override(self, item: object) -> None:
        """Save a manual override for an item."""
        from pygaeb.models.item import Item
        if not isinstance(item, Item) or item.classification is None:
            return
        text_hash = compute_hash(item.short_text, item.long_text_plain[:300])
        self.put(
            text_hash,
            item.classification.prompt_version,
            item.classification,
            is_override=True,
        )

    def stats(self) -> list[dict[str, Any]]:
        """Aggregate counts by prompt version."""
        counts: dict[str, dict[str, int]] = {}
        for key in self._backend.keys():  # noqa: SIM118
            raw = self._backend.get(key)
            if raw is None:
                continue
            data = json.loads(raw)
            pv = data.get("prompt_version", "unknown")
            is_override = data.get("_is_override", False)
            if pv not in counts:
                counts[pv] = {"count": 0, "overrides": 0}
            counts[pv]["count"] += 1
            if is_override:
                counts[pv]["overrides"] += 1
        return [
            {"prompt_version": pv, "count": v["count"], "overrides": v["overrides"]}
            for pv, v in counts.items()
        ]

    def clear(self) -> None:
        """Remove all non-override entries."""
        to_remove: list[str] = []
        for key in self._backend.keys():  # noqa: SIM118
            raw = self._backend.get(key)
            if raw:
                data = json.loads(raw)
                if not data.get("_is_override", False):
                    to_remove.append(key)
        for key in to_remove:
            self._backend.delete(key)

    def close(self) -> None:
        self._backend.close()


def _make_key(text_hash: str, prompt_version: str) -> str:
    return f"cls:{text_hash}:{prompt_version}"


def compute_hash(short_text: str, long_text_head: str) -> str:
    """SHA-256 hash of the classification input text."""
    content = f"{short_text}\n{long_text_head}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
