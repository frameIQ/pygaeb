"""Document handles and the parse cache.

Re-parsing a 50 MB tender on every tool call is untenable, so ``open_document``
parses once and returns a handle that later calls reuse.

Handles are **content-derived**: the key is a digest of the resolved path, mtime,
size, and validation mode. Two consequences fall out of that, and both are
deliberate:

* Re-opening an unchanged file returns the *same* handle with no re-parse, which
  makes ``open_document`` idempotent and lets it double as the summary tool.
* If the file changes on disk, the key changes, so a stale read is impossible.

There is no auto-rehydration of an evicted handle. A silent 50 MB re-parse
hidden inside ``get_item`` is exactly the invisible cost this design exists to
prevent; callers get an explicit error telling them to open the file again.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pygaeb.api.boq_tree import BoQTree
from pygaeb.config import get_settings
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ValidationMode

__all__ = ["CachedDocument", "DocumentCache"]


@dataclass
class CachedDocument:
    """A parsed document plus the derived structures the tools reuse."""

    handle: str
    path: Path
    doc: GAEBDocument
    size_mb: float
    summary: dict[str, Any] | None = None
    # Diff results keyed by the counterpart's handle. Safe to cache forever:
    # handles are content-derived, so the same pair always means the same bytes.
    diffs: dict[str, Any] = field(default_factory=dict, repr=False)
    _tree: BoQTree | None = field(default=None, repr=False)

    @property
    def tree(self) -> BoQTree:
        """The BoQ tree, built on first use then reused.

        Gates on ``is_procurement`` rather than on ``award.boq`` being absent:
        ``AwardInfo.boq`` has a ``default_factory``, so on a trade/cost/quantity
        document it is an *empty* ``BoQ``, never ``None``.

        Raises:
            ValueError: If the document is not a procurement document.
        """
        if self._tree is None:
            if not self.doc.is_procurement:
                # Neutral wording: this path is reachable from list_items itself
                # (via its category filter), so "use list_items" would be
                # self-referential advice there.
                raise ValueError(
                    f"Document {self.handle} is a {self.doc.document_kind.value} document "
                    f"and has no bill-of-quantities structure. Structure navigation, "
                    f"category filters, and OZ lookup require a procurement "
                    f"document (X80-X89)."
                )
            self._tree = BoQTree(self.doc.award.boq)
        return self._tree


class DocumentCache:
    """LRU cache of parsed documents, bounded by both count and total megabytes.

    Under the default stdio transport the cache lives for exactly one client
    session, which is why it needs no cross-session namespacing.
    """

    def __init__(
        self,
        max_documents: int | None = None,
        max_cache_mb: int | None = None,
    ) -> None:
        settings = get_settings()
        self.max_documents = (
            max_documents if max_documents is not None else settings.mcp_max_open_documents
        )
        self.max_cache_mb = (
            max_cache_mb if max_cache_mb is not None else settings.mcp_max_cache_mb
        )
        self._entries: OrderedDict[str, CachedDocument] = OrderedDict()
        # Handle -> path, kept after eviction so the error can name the file.
        self._known: OrderedDict[str, str] = OrderedDict()

    # ── Handle derivation ──────────────────────────────────────────────

    @staticmethod
    def derive_handle(path: Path, validation: ValidationMode) -> str:
        """Derive the deterministic handle for *path* in its current state."""
        stat = path.stat()
        payload = f"{path}|{stat.st_mtime_ns}|{stat.st_size}|{validation.value}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"doc_{digest}"

    # ── Access ─────────────────────────────────────────────────────────

    def get(self, handle: str) -> CachedDocument:
        """Fetch a cached document, refreshing its LRU position.

        Raises:
            ValueError: If the handle is unknown or has been evicted.
        """
        entry = self._entries.get(handle)
        if entry is None:
            known_path = self._known.get(handle)
            hint = f" (was {known_path})" if known_path else ""
            raise ValueError(
                f"Unknown or expired handle {handle!r}{hint}. Call open_document again."
            )
        self._entries.move_to_end(handle)
        return entry

    def peek(self, handle: str) -> CachedDocument | None:
        """Fetch without raising and without touching the LRU order."""
        return self._entries.get(handle)

    def get_if_present(self, handle: str) -> CachedDocument | None:
        """Fetch without raising, refreshing the LRU position on a hit.

        This is what serving paths should use: a document kept hot purely via
        repeated ``open_document`` calls must count as recently used, or the
        cheap cached path would make it the eviction candidate.
        """
        entry = self._entries.get(handle)
        if entry is not None:
            self._entries.move_to_end(handle)
        return entry

    def put(self, handle: str, path: Path, doc: GAEBDocument) -> CachedDocument:
        """Insert a freshly parsed document and evict if over budget."""
        entry = CachedDocument(
            handle=handle,
            path=path,
            doc=doc,
            size_mb=doc.memory_estimate_mb,
        )
        self._entries[handle] = entry
        self._entries.move_to_end(handle)
        self._known[handle] = str(path)
        while len(self._known) > 256:
            self._known.popitem(last=False)
        self._evict()
        return entry

    # ── Eviction ───────────────────────────────────────────────────────

    def _total_mb(self) -> float:
        return sum(e.size_mb for e in self._entries.values())

    def _evict(self) -> None:
        """Drop least-recently-used entries until both budgets are satisfied.

        The newest entry is never evicted; a single document larger than the MB
        budget is kept rather than parsed and immediately thrown away.
        """
        while len(self._entries) > self.max_documents:
            self._entries.popitem(last=False)
        while len(self._entries) > 1 and self._total_mb() > self.max_cache_mb:
            self._entries.popitem(last=False)

    # ── Introspection ──────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, handle: object) -> bool:
        return handle in self._entries

    def stats(self) -> dict[str, Any]:
        """Current occupancy — used by tests and troubleshooting."""
        return {
            "open_documents": len(self._entries),
            "total_mb": round(self._total_mb(), 2),
            "max_documents": self.max_documents,
            "max_cache_mb": self.max_cache_mb,
        }

    def clear(self) -> None:
        """Drop everything."""
        self._entries.clear()
        self._known.clear()
