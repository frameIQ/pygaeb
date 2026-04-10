"""Numeric validation: rounding checks per §5.2 rules and GAEB precision limits."""

from __future__ import annotations

from decimal import Decimal

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ValidationSeverity
from pygaeb.models.item import ValidationResult

_ROUNDING_TOLERANCE = Decimal("0.01")

# GAEB Fachdokumentation precision limits
_MAX_PRE_DECIMAL_EP = 10   # Unit price (Einheitspreis)
_MAX_PRE_DECIMAL_GB = 11   # Total amount (Gesamtbetrag)
_MAX_PRE_DECIMAL_QTY = 8   # Quantity (Menge)
_MAX_DECIMAL_QTY = 3       # Quantity max decimal places
_MAX_UP_COMPONENTS = 6     # Unit price parts (EPA)


def validate_numerics(doc: GAEBDocument) -> list[ValidationResult]:
    """Check total_price vs computed_total and GAEB precision limits for all items."""
    results: list[ValidationResult] = []

    for item in doc.award.boq.iter_items():
        # §5.2 rounding discrepancy check
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

        # GAEB precision limit: unit price max 10 pre-decimal digits
        if item.unit_price is not None:
            pre_decimal = _pre_decimal_digits(item.unit_price)
            if pre_decimal > _MAX_PRE_DECIMAL_EP:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Unit price {item.unit_price} exceeds "
                        f"GAEB limit of {_MAX_PRE_DECIMAL_EP} pre-decimal digits "
                        f"(has {pre_decimal})"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/UP",
                ))

        # GAEB precision limit: total price max 11 pre-decimal digits
        if item.total_price is not None:
            pre_decimal = _pre_decimal_digits(item.total_price)
            if pre_decimal > _MAX_PRE_DECIMAL_GB:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Total price {item.total_price} exceeds "
                        f"GAEB limit of {_MAX_PRE_DECIMAL_GB} pre-decimal digits "
                        f"(has {pre_decimal})"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/IT",
                ))

        # GAEB precision limit: quantity max 8 pre-decimal, max 3 decimal
        if item.qty is not None:
            pre_decimal = _pre_decimal_digits(item.qty)
            if pre_decimal > _MAX_PRE_DECIMAL_QTY:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Quantity {item.qty} exceeds "
                        f"GAEB limit of {_MAX_PRE_DECIMAL_QTY} pre-decimal digits "
                        f"(has {pre_decimal})"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/Qty",
                ))

            dec_places = _decimal_places(item.qty)
            if dec_places > _MAX_DECIMAL_QTY:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Quantity {item.qty} has {dec_places} "
                        f"decimal places, GAEB limit is {_MAX_DECIMAL_QTY}"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/Qty",
                ))

        # GAEB precision limit: max 6 unit price components
        if len(item.up_components) > _MAX_UP_COMPONENTS:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Item {item.oz}: {len(item.up_components)} unit price components, "
                    f"GAEB limit is {_MAX_UP_COMPONENTS}"
                ),
                xpath_location=f"Item[@RNoPart='{item.oz}']/UPComp",
            ))

    return results


def _pre_decimal_digits(value: Decimal) -> int:
    """Count pre-decimal (integer part) digits of a Decimal value."""
    abs_val = abs(value)
    int_part = int(abs_val)
    if int_part == 0:
        return 1
    count = 0
    while int_part > 0:
        int_part //= 10
        count += 1
    return count


def _decimal_places(value: Decimal) -> int:
    """Count decimal places of a Decimal value."""
    _sign, _digits, exponent = value.as_tuple()
    if not isinstance(exponent, int) or exponent >= 0:
        return 0
    return -exponent
