"""Structural validation: BoQInfo rules, breakdown structure, hierarchy constraints."""

from __future__ import annotations

from typing import Any

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import BkdnType, ValidationSeverity
from pygaeb.models.item import ValidationResult


def validate_structure(doc: GAEBDocument) -> list[ValidationResult]:
    """Validate BoQ structural rules."""
    results: list[ValidationResult] = []

    boq = doc.award.boq

    if not boq.lots:
        results.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message="No lots found in BoQ",
        ))
        return results

    for lot in boq.lots:
        if lot.boq_info:
            results.extend(_validate_bkdn(lot.boq_info.bkdn, lot.rno))

    if boq.boq_info:
        results.extend(_validate_bkdn(boq.boq_info.bkdn, "root"))

    return results


def _validate_bkdn(bkdn: list[Any], context: str) -> list[ValidationResult]:
    results: list[ValidationResult] = []

    if not bkdn:
        return results

    item_count = sum(1 for b in bkdn if b.bkdn_type == BkdnType.ITEM)
    if item_count != 1:
        results.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message=f"BoQBkdn in {context}: expected exactly 1 Item level, found {item_count}",
        ))

    total_length = sum(b.length for b in bkdn)
    if total_length > 14:
        results.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message=f"BoQBkdn in {context}: sum of key lengths ({total_length}) exceeds 14",
        ))

    if bkdn and bkdn[0].bkdn_type != BkdnType.LOT:
        for b in bkdn[1:]:
            if b.bkdn_type == BkdnType.LOT:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=f"BoQBkdn in {context}: Lot must be the first level if present",
                ))
                break

    level_count = sum(1 for b in bkdn if b.bkdn_type == BkdnType.BOQ_LEVEL)
    if level_count > 5:
        results.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message=f"BoQBkdn in {context}: more than 5 BoQLevel entries ({level_count})",
        ))

    return results
