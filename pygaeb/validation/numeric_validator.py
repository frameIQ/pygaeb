"""Numeric validation: rounding checks per §5.2 rules."""

from __future__ import annotations

from decimal import Decimal

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ValidationSeverity
from pygaeb.models.item import ValidationResult

_ROUNDING_TOLERANCE = Decimal("0.01")


def validate_numerics(doc: GAEBDocument) -> list[ValidationResult]:
    """Check total_price vs computed_total (qty x unit_price) for all items."""
    results: list[ValidationResult] = []

    for item in doc.award.boq.iter_items():
        if item.total_price is not None and item.computed_total is not None:
            diff = abs(item.total_price - item.computed_total)
            if diff > _ROUNDING_TOLERANCE:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Total price mismatch — "
                        f"stored={item.total_price}, "
                        f"computed={item.computed_total} "
                        f"(diff={diff})"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/IT",
                ))

    return results
