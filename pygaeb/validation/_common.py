"""Shared helpers for validation messages."""

from __future__ import annotations

from pygaeb.models.enums import ItemType, ValidationSeverity
from pygaeb.models.item import Item, ValidationResult


def item_ref(item: Item) -> str:
    """How a message names an item: ``"Item 01.02.0010"`` or ``"MarkupItem 02.0030"``.

    Uses the full OZ because the leaf ``RNoPart`` alone recurs in every category.
    """
    kind = "MarkupItem" if item.item_type == ItemType.MARKUP else "Item"
    return f"{kind} {item.full_oz or item.oz}"


def by_id(element_id: str | None, fallback: str, child: str | None = None) -> str:
    """An XPath to an element: by its XML ID when it has one, which is unique."""
    base = f"*[@ID='{element_id}']" if element_id else fallback
    return f"{base}/{child}" if child else base


def item_finding(
    item: Item,
    severity: ValidationSeverity,
    message: str,
    child: str | None = None,
    *,
    version_specific: bool = False,
    rno_part: str | None = None,
) -> ValidationResult:
    """A finding about one item, linked to it by ID and, when parsed with positions, by span.

    Without an ID the location names the item by *rno_part*, ``item.oz`` unless given.
    """
    rno = item.oz if rno_part is None else rno_part
    return ValidationResult(
        severity=severity,
        message=message,
        xpath_location=by_id(item.id, f"Item[@RNoPart='{rno}']", child),
        version_specific=version_specific,
        item_id=item.id,
        source_span=item.source_span,
    )
