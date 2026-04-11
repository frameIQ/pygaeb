"""Validation layer — structural, item, numeric, phase, and cross-phase rules."""

from __future__ import annotations

import re
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


def _suppress_matches(message: str, patterns: list[re.Pattern[str]]) -> bool:
    """Return True if *message* matches any compiled suppress pattern."""
    return any(p.search(message) is not None for p in patterns)


def _compile_suppress(suppress: list[str] | None) -> list[re.Pattern[str]]:
    """Compile each suppress pattern as a regex with word boundaries.

    Plain words like ``"XSD"`` become ``r"\\bXSD\\b"`` so they only match
    whole tokens — preventing accidental matches such as ``"price"``
    silencing ``"unit_price"``. Patterns containing regex metacharacters
    are compiled as-is so callers can opt in to free-form regex.
    """
    if not suppress:
        return []
    compiled: list[re.Pattern[str]] = []
    metachars = set(r".^$*+?{}[]\|()")
    for pat in suppress:
        if any(c in metachars for c in pat):
            compiled.append(re.compile(pat))
        else:
            compiled.append(re.compile(rf"\b{re.escape(pat)}\b"))
    return compiled


def run_validation(
    doc: GAEBDocument,
    route: ParseRoute,
    extra_validators: list[ValidatorFn] | None = None,
    suppress: list[str] | None = None,
) -> list[ValidationResult]:
    """Run all validation passes and append results to the document.

    *extra_validators* are per-call validators that run in addition to the
    globally registered ones.

    *suppress* is a list of patterns. Plain words are matched as whole
    tokens (word-boundary regex), so ``suppress=["price"]`` will *not*
    silence ``"unit_price expected"``. Patterns containing regex
    metacharacters (``.^$*+?{}[]|()``) are compiled as free-form regex.
    Useful for acknowledging known vendor quirks.

    Examples::

        # Suppress only the literal token "XSD" (won't match "XSDValidator"):
        suppress=["XSD"]

        # Suppress any message starting with "Item ":
        suppress=[r"^Item "]
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

    if suppress:
        compiled = _compile_suppress(suppress)
        results = [r for r in results if not _suppress_matches(r.message, compiled)]

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
