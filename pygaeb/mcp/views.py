"""Bounded projections of GAEB models for LLM consumption.

This module is the context-safety core. A real tender serialized whole is
megabytes; an LLM context window is not. Nothing here ever calls
``model_dump()`` — every projection is an explicit field allowlist, which makes
the dangerous fields structurally unreachable rather than merely omitted:

* ``Attachment.data`` (raw bytes) — only ``filename``/``mime_type``/``size_bytes``
  are ever projected.
* ``Item.long_text`` (unbounded prose) — previewed in detail views, never in list
  views, and reachable in full only through explicit character paging.
* ``Item.raw_data`` / ``source_element`` / ``xml_root`` — never projected.

Three bounding layers apply: structural allowlists, pagination on every list, and
:func:`bound` as a final serialized-size backstop.

Truncated values always report their true length (``short_text_chars``,
``total_chars``) so a model can tell it is reading a fragment.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from pygaeb.api.boq_tree import BoQNode, NodeKind
from pygaeb.config import get_settings
from pygaeb.models.boq import Totals
from pygaeb.models.item import Attachment, ValidationResult

__all__ = [
    "LONG_TEXT_PREVIEW_CHARS",
    "SHORT_TEXT_CHARS",
    "bound",
    "document_summary",
    "is_priced",
    "item_detail",
    "item_row",
    "paginate",
    "structure_node",
    "validation_issue",
]

SHORT_TEXT_CHARS = 120
LONG_TEXT_PREVIEW_CHARS = 500
MESSAGE_CHARS = 200
SNIPPET_RADIUS = 80

# Room reserved for the JSON envelope around a text window.
_ENVELOPE_ALLOWANCE = 600

_MAX_LOT_LABELS = 20
_MAX_NESTED_LIST = 50


# ── Primitives ─────────────────────────────────────────────────────────


def _dec(value: Decimal | None) -> str | None:
    """Serialize a Decimal losslessly. JSON floats would corrupt currency."""
    return None if value is None else str(value)


def _clip(text: str | None, limit: int) -> tuple[str, int]:
    """Return (clipped_text, true_length)."""
    if not text:
        return "", 0
    return (text[:limit], len(text))


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read an optional attribute across the four item kinds.

    ``doc.iter_items()`` yields ``Item``, ``OrderItem``, ``CostElement``, or
    ``QtyItem`` depending on the document kind, and those classes do **not**
    share a base — e.g. ``QtyItem`` has no ``short_text`` and ``OrderItem`` has no
    ``total_price``. Projections therefore read defensively and degrade to nulls
    rather than raising, matching the library's tolerant-parsing stance.
    """
    return getattr(obj, name, default)


def paginate(
    seq: Sequence[Any],
    offset: int,
    limit: int,
) -> tuple[list[Any], int, bool]:
    """Slice *seq* and report the full population size.

    Returns:
        (page, total_matched, has_more). ``total_matched`` is the size of the
        whole match set, not the page, so the model knows what it did not see.
    """
    total = len(seq)
    offset = max(0, offset)
    cap = get_settings().mcp_max_page_size
    limit = max(1, min(limit, cap))
    page = list(seq[offset : offset + limit])
    return page, total, offset + len(page) < total


def max_text_window() -> int:
    """The largest text window that still leaves room for the JSON envelope.

    ``bound`` can only shrink *lists*, so a tool returning one big string must
    clamp it up front or it would blow the budget with nothing to drop. Derived
    from the configured budget rather than hardcoded, so lowering
    ``mcp_max_response_chars`` tightens this automatically.
    """
    return max(500, get_settings().mcp_max_response_chars - _ENVELOPE_ALLOWANCE)


