"""Numbers from GAEB files: plain decimals of sane size, nothing else.

GAEB numbers are ``xs:decimal``: an optional sign, digits and at most one
decimal point. Python's ``Decimal()`` accepts far more, and each extra causes
trouble once the value is in the model. ``NaN`` and ``Infinity`` poison sums
and crash comparisons. An exponent such as ``1E+999999`` makes a 20-byte value
cost minutes of CPU in validation, or gigabytes of digits in an export. Unicode
digits and ``1_000`` are not what any other GAEB tool reads.

:func:`parse_decimal` therefore accepts only the plain form, within
:data:`MAX_INTEGER_DIGITS` and :data:`MAX_FRACTION_DIGITS`. A comma is taken as
the decimal separator, as pyGAEB always did. Anything else reads as empty.
While a parse runs inside :func:`collecting_rejects`, the rejected texts are
counted, so the parse can report what it could not read instead of losing it
silently.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

#: Integer digits a value may have. The 3.3 schema allows at most 13, for an EAN;
#: amounts (tgDecimal_13_2: 13 digits, 2 after the point) have 11.
MAX_INTEGER_DIGITS = 15
#: Fraction digits a value may have. The schema allows at most 6 (rates, tgDecimal_9_6).
MAX_FRACTION_DIGITS = 10

#: How many rejected texts a report quotes, and how much of each.
_SAMPLES = 5
_SAMPLE_CHARS = 24

_PLAIN = re.compile(r"([+-]?)(\d*)(?:[.,](\d*))?", re.ASCII)


@dataclass
class RejectedNumbers:
    """The texts one parse could not read as numbers: a count and a few samples."""

    count: int = 0
    samples: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.count += 1
        if len(self.samples) < _SAMPLES:
            clipped = text[:_SAMPLE_CHARS] + ("…" if len(text) > _SAMPLE_CHARS else "")
            self.samples.append(clipped)

    def message(self) -> str:
        quoted = ", ".join(repr(s) for s in self.samples)
        more = ", …" if self.count > len(self.samples) else ""
        return (
            f"{self.count} value(s) are not plain decimal numbers and were read as "
            f"empty: {quoted}{more}. GAEB numbers are digits with at most one "
            f"decimal separator, up to {MAX_INTEGER_DIGITS} integer and "
            f"{MAX_FRACTION_DIGITS} fraction digits"
        )


_rejected: ContextVar[RejectedNumbers | None] = ContextVar(
    "pygaeb_rejected_numbers", default=None,
)


@contextmanager
def collecting_rejects() -> Iterator[RejectedNumbers]:
    """Count the texts :func:`parse_decimal` rejects while the block runs."""
    rejected = RejectedNumbers()
    token = _rejected.set(rejected)
    try:
        yield rejected
    finally:
        _rejected.reset(token)


def parse_decimal(text: str | None, *, report: bool = True) -> Decimal | None:
    """The plain decimal in *text*, or None when it is empty or not one.

    With *report*, a rejected text is counted by an enclosing
    :func:`collecting_rejects`. Pass ``report=False`` for free text that may
    hold something other than a number.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    match = _PLAIN.fullmatch(stripped)
    if (
        match is None
        or not (match[2] or match[3])
        or len(match[2].lstrip("0")) > MAX_INTEGER_DIGITS
        or len(match[3] or "") > MAX_FRACTION_DIGITS
    ):
        if report and (sink := _rejected.get()) is not None:
            sink.add(stripped)
        return None
    sign, whole, fraction = match.groups()
    digits = whole or "0"
    return Decimal(f"{sign}{digits}.{fraction}" if fraction else f"{sign}{digits}")
