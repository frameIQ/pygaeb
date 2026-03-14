"""Validation layer — structural, item, numeric, phase, and cross-phase rules."""

from __future__ import annotations

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import ValidationResult
from pygaeb.validation.cross_phase_validator import CrossPhaseValidator
from pygaeb.validation.item_validator import validate_items
from pygaeb.validation.numeric_validator import validate_numerics
from pygaeb.validation.phase_validator import validate_phase
from pygaeb.validation.structural_validator import validate_structure


def run_validation(doc: GAEBDocument, route: ParseRoute) -> list[ValidationResult]:
    """Run all validation passes and append results to the document."""
    results: list[ValidationResult] = []

    results.extend(validate_structure(doc))
    results.extend(validate_items(doc))
    results.extend(validate_numerics(doc))
    results.extend(validate_phase(doc, route))

    doc.validation_results.extend(results)
    return results


__all__ = [
    "CrossPhaseValidator",
    "run_validation",
    "validate_items",
    "validate_numerics",
    "validate_phase",
    "validate_structure",
]