def bound(payload: dict[str, Any]) -> dict[str, Any]:
    """Final backstop: shrink *payload* until it serializes under the char budget.

    Pagination and allowlists should already have kept us well clear of this. It
    exists so that a pathological document cannot blow the context window even if
    a projection is wrong — trailing entries are dropped from the longest list
    and the result is flagged rather than silently truncated.

    Limitation: only **top-level lists** can be shrunk. A payload dominated by a
    single large string is flagged ``truncated`` but not reduced — which is why
    every tool that returns a text window must clamp it via
    :func:`max_text_window` before calling this.
    """
    max_chars = get_settings().mcp_max_response_chars
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= max_chars:
        return payload

    list_keys = [k for k, v in payload.items() if isinstance(v, list) and v]
    if not list_keys:
        payload["truncated"] = True
        payload["truncated_reason"] = "response_size"
        return payload

    while len(encoded) > max_chars:
        longest = max(list_keys, key=lambda k: len(payload[k]))
        if not payload[longest]:
            break
        payload[longest].pop()
        encoded = json.dumps(payload, ensure_ascii=False)

    payload["truncated"] = True
    payload["truncated_reason"] = "response_size"
    return payload


# ── Projections ────────────────────────────────────────────────────────


def _totals(totals: Totals | None) -> dict[str, Any]:
    if totals is None:
        return {}
    return {
        "total": _dec(totals.total),
        "total_net": _dec(totals.total_net),
        "total_gross": _dec(totals.total_gross),
        "vat": _dec(totals.vat),
    }


def attachment_meta(att: Attachment) -> dict[str, Any]:
    """Project an attachment to metadata only.

    ``Attachment.data`` is deliberately absent and must stay that way — it is raw
    binary and would be catastrophic in a context window.
    """
    return {
        "filename": att.filename,
        "mime_type": att.mime_type,
        "size_bytes": att.size_bytes,
    }


def is_priced(doc: Any) -> bool:
    """Whether any item carries a unit or total price.

    An X83 before bids has no prices at all, and the library's ``grand_total``
    sums to ``0`` there — which a model would faithfully report as "the tender
    costs 0 €". Summaries use this to report ``null`` instead.
    """
    return any(
        _attr(item, "unit_price") is not None or _attr(item, "total_price") is not None
        for item in doc.iter_items()
    )


def document_summary(doc: Any, handle: str, path: str, cached: bool) -> dict[str, Any]:
    """The orienting payload for ``open_document``.

    Fixed-size: roughly 25 scalars plus one capped list, regardless of whether the
    source file is 4 KB or 500 MB.
    """
    from pygaeb.quality import quality_score

    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in doc.validation_results:
        key = issue.severity.value.lower()
        if key in counts:
            counts[key] += 1

    score = quality_score(doc)
    payload: dict[str, Any] = {
        "handle": handle,
        "file": path,
        "cached": cached,
        "source_version": doc.source_version.value,
        "exchange_phase": doc.exchange_phase.value,
        "document_kind": doc.document_kind.value,
        "is_procurement": doc.is_procurement,
        "is_trade": doc.is_trade,
        "is_cost": doc.is_cost,
        "is_quantity": doc.is_quantity,
        "item_count": doc.item_count,
        "memory_estimate_mb": round(doc.memory_estimate_mb, 2),
        "validation_counts": counts,
        "quality": {
            "overall": score.overall,
            "completeness": score.completeness,
            "precision": score.precision,
            "structure": score.structure,
        },
    }

    if doc.is_procurement:
        award = doc.award
        priced = is_priced(doc)
        # Stated totals need an item total somewhere; a bid with unit prices only
        # has none, and reporting "0" there reads as a zero bid.
        stated = priced and any(_attr(i, "total_price") is not None for i in doc.iter_items())
        payload.update(
            {
                "project_no": award.project_no,
                "project_name": award.project_name,
                "client": award.client,
                "currency": award.currency,
                # Null, not "0", on an unpriced tender — see is_priced().
                "is_priced": priced,
                "grand_total": _dec(doc.grand_total) if stated else None,
                "computed_grand_total": _dec(doc.computed_grand_total) if priced else None,
                "award": award_info(award),
            }
        )
        boq = getattr(award, "boq", None)
        if boq is not None:
            payload.update(_totals(getattr(boq.boq_info, "totals", None) if boq.boq_info else None))
            # The placeholder lot the parser adds to lot-less files is not a Los.
            lots = [
                lot for lot in (getattr(boq, "lots", []) or [])
                if not getattr(lot, "synthetic", False)
            ]
            labels = [lot.label or lot.rno for lot in lots][:_MAX_LOT_LABELS]
            payload["lot_count"] = len(lots)
            payload["is_multi_lot"] = len(lots) > 1
            payload["lot_labels"] = labels
            if len(lots) > _MAX_LOT_LABELS:
                payload["lot_labels_truncated"] = True

    return bound(payload)


