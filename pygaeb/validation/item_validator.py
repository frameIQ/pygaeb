"""Item-level validation: qty rules, QtySplit totals, change order requirements."""

from __future__ import annotations

from decimal import Decimal

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ItemType, ValidationSeverity
from pygaeb.models.item import ValidationResult
from pygaeb.validation._common import item_ref
from pygaeb.validation.phase_validator import _PHASES_REQUIRING_DESCRIPTION


def validate_items(doc: GAEBDocument) -> list[ValidationResult]:
    """Validate individual item rules."""
    results: list[ValidationResult] = []
    phase = doc.exchange_phase
    if hasattr(phase, "normalized"):
        phase = phase.normalized()
    # A bid (X84) only returns prices; its texts are optional by schema.
    text_expected = phase in _PHASES_REQUIRING_DESCRIPTION

    for item in doc.award.boq.iter_items():
        if item.item_type == ItemType.SUPPLEMENT and not item.change_order_number:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=f"{item_ref(item)}: Supplement item missing change order number (CONo)",
                xpath_location=f"Item[@RNoPart='{item.oz}']",
            ))

        if item.qty_splits:
            split_total = sum(qs.qty for qs in item.qty_splits)
            if item.qty is not None and abs(split_total - item.qty) > Decimal("0.001"):
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"{item_ref(item)}: QtySplit total ({split_total}) "
                        f"does not match item quantity ({item.qty})"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/QtySplit",
                ))

        if item.item_type == ItemType.NORMAL and item.qty is None:
            results.append(ValidationResult(
                severity=ValidationSeverity.INFO,
                message=f"{item_ref(item)}: Normal item has no quantity",
                xpath_location=f"Item[@RNoPart='{item.oz}']",
            ))

        # Markup items (Zuschlagspositionen) carry no ShortText in 3.x files.
        if (
            text_expected
            and not item.short_text
            and item.item_type not in (ItemType.INDEX, ItemType.MARKUP)
        ):
            results.append(ValidationResult(
                severity=ValidationSeverity.INFO,
                message=f"{item_ref(item)}: Missing short text",
                xpath_location=f"Item[@RNoPart='{item.oz}']",
            ))

    return results
