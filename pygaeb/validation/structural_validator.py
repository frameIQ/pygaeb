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
        results.extend(_validate_unique_oz(lot))

    if boq.boq_info:
        results.extend(_validate_bkdn(boq.boq_info.bkdn, "root"))

    return results


def _validate_unique_oz(lot: Any) -> list[ValidationResult]:
    """An OZ (with its index, for Indexpositionen) must be unique within a lot."""
    seen: dict[tuple[str, str], int] = {}
    for item in lot.iter_items():
        key = (item.full_oz, item.rno_index or "")
        seen[key] = seen.get(key, 0) + 1
    results: list[ValidationResult] = []
    for (oz, index), count in seen.items():
        if count > 1:
            shown = f"{oz}[{index}]" if index else oz
            results.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                message=f"Duplicate OZ {shown} ({count}x) in lot {lot.rno!r}",
                xpath_location=f"Item[@RNoPart='{oz.rsplit('.', 1)[-1]}']",
            ))
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