def award_info(award: Any) -> dict[str, Any]:
    """The tender's dates and terms from ``AwardInfo`` — what an estimator asks first."""

    def _date(name: str) -> str | None:
        value = _attr(award, name)
        return value.isoformat() if value is not None else None

    return {
        "open_date": _date("open_date"),
        "open_time": _attr(award, "open_time"),
        "eval_end": _date("eval_end"),
        "submit_location": _attr(award, "submit_location"),
        "construction_start": _date("construction_start"),
        "construction_end": _date("construction_end"),
        "contract_no": _attr(award, "contract_no"),
        "contract_date": _date("contract_date"),
        "award_no": _attr(award, "award_no"),
        "procurement_type": _attr(award, "procurement_type"),
        "description": _attr(award, "description"),
    }


def item_row(item: Any) -> dict[str, Any]:
    """List-view projection of an item, across all four document kinds.

    Deliberately omits ``long_text``, ``bidder_prices``, ``cost_approaches``,
    ``raw_data``, and attachment bytes. Reports presence and size of the omitted
    prose so the model can decide whether to fetch it.
    """
    short_text, short_len = _clip(_attr(item, "short_text", ""), SHORT_TEXT_CHARS)
    long_plain: str = _attr(item, "long_text_plain", "") or ""
    item_type = _attr(item, "item_type")
    attachments = _attr(item, "attachments", []) or []
    return {
        "oz": _attr(item, "full_oz") or _attr(item, "oz", "") or "",
        "short_text": short_text,
        "short_text_chars": short_len,
        "qty": _dec(_attr(item, "qty")),
        "unit": _attr(item, "unit"),
        "unit_price": _dec(_attr(item, "unit_price")),
        "total_price": _dec(_attr(item, "total_price")),
        # qty x unit price; the stated total is often absent in bids.
        "computed_total": _dec(_attr(item, "computed_total")),
        "item_type": item_type.value if item_type is not None else None,
        # Whether the price counts toward the contract total (VOB/A) —
        # False for alternative/eventual/text-only positions.
        "affects_total": bool(item_type.affects_total) if item_type is not None else None,
        "has_long_text": bool(long_plain),
        "long_text_chars": len(long_plain),
        "attachment_count": len(attachments),
        "has_classification": _attr(item, "classification") is not None,
    }


