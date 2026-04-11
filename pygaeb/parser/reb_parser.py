"""REB 23.003 takeoff row parser.

Parses the common textual formula formats found in GAEB X31 quantity
determination rows into structured dimensions and computed quantities.

Common formats::

    "Fundament A  5,00 * 3,20 * 0,75 = 12,000 m3"
    "Wand Nord   12,50 * 3,00 = 37,500 m2"
    "3 Stk Fenster 1,20 * 1,50 = 5,400 m2"
    "Aushub 120,000 m3"
    "Pauschale = 1,000"

The parser is tolerant of formatting variations and German decimal
notation (comma as decimal separator).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from pygaeb.models.quantity import ParsedTakeoff

# Matches a number with optional German comma decimal (e.g., "5,00" or "5.00").
# The decimal-fraction part is required when a separator is present, so "5."
# and "5," (ambiguous) won't match.
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Matches "= <result>" at the end
_RESULT_RE = re.compile(r"=\s*(-?\d+(?:[.,]\d+)?)\s*(\S*)\s*$")

# Matches multiplication chain: "5,00 * 3,20 * 0,75"
_FORMULA_RE = re.compile(
    r"(-?\d+(?:[.,]\d+)?)"       # first dimension
    r"(?:\s*[*xX\u00d7]\s*"      # multiplication operator (* x X U+00D7)
    r"(-?\d+(?:[.,]\d+)?))*"     # subsequent dimensions
)

# Split on multiplication operators
_MUL_SPLIT_RE = re.compile(r"\s*[*xX\u00d7]\s*")

# Known unit strings (checked longest-first to avoid partial matches)
_KNOWN_UNITS = ("m3", "m2", "lfm", "Stk", "psch", "kg", "m")


def _to_decimal(s: str) -> Decimal | None:
    """Convert a string with optional German comma notation to Decimal."""
    s = s.strip().replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_reb_row(raw: str) -> ParsedTakeoff:
    """Parse a REB 23.003 row string into structured takeoff data.

    Args:
        raw: The raw takeoff row string.

    Returns:
        A :class:`ParsedTakeoff` with extracted fields.
    """
    if not raw or not raw.strip():
        return ParsedTakeoff()

    text = raw.strip()
    result = ParsedTakeoff()

    # Try to extract "= <result> [unit]" from the end
    result_match = _RESULT_RE.search(text)
    if result_match:
        result.computed_qty = _to_decimal(result_match.group(1))
        result.unit = result_match.group(2).strip()
        # Remove the result part for further parsing
        formula_part = text[:result_match.start()].strip()
    else:
        formula_part = text

    # Find all numbers in the formula part
    numbers = _NUMBER_RE.findall(formula_part)

    if not numbers:
        # Pure text description, no dimensions
        result.description = text
        return result

    # Find the formula portion (numbers connected by * or x)
    # Split the text into description + formula
    # Look for the first number to separate description from formula
    first_num_match = _NUMBER_RE.search(formula_part)
    if first_num_match:
        result.description = formula_part[:first_num_match.start()].strip()
        formula_str = formula_part[first_num_match.start():].strip()
    else:
        result.description = formula_part
        formula_str = ""

    if formula_str:
        # Strip trailing unit from formula before parsing dimensions
        stripped_formula = formula_str
        for unit_candidate in _KNOWN_UNITS:
            if stripped_formula.rstrip().endswith(unit_candidate):
                result.unit = unit_candidate
                stripped_formula = stripped_formula.rstrip()[:-len(unit_candidate)].rstrip()
                break

        result.formula = formula_str
        if result_match:
            result.formula += " = " + result_match.group(1)
            if result.unit:
                result.formula += " " + result.unit

        # Extract dimensions from multiplication chain
        parts = _MUL_SPLIT_RE.split(stripped_formula)
        for part in parts:
            d = _to_decimal(part.strip())
            if d is not None:
                result.dimensions.append(d)

        if len(result.dimensions) > 1:
            result.operator = "*"

    # If no explicit result, compute from dimensions
    if result.computed_qty is None and result.dimensions:
        product = Decimal("1")
        for d in result.dimensions:
            product *= d
        result.computed_qty = product

    # If only one number and no formula, treat as direct quantity
    if not result.dimensions and numbers:
        qty = _to_decimal(numbers[-1])
        if qty is not None:
            result.dimensions = [qty]
            if result.computed_qty is None:
                result.computed_qty = qty

    return result
