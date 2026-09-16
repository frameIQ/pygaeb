"""Shared helpers for validation messages."""

from __future__ import annotations

from pygaeb.models.enums import ItemType
from pygaeb.models.item import Item


def item_ref(item: Item) -> str:
    """How a message names an item: ``"Item 01.02.0010"`` or ``"MarkupItem 02.0030"``.

    Uses the full OZ because the leaf ``RNoPart`` alone recurs in every category.
    """
    kind = "MarkupItem" if item.item_type == ItemType.MARKUP else "Item"
    return f"{kind} {item.full_oz or item.oz}"
