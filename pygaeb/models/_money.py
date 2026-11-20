"""Money arithmetic that does not depend on the caller's decimal context.

Amounts are multiplied, then rounded half-up to the cent. Python does both in
the thread's current decimal context: 28 digits by default, which an
application may have lowered, and too narrow for the product of two very large
but valid GAEB values. These helpers use a context of their own instead.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation

#: Wide enough for the product of any two GAEB amounts.
WIDE = Context(prec=60, rounding=ROUND_HALF_UP)
_CENT = Decimal("0.01")


def product_in_cents(*factors: Decimal, divisor: Decimal = Decimal(1)) -> Decimal | None:
    """The product of *factors* divided by *divisor*, rounded half-up to the cent.

    None when a value is not finite, the divisor is zero, or the result does not
    fit the wide context; an amount nobody can state is better absent than a crash.
    """
    if divisor.is_zero() or not all(f.is_finite() for f in (*factors, divisor)):
        return None
    try:
        value = Decimal(1)
        for factor in factors:
            value = WIDE.multiply(value, factor)
        return WIDE.divide(value, divisor).quantize(_CENT, context=WIDE)
    except InvalidOperation:
        return None
