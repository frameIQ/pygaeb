"""The MCP tool surface, as plain Python.

Nothing here imports the MCP SDK. Each tool is an ordinary function whose
signature *is* its JSON schema — ``FastMCP.add_tool`` derives the schema from the
type hints, the description from the docstring, and per-parameter descriptions
and bounds from ``Annotated[..., Field(...)]``. Keeping this module SDK-free is
what lets the whole surface be unit-tested without a server.

Tools are built as closures over a :class:`ToolContext` so that the cache and
roots are captured without appearing as tool parameters.

The SDK calls sync tool functions directly on the asyncio event loop (verified
against mcp 1.28: ``func_metadata.call_fn_with_arg_validation`` has no thread
hop). A tool that parses, diffs, or scans a large document would therefore stall
heartbeats, cancellation, and — over HTTP — every other session. So the heavy
tools are ``async`` and run their expensive part in a worker thread via
``asyncio.to_thread`` (stdlib; same pattern as :mod:`pygaeb.async_api`), while
cache mutations stay on the event loop, which keeps the single-threaded
``DocumentCache`` safe. The cheap, cached-lookup tools stay sync on purpose:
``async def`` without an await point buys nothing.

Every docstring here is read by a language model as the tool's description.
Write them for the model first and the human second.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from pygaeb.api.boq_tree import BoQNode, NodeKind
from pygaeb.mcp import views
from pygaeb.mcp.handles import DocumentCache
from pygaeb.mcp.safety import is_gaeb_suffix, resolve_output_path, resolve_within_roots
from pygaeb.models.enums import ValidationMode

__all__ = ["ToolContext", "build_tools"]

Sort = Literal["oz", "total_desc", "qty_desc"]
Severity = Literal["ERROR", "WARNING", "INFO"]

# A root like a home directory can hold millions of files; stop walking once
# this many GAEB files are found and say so, rather than scanning forever.
MAX_LISTED_DOCUMENTS = 5_000

# A tool is either sync (cheap, cached lookups) or async (heavy work in a
# worker thread) — see the module docstring for which is which and why.
ToolFn = Callable[..., "dict[str, Any] | Coroutine[Any, Any, dict[str, Any]]"]


@dataclass
class ToolContext:
    """Everything the tools need that must not appear in their schemas."""

    cache: DocumentCache
    roots: list[Path]
    allow_any_extension: bool = False
    allow_write: bool = False
    output_dir: Path | None = None


def _to_decimal(value: float | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Not a number: {value!r}") from None
    # NaN would poison every Decimal comparison downstream with a raw
    # InvalidOperation; reject it (and infinities) as input instead.
    if not result.is_finite():
        raise ValueError(f"Not a finite number: {value!r}")
    return result


def _one_item(tree: Any, oz: str, handle: str, item_id: str | None = None) -> BoQNode:
    """Resolve an OZ (or an XML id) to exactly one item, refusing to guess.

    A leaf shared across categories and a full OZ a file genuinely repeats both
    raise, listing the candidates with their ids so the caller can pick one.
    """
    nodes: list[BoQNode] = tree.find_items(oz)
    if item_id and item_id.startswith("#"):
        # "#2" = the second copy in document order, for files that carry no ids.
        ordinal = item_id[1:]
        if not ordinal.isdigit() or not 1 <= int(ordinal) <= len(nodes):
            raise ValueError(f"OZ {oz!r} has {len(nodes)} copies in {handle}; got {item_id!r}.")
        return nodes[int(ordinal) - 1]
    if item_id:
        by_id: BoQNode | None = tree.find_item_by_id(item_id)
        if by_id is None:
            raise ValueError(f"No item with id {item_id!r} in {handle}.")
        return by_id
    if not nodes:
        raise ValueError(f"No item with OZ {oz!r} in {handle}.")
    if len(nodes) > 1:
        candidates = "; ".join(
            f"{n.oz} (item_id={n.item.id or f'#{i}'}) {n.item.short_text or ''}".strip()
            for i, n in enumerate(nodes, start=1)
        )
        hint = "Pass the full OZ." if len({n.oz for n in nodes}) > 1 else "Pass item_id."
        raise ValueError(f"OZ {oz!r} is ambiguous in {handle}: {candidates}. {hint}")
    return nodes[0]


_STRUCTURE_DETAIL_CAP = 20


def _structure_detail(structure: Any) -> dict[str, Any]:
    """The section-level changes, each list capped so a reorganised tender stays readable."""
    payload: dict[str, Any] = {}
    for name in ("sections_added", "sections_removed", "sections_renamed", "items_moved"):
        rows = list(getattr(structure, name, []) or [])
        payload[name] = [views.section_change(r) for r in rows[:_STRUCTURE_DETAIL_CAP]]
        if len(rows) > _STRUCTURE_DETAIL_CAP:
            payload[f"{name}_truncated"] = True
    return payload


def _digest(path: Path) -> str:
    """Short SHA-256 of the file bytes — equal digests mean identical files."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def _priced_rows(items: list[Any]) -> list[tuple[Any, Decimal]]:
    """Each item that has a stated or computed total, paired with it."""
    rows: list[tuple[Any, Decimal]] = []
    for item in items:
        total = views.effective_total(item)
        if total is not None:
            rows.append((item, total))
    return rows


