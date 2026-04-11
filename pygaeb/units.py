"""Unit normalization for GAEB measurements.

Real GAEB files use inconsistent unit notation (m2/m^2/qm/m²). This
module normalizes them to standard ISO/SI form for analysis.

Usage::

    from pygaeb import normalize_unit

    normalize_unit("m2")     # "m²"
    normalize_unit("qm")     # "m²"
    normalize_unit("m^3")    # "m³"
    normalize_unit("Stck")   # "Stk"

    # Bulk normalization across a document:
    from pygaeb import normalize_units_in_doc
    normalize_units_in_doc(doc)
"""

from __future__ import annotations

from pygaeb.models.document import GAEBDocument

# Mapping of common variants to canonical form.
# Values: canonical (Unicode) form
_UNIT_ALIASES: dict[str, str] = {
    # Square meters
    "m2": "m²",
    "m^2": "m²",
    "qm": "m²",
    "qm.": "m²",
    "sqm": "m²",
    "qm2": "m²",
    "m**2": "m²",
    "m²": "m²",
    # Cubic meters
    "m3": "m³",
    "m^3": "m³",
    "cbm": "m³",
    "cbm.": "m³",
    "m**3": "m³",
    "m³": "m³",
    # Linear meters
    "lfdm": "lfm",
    "lfdm.": "lfm",
    "lm": "lfm",
    "lfd.m": "lfm",
    "lfm": "lfm",
    "m": "m",
    # Pieces
    "stk": "Stk",
    "stck": "Stk",
    "stk.": "Stk",
    "stck.": "Stk",
    "st": "Stk",
    "st.": "Stk",
    "pcs": "Stk",
    "pieces": "Stk",
    "Stk": "Stk",
    "Stck": "Stk",
    # Lump sum
    "psch": "psch",
    "psch.": "psch",
    "pausch": "psch",
    "pauschal": "psch",
    "ls": "psch",
    "lump": "psch",
    # Mass
    "kg": "kg",
    "Kg": "kg",
    "KG": "kg",
    "t": "t",
    "to": "t",
    "tonne": "t",
    "tonnen": "t",
    # Hours
    "h": "h",
    "Std": "h",
    "Std.": "h",
    "hr": "h",
}


def normalize_unit(unit: str | None) -> str | None:
    """Return the canonical form of a unit string.

    Strips leading/trailing whitespace and matches case-insensitively
    against known variants. Returns the input unchanged if no match.

    Args:
        unit: A raw unit string from a GAEB file.

    Returns:
        Canonical unit string (e.g. "m²", "m³", "Stk"), or the input
        unchanged if not recognized. ``None`` returns ``None``.
    """
    if unit is None:
        return None
    cleaned = unit.strip()
    if not cleaned:
        return cleaned
    # Try direct match first (preserves case-sensitive entries)
    if cleaned in _UNIT_ALIASES:
        return _UNIT_ALIASES[cleaned]
    # Fall back to lowercase match
    lower = cleaned.lower()
    return _UNIT_ALIASES.get(lower, cleaned)


def normalize_units_in_doc(doc: GAEBDocument) -> int:
    """Normalize all item units in a document in place.

    Args:
        doc: The GAEBDocument to update.

    Returns:
        Number of items whose units were changed.
    """
    changed = 0
    for item in doc.iter_items():
        original = getattr(item, "unit", None)
        if original is None:
            continue
        normalized = normalize_unit(original)
        if normalized != original:
            item.unit = normalized
            changed += 1
    return changed
