"""Document quality scoring.

Aggregate document validation results and metadata into a single
quality score (0-100) with sub-metrics for completeness, precision,
and structural validity.

Usage::

    from pygaeb import GAEBParser, quality_score

    doc = GAEBParser.parse("tender.X83")
    score = quality_score(doc)
    print(score.overall)        # 87
    print(score.completeness)   # 92
    print(score.precision)      # 95
    print(score.structure)      # 75
"""

from __future__ import annotations

from pydantic import BaseModel

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ValidationSeverity


class QualityScore(BaseModel):
    """Aggregated quality score for a parsed GAEB document."""

    overall: int = 0           # 0-100
    completeness: int = 0      # % of items with all required fields
    precision: int = 0         # % free of rounding/precision warnings
    structure: int = 0         # % free of structural errors
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0


def quality_score(doc: GAEBDocument) -> QualityScore:
    """Compute a quality score for a parsed GAEB document.

    The score is derived from:
      - **completeness**: fraction of items that have all phase-required fields
      - **precision**: 100 minus penalty for rounding/precision warnings
      - **structure**: 100 minus penalty for structural errors

    Returns a :class:`QualityScore` with sub-metrics and overall (0-100).
    """
    items = list(doc.iter_items())
    total_items = len(items)

    errors = sum(
        1 for r in doc.validation_results
        if r.severity == ValidationSeverity.ERROR
    )
    warnings = sum(
        1 for r in doc.validation_results
        if r.severity == ValidationSeverity.WARNING
    )
    infos = sum(
        1 for r in doc.validation_results
        if r.severity == ValidationSeverity.INFO
    )

    if total_items == 0:
        complete = 100
    else:
        complete_items = sum(
            1 for item in items
            if _is_complete(item)
        )
        complete = int(100 * complete_items / total_items)

    precision_warnings = sum(
        1 for r in doc.validation_results
        if "precision" in r.message.lower()
        or "rounding" in r.message.lower()
        or "mismatch" in r.message.lower()
    )
    if total_items == 0:
        precision = 100
    else:
        precision = max(0, 100 - int(100 * precision_warnings / total_items))

    structural_errors = sum(
        1 for r in doc.validation_results
        if r.severity == ValidationSeverity.ERROR
        and ("structure" in r.message.lower()
             or "missing" in r.message.lower()
             or "duplicate" in r.message.lower())
    )
    structure = max(0, 100 - structural_errors * 10)

    overall = (complete + precision + structure) // 3

    return QualityScore(
        overall=overall,
        completeness=complete,
        precision=precision,
        structure=structure,
        error_count=errors,
        warning_count=warnings,
        info_count=infos,
    )


def _is_complete(item: object) -> bool:
    """Heuristic: an item is complete if it has short_text and either qty or price."""
    short_text = getattr(item, "short_text", "")
    qty = getattr(item, "qty", None)
    unit_price = getattr(item, "unit_price", None)
    return bool(short_text) and (qty is not None or unit_price is not None)
