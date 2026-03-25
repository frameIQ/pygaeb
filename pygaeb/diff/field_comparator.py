"""Field-by-field comparison of matched items with significance classification.

Each comparable field has a known significance level based on its impact in a
construction context. Numeric fields also compute absolute and percent deltas.
"""

from __future__ import annotations

from decimal import Decimal

from pygaeb.diff.models import FieldChange, Significance
from pygaeb.models.item import Item

_FIELD_SIGNIFICANCE: dict[str, Significance] = {
    "unit_price": Significance.CRITICAL,
    "total_price": Significance.CRITICAL,
    "qty": Significance.CRITICAL,
    "unit": Significance.HIGH,
    "item_type": Significance.HIGH,
    "short_text": Significance.MEDIUM,
    "discount_pct": Significance.HIGH,
    "vat": Significance.MEDIUM,
    "markup_type": Significance.MEDIUM,
    "bim_guid": Significance.LOW,
    "change_order_number": Significance.LOW,
}

_COMPARABLE_FIELDS: tuple[str, ...] = (
    "short_text",
    "qty",
    "unit",
    "unit_price",
    "total_price",
    "item_type",
    "discount_pct",
    "vat",
    "markup_type",
    "bim_guid",
    "change_order_number",
)


def compare_items(item_a: Item, item_b: Item) -> list[FieldChange]:
    """Compare two matched items and return a list of field changes.

    Only fields that actually differ are returned. Numeric fields include
    absolute_delta and percent_delta where applicable.
    """
    changes: list[FieldChange] = []

    for field_name in _COMPARABLE_FIELDS:
        val_a = getattr(item_a, field_name, None)
        val_b = getattr(item_b, field_name, None)

        if _values_equal(val_a, val_b):
            continue

        significance = _FIELD_SIGNIFICANCE.get(field_name, Significance.LOW)
        abs_delta, pct_delta = _compute_deltas(val_a, val_b)

        changes.append(FieldChange(
            field=field_name,
            old_value=_serialize_value(val_a),
            new_value=_serialize_value(val_b),
            significance=significance,
            absolute_delta=abs_delta,
            percent_delta=pct_delta,
        ))

    return changes


def _values_equal(a: object, b: object) -> bool:
    """Compare two values, treating None and empty string as equivalent for text."""
    if a is None and b is None:
        return True
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if a is None and b == "":
        return True
    if a == "" and b is None:
        return True
    return a == b


def _compute_deltas(
    old: object, new: object
) -> tuple[Decimal | None, float | None]:
    """Compute absolute and percent delta for numeric values."""
    if not isinstance(old, Decimal) or not isinstance(new, Decimal):
        return None, None

    abs_delta = new - old
    pct_delta = float(abs_delta / old * Decimal("100")) if old != Decimal("0") else None

    return abs_delta, pct_delta


def _serialize_value(val: object) -> object:
    """Convert values to JSON-safe types for storage in FieldChange."""
    if isinstance(val, Decimal):
        return str(val)
    if hasattr(val, "value"):
        return val.value
    return val
