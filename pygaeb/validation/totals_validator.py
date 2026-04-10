"""Totals validation: declared XML totals vs computed subtotals from items.

Checks:
  - XML-declared totals match computed subtotals at BoQ, lot, and category levels
  - Alternative/Eventual items are not incorrectly included in declared totals
"""

from __future__ import annotations

from decimal import Decimal

from pygaeb.models.boq import BoQCtgy
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ValidationSeverity
from pygaeb.models.item import ValidationResult

_TOTALS_TOLERANCE = Decimal("0.02")


def validate_totals(doc: GAEBDocument) -> list[ValidationResult]:
    """Check XML-declared totals against computed subtotals at lot and category levels."""
    results: list[ValidationResult] = []

    boq = doc.award.boq

    # BoQ-level totals
    if boq.boq_info and boq.boq_info.totals and boq.boq_info.totals.total is not None:
        computed = sum(
            (lot.subtotal for lot in boq.lots), Decimal("0")
        )
        declared = boq.boq_info.totals.total
        if abs(declared - computed) > _TOTALS_TOLERANCE:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=(
                    f"BoQ total mismatch — declared={declared}, "
                    f"computed={computed} (diff={abs(declared - computed)})"
                ),
                xpath_location="BoQInfo/Totals/Total",
            ))

    # Lot-level totals
    for lot in boq.lots:
        if lot.totals and lot.totals.total is not None:
            computed = lot.subtotal
            declared = lot.totals.total
            if abs(declared - computed) > _TOTALS_TOLERANCE:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Lot {lot.rno!r} total mismatch — declared={declared}, "
                        f"computed={computed} (diff={abs(declared - computed)})"
                    ),
                    xpath_location=f"Lot[@RNoPart='{lot.rno}']/Totals/Total",
                ))

    # Category-level totals (recursive)
    for lot in boq.lots:
        for ctgy in lot.body.categories:
            results.extend(_validate_ctgy_totals(ctgy))

    # Check for alternative/eventual items incorrectly included in totals
    results.extend(_check_alternative_total_exclusion(doc))

    return results


def _check_alternative_total_exclusion(
    doc: GAEBDocument,
) -> list[ValidationResult]:
    """Warn if declared totals appear to include alternative/eventual items.

    Per VOB/A, alternative items must NOT be included in totals unless
    explicitly selected by the owner — including them misrepresents the bid sum.
    """
    results: list[ValidationResult] = []
    boq = doc.award.boq

    if boq.boq_info and boq.boq_info.totals and boq.boq_info.totals.total is not None:
        declared = boq.boq_info.totals.total
        # Compute total including alternatives
        total_with_alt = Decimal("0")
        total_without_alt = Decimal("0")
        for item in boq.iter_items():
            if item.total_price is not None:
                total_with_alt += item.total_price
                if item.item_type.affects_total:
                    total_without_alt += item.total_price

        has_alt_items = total_with_alt != total_without_alt
        if has_alt_items:
            # Declared total is closer to total-with-alternatives than without
            diff_with = abs(declared - total_with_alt)
            diff_without = abs(declared - total_without_alt)
            if diff_with < diff_without and diff_with <= _TOTALS_TOLERANCE:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        "BoQ total appears to include alternative/eventual items "
                        f"(declared={declared}, with_alt={total_with_alt}, "
                        f"without_alt={total_without_alt}). Per VOB/A, "
                        "alternative items should not be included in base totals."
                    ),
                    xpath_location="BoQInfo/Totals/Total",
                ))

    return results


def _validate_ctgy_totals(ctgy: BoQCtgy, depth: int = 0) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    if depth > 50:
        return results

    if ctgy.totals and ctgy.totals.total is not None:
        computed = ctgy.subtotal
        declared = ctgy.totals.total
        if abs(declared - computed) > _TOTALS_TOLERANCE:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Category {ctgy.rno!r} total mismatch — declared={declared}, "
                    f"computed={computed} (diff={abs(declared - computed)})"
                ),
                xpath_location=f"BoQCtgy[@RNoPart='{ctgy.rno}']/Totals/Total",
            ))

    for sub in ctgy.subcategories:
        results.extend(_validate_ctgy_totals(sub, depth + 1))

    return results