def item_detail(item: Any, node: BoQNode | None = None) -> dict[str, Any]:
    """Single-item projection, across all four document kinds.

    The only unbounded field, ``long_text``, is previewed; the full text is
    reachable only via ``get_item_long_text``.
    """
    payload = item_row(item)
    long_text = _attr(item, "long_text")
    preview, total_chars = _clip(_attr(item, "long_text_plain", "") or "", LONG_TEXT_PREVIEW_CHARS)
    payload.update(
        {
            "hierarchy_path": _attr(item, "hierarchy_path", []) or [],
            "lot_label": _attr(item, "lot_label"),
            "computed_total": _dec(_attr(item, "computed_total")),
            "has_rounding_discrepancy": bool(_attr(item, "has_rounding_discrepancy", False)),
            "bim_guid": _attr(item, "bim_guid"),
            "change_order_number": _attr(item, "change_order_number"),
            "vat": _dec(_attr(item, "vat")),
            "discount_pct": _dec(_attr(item, "discount_pct")),
            "long_text_preview": preview,
            "long_text_chars": total_chars,
            "long_text_tables": len(long_text.tables) if long_text else 0,
            "long_text_images": len(long_text.images) if long_text else 0,
            "attachments": [
                attachment_meta(a)
                for a in (_attr(item, "attachments", []) or [])[:_MAX_NESTED_LIST]
            ],
            "qty_splits": [
                {"label": s.label, "qty": _dec(s.qty), "unit": s.unit}
                for s in (_attr(item, "qty_splits", []) or [])[:_MAX_NESTED_LIST]
            ],
            "bidder_prices": [
                {
                    "bidder_name": b.bidder_name,
                    "unit_price": _dec(b.unit_price),
                    "total_price": _dec(b.total_price),
                    "rank": b.rank,
                }
                for b in (_attr(item, "bidder_prices", []) or [])[:_MAX_NESTED_LIST]
            ],
        }
    )
    classification = _attr(item, "classification")
    if classification is not None:
        payload["classification"] = {
            "trade": classification.trade,
            "element_type": classification.element_type,
            "sub_type": classification.sub_type,
            "confidence": classification.confidence,
            "ifc_type": classification.ifc_type,
            "din276_code": classification.din276_code,
        }
    if node is not None:
        payload["label_path"] = node.label_path
    return bound(payload)


def structure_node(node: BoQNode) -> dict[str, Any]:
    """Project one structural node.

    ``item_count`` and ``subtotal`` are what let a model find the expensive part
    of a tender *without* descending into it — the whole point of the tool.
    """
    totals: Totals | None = None
    if node.kind == NodeKind.CATEGORY:
        totals = node.category.totals
    elif node.kind == NodeKind.LOT:
        totals = node.lot.totals

    label, _ = _clip(node.label, SHORT_TEXT_CHARS)
    payload = {
        "rno": node.rno,
        "label": label,
        "kind": node.kind.value,
        "depth": node.depth,
        "child_count": len(node.children),
        "item_count": sum(1 for _ in node.iter_items()),
        "subtotal": _dec(totals.total) if totals else None,
    }
    if node.kind == NodeKind.LOT and getattr(node.lot, "synthetic", False):
        payload["synthetic"] = True
    return payload


def effective_total(item: Any) -> Decimal | None:
    """The stated item total, else qty x unit price."""
    total: Decimal | None = _attr(item, "total_price")
    if total is None:
        total = _attr(item, "computed_total")
    return total


def effective_grand_total(doc: Any) -> Decimal | None:
    """Sum of :func:`effective_total` over the positions that count toward the contract."""
    total = Decimal(0)
    seen = False
    for item in doc.iter_items():
        value = effective_total(item)
        item_type = _attr(item, "item_type")
        if value is None or (item_type is not None and not item_type.affects_total):
            continue
        total += value
        seen = True
    return total if seen else None


def section_change(change: Any) -> dict[str, Any]:
    """Project a section added/removed/renamed or an item moved, whichever it is."""
    payload: dict[str, Any] = change.model_dump()
    for key in ("label", "old_label", "new_label", "short_text"):
        if key in payload and isinstance(payload[key], str):
            payload[key], _ = _clip(payload[key], SHORT_TEXT_CHARS)
    return payload


def validation_issue(issue: ValidationResult) -> dict[str, Any]:
    """Project one validation result, with the message clipped."""
    message, message_len = _clip(issue.message, MESSAGE_CHARS)
    return {
        "severity": issue.severity.value,
        "message": message,
        "message_chars": message_len,
        "xpath_location": issue.xpath_location,
    }


def snippet(text: str, query: str, radius: int = SNIPPET_RADIUS) -> tuple[str, int]:
    """Extract a context window around the first match of *query*.

    Returns (snippet, match_count). Returning windows rather than whole fields is
    what makes searching megabytes of specification prose cost ~1 KB of context.
    """
    lowered = text.lower()
    needle = query.lower()
    count = lowered.count(needle)
    if count == 0:
        return "", 0
    pos = lowered.find(needle)
    start = max(0, pos - radius)
    end = min(len(text), pos + len(needle) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}", count
