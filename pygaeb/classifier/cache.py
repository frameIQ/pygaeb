"""Classification cache — domain wrapper over a pluggable CacheBackend."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from pygaeb.cache import CacheBackend, InMemoryCache
from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import ClassificationResult

logger = logging.getLogger("pygaeb.classifier")

#: How much of the long text the classification prompt sends.
LONG_TEXT_HEAD = 300


class ClassificationCache:
    """Caches classification results keyed by (input hash, config version).

    The classifier passes :func:`item_input_hash` and :func:`config_version`, so a
    result is reused only for the same item input under the same model, prompt
    and taxonomy. Manual overrides live under their own key (:meth:`save_override`).

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
        """Save the item's classification as a manual override.

        Stored apart from model results, keyed on the item's own input only, so it
        applies whichever model, prompt or taxonomy classifies the item later, and
        wins even when classification is forced.
        """
        from pygaeb.models.item import Item
        if not isinstance(item, Item) or item.classification is None:
            return
        override = item.classification.model_copy(
            update={"flag": ClassificationFlag.MANUAL_OVERRIDE},
        )
        data = override.model_dump(exclude={"cached"})
        data["_is_override"] = True
        self._backend.put(_override_key(item_input_hash(item)), json.dumps(data))

    def get_override(
        self,
        input_hash: str,
        legacy_hash: str | None = None,
        legacy_version: str | None = None,
    ) -> ClassificationResult | None:
        """The saved override for an item input, if any.

        *legacy_hash* and *legacy_version* find an override saved before overrides
        had their own key (``compute_hash`` of the texts, under a prompt version).
        """
        raw = self._backend.get(_override_key(input_hash))
        if raw is None and legacy_hash is not None and legacy_version is not None:
            raw = self._backend.get(_make_key(legacy_hash, legacy_version))
            if raw is not None and not json.loads(raw).get("_is_override", False):
                raw = None
        if raw is None:
            return None
        data = json.loads(raw)
        data.pop("_is_override", None)
        result = ClassificationResult(**data)
        result.cached = True
        return result

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


def _override_key(input_hash: str) -> str:
    return f"cls-override:{input_hash}"


def compute_hash(short_text: str, long_text_head: str) -> str:
    """SHA-256 hash of the two texts: the classification key up to pyGAEB 1.21.

    Still how overrides saved by those versions are found; new keys use
    :func:`item_input_hash`.
    """
    content = f"{short_text}\n{long_text_head}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def input_hash(hierarchy_path: str, short_text: str, long_text_head: str, unit: str) -> str:
    """SHA-256 of everything about an item that the classification prompt sends."""
    content = json.dumps([hierarchy_path, short_text, long_text_head, unit])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def item_input_hash(item: Any) -> str:
    """:func:`input_hash` of *item*, read the way the classifier reads it."""
    return input_hash(
        getattr(item, "hierarchy_path_str", "") or "",
        item.short_text,
        item.long_text_plain[:LONG_TEXT_HEAD],
        item.unit or "",
    )


def config_version(
    prompt_version: str,
    model: str,
    prompt: str,
    taxonomy: dict[str, dict[str, list[str]]] | None,
) -> str:
    """The version half of a result key: what the answer depends on besides the item.

    The prompt is the text actually sent, so re-registering a prompt version
    under new words does not serve answers to the old one.
    """
    content = json.dumps([model, prompt, taxonomy], sort_keys=True)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"{prompt_version}:{digest}"