def _affects_total(item: Any) -> bool:
    """Whether an item's price counts toward the document total (VOB/A).

    Alternative and eventual positions carry prices but are not part of the
    contract value — the library's own ``grand_total`` excludes them via
    ``ItemType.affects_total``, and any sum this server reports must follow the
    same convention. Item kinds without an ``item_type`` (trade/cost/quantity)
    count as-is.
    """
    item_type = getattr(item, "item_type", None)
    return item_type is None or bool(item_type.affects_total)


def build_tools(ctx: ToolContext) -> list[ToolFn]:
    """Build the tool callables bound to *ctx*.

    Returns the 10 read tools, plus the 2 write tools when ``ctx.allow_write``.
    """

    # ── list_documents ─────────────────────────────────────────────────

    async def list_documents(
        name_contains: Annotated[
            str | None, Field(description="Case-insensitive substring of the file name.")
        ] = None,
        limit: Annotated[int, Field(description="Max files to return.", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Files to skip.", ge=0)] = 0,
        with_digest: Annotated[
            bool,
            Field(description="Add content_sha256 per listed file (reads each file on the page)."),
        ] = False,
    ) -> dict[str, Any]:
        """List the GAEB files the server is allowed to open.

        Call this when you do not know the exact file name or path. Each row's
        `path` can be passed straight to `open_document`. Every allowed root is
        scanned recursively (hidden directories skipped); only files with a GAEB
        extension are listed unless the server allows any extension.

        To find out whether files are copies of each other, ask for `with_digest`:
        equal `content_sha256` means identical bytes, whatever the name or date —
        no need to open and compare them.
        """
        needle = name_contains.lower() if name_contains else None

        def _scan() -> tuple[list[dict[str, Any]], bool]:
            found: list[dict[str, Any]] = []
            for root in ctx.roots:
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                    for name in sorted(filenames):
                        if name.startswith("."):
                            continue
                        if not ctx.allow_any_extension and not is_gaeb_suffix(Path(name).suffix):
                            continue
                        if needle is not None and needle not in name.lower():
                            continue
                        file = Path(dirpath) / name
                        # A symlink out of the root would be refused by open_document anyway.
                        if file.is_symlink():
                            continue
                        try:
                            stat = file.stat()
                        except OSError:
                            continue
                        found.append(
                            {
                                "path": str(file),
                                "name": name,
                                "root": str(root),
                                "size_bytes": stat.st_size,
                                "modified": datetime.fromtimestamp(
                                    stat.st_mtime, tz=timezone.utc
                                ).isoformat(timespec="seconds"),
                            }
                        )
                        if len(found) >= MAX_LISTED_DOCUMENTS:
                            return found, True
            return found, False

        # Walking a large tree is blocking I/O; keep it off the event loop.
        files, scan_truncated = await asyncio.to_thread(_scan)
        page, total, has_more = views.paginate(files, offset, limit)
        if with_digest:
            # Only the page is hashed, so the cost is bounded by `limit`, not the scan.
            def _hash_page() -> None:
                for row in page:
                    try:
                        row["content_sha256"] = _digest(Path(row["path"]))
                    except OSError:
                        row["content_sha256"] = None

            await asyncio.to_thread(_hash_page)
        return views.bound(
            {
                "roots": [str(r) for r in ctx.roots],
                "files": page,
                "total_matched": total,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "scan_truncated": scan_truncated,
            }
        )

    # ── open_document ──────────────────────────────────────────────────

    async def open_document(
        path: Annotated[str, Field(description="Path to a GAEB file (.X83, .D83, .P83, …).")],
        validation: Annotated[
            Literal["lenient", "strict"],
            Field(description="'lenient' collects issues; 'strict' fails on the first error."),
        ] = "lenient",
    ) -> dict[str, Any]:
        """Open a GAEB file and return a handle plus a summary of the document.

        Call this first. The returned `handle` is required by every other tool.
        Re-opening an unchanged file is free and returns the same handle. A bare
        file name is looked up under the allowed roots; use `list_documents` if
        you do not know the name.

        The summary is deliberately small — totals, counts, project metadata, and
        quality scores. To see the contents, drill down with `list_structure` and
        `list_items`; do not expect this to return the items themselves. On an
        unpriced tender (an X83 before bids) `is_priced` is false and the totals
        are null, not zero.
        """
        mode = ValidationMode.STRICT if validation == "strict" else ValidationMode.LENIENT
        resolved = resolve_within_roots(
            path, ctx.roots, allow_any_extension=ctx.allow_any_extension
        )
        handle = DocumentCache.derive_handle(resolved, mode)

        # get_if_present (not peek) so a repeatedly re-opened document counts as
        # recently used and is not the LRU eviction candidate.
        entry = ctx.cache.get_if_present(handle)
        if entry is not None:
            assert entry.summary is not None
            return {**entry.summary, "cached": True}

        def _load() -> tuple[Any, dict[str, Any]]:
            from pygaeb.parser.gaeb_parser import GAEBParser

            doc = GAEBParser.parse(str(resolved), validation=mode)
            doc.discard_xml()
            summary = views.document_summary(
                doc, handle, str(resolved), cached=False, content_sha256=_digest(resolved)
            )
            return doc, summary

        # Parse in a worker thread so a large file cannot stall the event loop.
        # Two concurrent opens of the same unchanged file may both parse and the
        # second put wins — identical content, so wasted work, not corruption.
        doc, summary = await asyncio.to_thread(_load)
        entry = ctx.cache.put(handle, resolved, doc)
        entry.summary = summary
        return summary

    # ── list_structure ─────────────────────────────────────────────────

    def list_structure(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        rno: Annotated[
            str | None,
            Field(description="Category/lot number to expand. Omit for the top level."),
        ] = None,
        limit: Annotated[int, Field(description="Max nodes to return.", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Nodes to skip.", ge=0)] = 0,
    ) -> dict[str, Any]:
        """List the direct children of a level of the bill of quantities.

        Each node reports `item_count` and `subtotal`, so you can find the
        expensive part of a large tender by expanding one level at a time rather
        than listing every item. Pass a node's `rno` back in to go deeper.

        Procurement documents only.
        """
        entry = ctx.cache.get(handle)
        tree = entry.tree

        parent: BoQNode
        if rno is None:
            parent = tree.root
        else:
            found = tree.find_category(rno)
            if found is None:
                found = next((n for n in tree.lots if n.rno == rno), None)
            if found is None:
                raise ValueError(f"No category or lot with rno {rno!r} in {handle}.")
            parent = found

        children = list(parent.children)
        # A lot-less file gets a placeholder lot from the parser; show its
        # categories directly rather than a "Default" lot the file never had.
        if (
            parent.kind == NodeKind.ROOT
            and len(children) == 1
            and getattr(children[0].lot, "synthetic", False)
        ):
            children = list(children[0].children)
        page, total, has_more = views.paginate(children, offset, limit)
        return views.bound(
            {
                "parent": {
                    "rno": parent.rno,
                    "label": parent.label,
                    "kind": parent.kind.value,
                    "label_path": parent.label_path,
                },
                "nodes": [views.structure_node(n) for n in page],
                "total_matched": total,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
            }
        )

    # ── list_items ─────────────────────────────────────────────────────

    def list_items(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        category: Annotated[
            str | None, Field(description="Restrict to this category rno (procurement only).")
        ] = None,
        text_contains: Annotated[
            str | None, Field(description="Case-insensitive substring of the short text.")
        ] = None,
        min_total: Annotated[
            float | None,
            Field(description="Only items whose total (stated, else qty x unit price) >= this."),
        ] = None,
        max_total: Annotated[
            float | None,
            Field(description="Only items whose total (stated, else qty x unit price) <= this."),
        ] = None,
        has_attachments: Annotated[
            bool | None, Field(description="Filter on presence of attachments.")
        ] = None,
        sort: Annotated[
            Sort,
            Field(
                description="'oz' = document order; 'total_desc' surfaces cost drivers "
                "first; 'qty_desc' the largest quantities first."
            ),
        ] = "oz",
        limit: Annotated[int, Field(description="Max items to return.", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Items to skip.", ge=0)] = 0,
    ) -> dict[str, Any]:
        """List items, filtered and sorted, without their specification text.

        Returns a compact row per item. Long text and attachments are summarised
        as counts only — use `get_item` for one item's detail, or
        `get_item_long_text` for its full prose.

        For "what are the biggest cost drivers?", use sort='total_desc' with a
        small limit; do not page through every item.

        Totals are the stated `total_price`, falling back to `computed_total`
        (qty x unit price) — bids often carry unit prices only.
        `sum_of_matched_totals` follows VOB/A: alternative and eventual positions
        are excluded (each row's `affects_total` says whether it counted). On an
        unpriced tender (e.g. an X83 before bids), totals are null, not zero —
        price filters and total-based sorting are meaningless there.
        """
        entry = ctx.cache.get(handle)

        if category is not None:
            node = entry.tree.find_category(category)
            if node is None:
                raise ValueError(f"No category with rno {category!r} in {handle}.")
            items: list[Any] = [n.item for n in node.iter_items()]
        else:
            items = list(entry.doc.iter_items())

        lo = _to_decimal(min_total)
        hi = _to_decimal(max_total)
        needle = text_contains.lower() if text_contains else None

        def keep(item: Any) -> bool:
            if needle is not None and needle not in (getattr(item, "short_text", "") or "").lower():
                return False
            total = views.effective_total(item)
            if lo is not None and (total is None or total < lo):
                return False
            if hi is not None and (total is None or total > hi):
                return False
            if has_attachments is not None:
                present = bool(getattr(item, "attachments", None))
                if present is not has_attachments:
                    return False
            return True

        matched = [i for i in items if keep(i)]

        if sort == "total_desc":
            matched.sort(key=lambda i: views.effective_total(i) or Decimal(0), reverse=True)
        elif sort == "qty_desc":
            matched.sort(key=lambda i: getattr(i, "qty", None) or Decimal(0), reverse=True)

        priced = _priced_rows(matched)
        sum_matched: Decimal | None = None
        pct: float | None = None
        if priced:
            sum_matched = sum((t for i, t in priced if _affects_total(i)), Decimal(0))
            grand = views.effective_grand_total(entry.doc) if entry.doc.is_procurement else None
            pct = float(sum_matched / grand * 100) if grand else None

        page, total, has_more = views.paginate(matched, offset, limit)
        return views.bound(
            {
                "items": [views.item_row(i) for i in page],
                "total_matched": total,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                # Null when nothing matched carries a price (an unpriced X83).
                "sum_of_matched_totals": str(sum_matched) if sum_matched is not None else None,
                "pct_of_grand_total": round(pct, 2) if pct is not None else None,
            }
        )

    # ── get_item ───────────────────────────────────────────────────────

    def get_item(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        oz: Annotated[
            str, Field(description="Ordinal number — leaf ('0040') or full ('01.02.0040').")
        ],
        item_id: Annotated[
            str | None,
            Field(
                description="When a file repeats an OZ: the item's XML id (see list_items "
                "rows), or '#2' for the second copy in document order."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Get one item's full detail, with its specification text previewed.

        `long_text_preview` is the first 500 characters; `long_text_chars` is the
        true length. Fetch the rest with `get_item_long_text` only if you need it.
        Attachments are listed as metadata — their contents are never returned.

        A leaf shared by several categories, or a full OZ the file repeats, is
        refused with the candidates listed — pass the full OZ or `item_id`. For
        a markup item (Zuschlagsposition) the `markup` block carries the rate and
        what it applies to; its prices are null because the rate is not a price.
        """
        entry = ctx.cache.get(handle)
        node = _one_item(entry.tree, oz, handle, item_id)
        return views.item_detail(node.item, node)

    # ── get_item_long_text ─────────────────────────────────────────────

    def get_item_long_text(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        oz: Annotated[str, Field(description="Ordinal number of the item.")],
        offset: Annotated[int, Field(description="Character offset to start at.", ge=0)] = 0,
        limit: Annotated[
            int, Field(description="Characters to return.", ge=1, le=20_000)
        ] = 4_000,
        item_id: Annotated[
            str | None,
            Field(
                description="When a file repeats an OZ: the item's XML id (see list_items "
                "rows), or '#2' for the second copy in document order."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read an item's full specification text, one window at a time.

        Specification prose can run to tens of thousands of characters. Read only
        the window you need and stop when you have the answer — `has_more` tells
        you whether more remains. `limit` may be reduced to fit the response
        budget; the `limit` in the response is the window actually used.
        """
        entry = ctx.cache.get(handle)
        node = _one_item(entry.tree, oz, handle, item_id)
        item = node.item
        text = item.long_text_plain
        effective = min(limit, views.max_text_window())
        window = text[offset : offset + effective]
        return views.bound(
            {
                "oz": item.full_oz or item.oz,
                "text": window,
                "offset": offset,
                "limit": effective,
                "total_chars": len(text),
                "has_more": offset + len(window) < len(text),
                "tables_count": len(item.long_text.tables) if item.long_text else 0,
                "images_count": len(item.long_text.images) if item.long_text else 0,
            }
        )

    # ── search_items ───────────────────────────────────────────────────

    async def search_items(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        query: Annotated[str, Field(description="Case-insensitive text to find.", min_length=1)],
        search_long_text: Annotated[
            bool, Field(description="Also search the full specification prose.")
        ] = True,
        whole_word: Annotated[
            bool,
            Field(description="Match whole words only, so 'U' does not hit 'und'."),
        ] = False,
        limit: Annotated[int, Field(description="Max matches.", ge=1, le=200)] = 25,
        offset: Annotated[int, Field(description="Matches to skip.", ge=0)] = 0,
    ) -> dict[str, Any]:
        """Find items whose text mentions something, returning short snippets.

        Returns a context window around each hit rather than the whole field, so
        searching megabytes of specification prose stays cheap. Use this to locate
        a clause; use `get_item_long_text` to read around it. Each match says
        which `field` matched: the item's `oz`, its `short_text`, the label of an
        enclosing `category`, or its `long_text`. Short queries ("U", "EN") match
        inside ordinary words — set `whole_word` for those.
        """
        entry = ctx.cache.get(handle)
        tree = entry.tree if entry.doc.is_procurement else None

        def _scan() -> list[dict[str, Any]]:
            found: list[dict[str, Any]] = []
            nodes: list[Any] = list(tree.root.iter_items()) if tree else []
            items: list[tuple[Any, Any]] = (
                [(n.item, n) for n in nodes]
                if nodes
                else [(i, None) for i in entry.doc.iter_items()]
            )
            for item, node in items:
                oz = getattr(item, "full_oz", None) or getattr(item, "oz", "") or ""
                if views.find_matches(oz, query, whole_word):
                    found.append({"oz": oz, "field": "oz", "snippet": oz, "match_count": 1})
                    continue
                short_text = getattr(item, "short_text", "") or ""
                snip, count = views.snippet(short_text, query, whole_word=whole_word)
                if count:
                    found.append(
                        {"oz": oz, "field": "short_text", "snippet": snip, "match_count": count}
                    )
                    continue
                if node is not None:
                    labels = [
                        n.label for n in node.path if n.kind == NodeKind.CATEGORY
                    ]
                    hit = next(
                        (lbl for lbl in labels if views.find_matches(lbl, query, whole_word)),
                        None,
                    )
                    if hit is not None:
                        snip, count = views.snippet(hit, query, whole_word=whole_word)
                        found.append(
                            {"oz": oz, "field": "category", "snippet": snip, "match_count": count}
                        )
                        continue
                if search_long_text:
                    snip, count = views.snippet(
                        getattr(item, "long_text_plain", "") or "", query, whole_word=whole_word
                    )
                    if count:
                        found.append(
                            {"oz": oz, "field": "long_text", "snippet": snip, "match_count": count}
                        )
            return found

        # Scanning every item's prose is the heaviest in-memory operation the
        # server does; keep it off the event loop.
        matches = await asyncio.to_thread(_scan)

        page, total, has_more = views.paginate(matches, offset, limit)
        return views.bound(
            {
                "query": query,
                "matches": page,
                "total_matched": total,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
            }
        )

    # ── list_validation_issues ─────────────────────────────────────────

    def list_validation_issues(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        severity: Annotated[
            Severity | None, Field(description="Restrict to one severity.")
        ] = None,
        limit: Annotated[int, Field(description="Max issues.", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Issues to skip.", ge=0)] = 0,
    ) -> dict[str, Any]:
        """List validation problems found while parsing.

        `counts` is always complete, so check it before paging — a file with 4000
        warnings rarely needs all of them read.
        """
        entry = ctx.cache.get(handle)
        issues = list(entry.doc.validation_results)

        counts = {"error": 0, "warning": 0, "info": 0}
        for issue in issues:
            key = issue.severity.value.lower()
            if key in counts:
                counts[key] += 1

        if severity is not None:
            issues = [i for i in issues if i.severity.value.upper() == severity]

        page, total, has_more = views.paginate(issues, offset, limit)
        return views.bound(
            {
                "counts": counts,
                "issues": [views.validation_issue(i) for i in page],
                "total_matched": total,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
            }
        )

    # ── compare_documents ──────────────────────────────────────────────

    async def compare_documents(
        handle_a: Annotated[str, Field(description="Handle of the earlier document.")],
        handle_b: Annotated[str, Field(description="Handle of the later document.")],
        min_significance: Annotated[
            Literal["low", "medium", "high", "critical"],
            Field(description="Drop changes below this significance."),
        ] = "low",
        limit: Annotated[int, Field(description="Max changes.", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Changes to skip.", ge=0)] = 0,
    ) -> dict[str, Any]:
        """Compare two procurement documents and list what changed.

        Returns counts plus a significance-sorted, paginated stream of item
        changes. `structure` lists the sections added, removed or renamed and
        the items that moved (first 20 of each). Items are matched by their
        full OZ within a lot, so `summary.is_likely_same_project` and a low
        `match_ratio` tell you when two files are unrelated. Paging through the
        changes is cheap: the diff is computed once per document pair.
        """
        from pygaeb.diff.boq_diff import BoQDiff
        from pygaeb.diff.models import DiffResult, Significance

        entry_a = ctx.cache.get(handle_a)
        entry_b = ctx.cache.get(handle_b)

        # Handles are content-derived, so a cached diff can never go stale:
        # the same handle pair always names the same two byte-identical files.
        result: DiffResult | None = entry_a.diffs.get(handle_b)
        if result is None:
            try:
                result = await asyncio.to_thread(BoQDiff.compare, entry_a.doc, entry_b.doc)
            except TypeError:
                kinds = f"{entry_a.doc.document_kind.value} / {entry_b.doc.document_kind.value}"
                raise ValueError(
                    f"compare_documents needs two procurement documents; got {kinds}."
                ) from None
            entry_a.diffs[handle_b] = result

        order = ["low", "medium", "high", "critical"]
        floor = order.index(min_significance)

        def sig_rank(s: Significance) -> int:
            return order.index(s.value.lower()) if s.value.lower() in order else 0

        changes: list[dict[str, Any]] = []
        for added in result.items.added:
            changes.append(
                {
                    "kind": "added",
                    "oz": added.oz,
                    "short_text": added.short_text[: views.SHORT_TEXT_CHARS],
                    "total_price": str(added.total_price) if added.total_price else None,
                    "_rank": len(order) - 1,
                }
            )
        for removed in result.items.removed:
            changes.append(
                {
                    "kind": "removed",
                    "oz": removed.oz,
                    "short_text": removed.short_text[: views.SHORT_TEXT_CHARS],
                    "total_price": str(removed.total_price) if removed.total_price else None,
                    "_rank": len(order) - 1,
                }
            )
        for mod in result.items.modified:
            kept = [c for c in mod.changes if sig_rank(c.significance) >= floor]
            if not kept:
                continue
            entry_changes = [
                {
                    "field": c.field,
                    "old": str(c.old_value) if c.old_value is not None else None,
                    "new": str(c.new_value) if c.new_value is not None else None,
                    "significance": c.significance.value,
                }
                for c in kept[:10]
            ]
            row: dict[str, Any] = {
                "kind": "modified",
                "oz": mod.oz,
                "short_text": mod.short_text_b[: views.SHORT_TEXT_CHARS],
                "changes": entry_changes,
                "_rank": max(sig_rank(c.significance) for c in kept),
            }
            if len(kept) > 10:
                row["changes_truncated"] = True
            changes.append(row)

        changes.sort(key=lambda c: c["_rank"], reverse=True)
        for c in changes:
            c.pop("_rank", None)

        page, total, has_more = views.paginate(changes, offset, limit)
        s = result.summary
        return views.bound(
            {
                "summary": {
                    "has_changes": s.has_changes,
                    "total_changes": s.total_changes,
                    "match_ratio": round(s.match_ratio, 3),
                    "is_likely_same_project": s.is_likely_same_project,
                    "financial_impact": str(s.financial_impact) if s.financial_impact else None,
                    "max_significance": s.max_significance.value,
                    # OZs a file repeats: only the first copy was compared.
                    "duplicates_collapsed": [d.model_dump() for d in s.duplicates_collapsed],
                },
                "counts": {
                    "added": len(result.items.added),
                    "removed": len(result.items.removed),
                    "modified": len(result.items.modified),
                    "unchanged": result.items.unchanged_count,
                    "moved": len(result.structure.items_moved),
                    "sections_added": len(result.structure.sections_added),
                    "sections_removed": len(result.structure.sections_removed),
                    "sections_renamed": len(result.structure.sections_renamed),
                },
                "structure": _structure_detail(result.structure),
                "changes": page,
                "total_matched": total,
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "warnings": result.warnings[:20],
            }
        )

    # ── analyze_bids ───────────────────────────────────────────────────

    async def analyze_bids(
        tender_handle: Annotated[str, Field(description="Handle of the tender (X83), or an X82.")],
        bids: Annotated[
            list[dict[str, str]] | None,
            Field(description="[{'name': 'Bidder A', 'handle': 'doc_…'}]. Omit for an X82."),
        ] = None,
        spread_for: Annotated[
            list[str] | None,
            Field(
                description="Full OZs ('01.02.0010') to report min/max/avg unit-price "
                "spread for (max 25). A bare leaf works when only one position has it."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Rank bidders and report price spreads.

        Pass X84 bid handles alongside the tender, or omit `bids` for an X82
        Preisspiegel that already carries every bidder's prices.

        `grand_total` sums each bidder's stated item totals, falling back to
        qty x unit price, over the positions that count toward the contract. A
        bidder with no priced item gets a null total and rank — a missing bid is
        not a zero bid. `spreads` covers the OZs found; `spread_unmatched` and
        `spread_ambiguous` say why the rest are absent. `items_priced_by_all_count`
        is a count, not a list — use `list_items` if you need the items themselves.
        """
        from pygaeb.bid_analysis import BidAnalysis

        # Cache lookups happen on the event loop (they mutate LRU order); only
        # the item-scanning analysis moves to a worker thread.
        entry = ctx.cache.get(tender_handle)
        mapping: dict[str, Any] | None = None
        if bids:
            mapping = {}
            for bid in bids:
                name, bid_handle = bid.get("name"), bid.get("handle")
                if not name or not bid_handle:
                    raise ValueError("Each bid needs both 'name' and 'handle'.")
                mapping[name] = ctx.cache.get(bid_handle).doc

        def _analyze() -> dict[str, Any]:
            if mapping is not None:
                analysis = BidAnalysis.from_x84_bids(entry.doc, mapping)
            else:
                analysis = BidAnalysis.from_x82(entry.doc)

            ranking = []
            for i, (name, total) in enumerate(analysis.ranking()):
                priced = analysis.priced_item_count(name)
                ranking.append(
                    {
                        "bidder": name,
                        "grand_total": str(total) if priced else None,
                        "rank": i + 1 if priced else None,
                        "priced_items": priced,
                    }
                )

            spreads: dict[str, Any] = {}
            unmatched: list[str] = []
            ambiguous: dict[str, list[str]] = {}
            for oz in (spread_for or [])[:25]:
                try:
                    spread = analysis.price_spread(oz)
                except ValueError as exc:
                    # "ambiguous OZ '0010': 01.0010, 02.0010"
                    ambiguous[oz] = str(exc).split(": ", 1)[-1].split(", ")
                    continue
                if spread is None:
                    unmatched.append(oz)
                    continue
                # Decimals stringify for lossless JSON; counts stay ints.
                spreads[oz] = {
                    k: (str(v) if isinstance(v, Decimal) else v) for k, v in spread.items()
                }

            # OZs a bid repeats: only the first copy is priced, so totals may be short.
            collapsed = {
                name: [{"oz": oz, "count": n} for oz, n in sorted(dups.items())]
                for name in analysis.bidders
                if (dups := analysis.duplicates_collapsed(name))
            }

            return {
                "ranking": ranking,
                "lowest_bidder": analysis.lowest_bidder,
                "bidder_count": len(analysis.bidders),
                "items_priced_by_all_count": len(analysis.items_priced_by_all()),
                "spreads": spreads,
                "spread_unmatched": unmatched,
                "spread_ambiguous": ambiguous,
                "duplicates_collapsed": collapsed,
            }

        return views.bound(await asyncio.to_thread(_analyze))

    tools: list[ToolFn] = [
        list_documents,
        open_document,
        list_structure,
        list_items,
        get_item,
        get_item_long_text,
        search_items,
        list_validation_issues,
        compare_documents,
        analyze_bids,
    ]

    if not ctx.allow_write:
        return tools

    # ── Write tools — only registered under --allow-write ──────────────

    async def export_document(
        handle: Annotated[str, Field(description="Handle from open_document.")],
        output_path: Annotated[str, Field(description="Destination path inside --output-dir.")],
        format: Annotated[
            Literal["json", "csv", "xlsx"], Field(description="Export format.")
        ] = "json",
    ) -> dict[str, Any]:
        """Write a parsed document to a file. Returns the path, never the contents."""
        assert ctx.output_dir is not None
        entry = ctx.cache.get(handle)
        dest = resolve_output_path(output_path, ctx.output_dir)

        def _write() -> int:
            if format == "json":
                from pygaeb.convert.to_json import to_json

                to_json(entry.doc, dest)
            elif format == "csv":
                from pygaeb.convert.to_csv import to_csv

                to_csv(entry.doc, dest)
            else:
                from pygaeb.convert.to_excel import to_excel

                to_excel(entry.doc, dest)
            return dest.stat().st_size

        size = await asyncio.to_thread(_write)
        return {"path": str(dest), "format": format, "bytes_written": size}

    async def convert_document(
        path: Annotated[str, Field(description="Source GAEB file inside an allowed root.")],
        output_path: Annotated[str, Field(description="Destination inside --output-dir.")],
        target_version: Annotated[
            Literal["2.0", "2.1", "3.0", "3.1", "3.2", "3.3"],
            Field(description="Target DA XML version."),
        ] = "3.3",
    ) -> dict[str, Any]:
        """Convert a GAEB file to another DA XML version. Returns a report, not contents."""
        from pygaeb.converter import GAEBConverter
        from pygaeb.models.enums import SourceVersion

        assert ctx.output_dir is not None
        source = resolve_within_roots(
            path, ctx.roots, allow_any_extension=ctx.allow_any_extension
        )
        dest = resolve_output_path(output_path, ctx.output_dir)

        report = await asyncio.to_thread(
            GAEBConverter.convert, str(source), dest, target_version=SourceVersion(target_version)
        )
        return views.bound(
            {
                "path": str(dest),
                "items_converted": report.items_converted,
                "source_version": report.source_version.value,
                "target_version": report.target_version.value,
                "has_data_loss": report.has_data_loss,
                "fields_dropped": report.fields_dropped[:20],
                "warnings": report.warnings[:20],
            }
        )

    tools.extend([export_document, convert_document])
    return tools
