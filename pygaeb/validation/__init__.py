"""Validation layer — structural, item, numeric, phase, and cross-phase rules."""

from __future__ import annotations

from collections.abc import Callable

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import ValidationResult
from pygaeb.validation.cross_phase_validator import CrossPhaseValidator
from pygaeb.validation.item_validator import validate_items
from pygaeb.validation.numeric_validator import validate_numerics
from pygaeb.validation.phase_validator import validate_phase
from pygaeb.validation.structural_validator import validate_structure
from pygaeb.validation.totals_validator import validate_totals

ValidatorFn = Callable[[GAEBDocument], list[ValidationResult]]

_custom_validators: list[ValidatorFn] = []


def register_validator(fn: ValidatorFn) -> None:
    """Register a custom validation rule that runs after built-in validators.

    The callable receives a ``GAEBDocument`` and must return a
    ``list[ValidationResult]``.  Results are appended to the document's
    ``validation_results``.
    """
    _custom_validators.append(fn)


def clear_validators() -> None:
    """Remove all custom validators.  Useful in tests."""
    _custom_validators.clear()


def run_validation(
    doc: GAEBDocument,
    route: ParseRoute,
    extra_validators: list[ValidatorFn] | None = None,
) -> list[ValidationResult]:
    """Run all validation passes and append results to the document.

    *extra_validators* are per-call validators that run in addition to the
    globally registered ones.
    """
    results: list[ValidationResult] = []

    results.extend(validate_structure(doc))
    results.extend(validate_items(doc))
    results.extend(validate_numerics(doc))
    results.extend(validate_totals(doc))
    results.extend(validate_phase(doc, route))

    for fn in _custom_validators:
        results.extend(fn(doc))

    for fn in extra_validators or []:
        results.extend(fn(doc))

    doc.validation_results.extend(results)
    return results


__all__ = [
    "CrossPhaseValidator",
    "clear_validators",
    "register_validator",
    "run_validation",
    "validate_items",
    "validate_numerics",
    "validate_phase",
    "validate_structure",
    "validate_totals",
]
