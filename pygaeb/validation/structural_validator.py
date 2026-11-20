"""Structural validation: BoQInfo rules, breakdown structure, hierarchy constraints."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import AlternativeDecision, BkdnType, ValidationSeverity
from pygaeb.models.item import AlternativeGroup, Item, ValidationResult
from pygaeb.validation._common import item_finding, item_ref


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
        results.extend(_validate_alternative_groups(lot))

    if boq.boq_info:
        results.extend(_validate_bkdn(boq.boq_info.bkdn, "root"))

    return results


def _validate_unique_oz(lot: Any) -> list[ValidationResult]:
    """An OZ (with its index, for Indexpositionen) must be unique within a lot."""
    seen: dict[tuple[str, str], int] = {}
    # The first repeat of an OZ: the place a reader has to look.
    repeats: dict[tuple[str, str], Item] = {}
    for item in lot.iter_items():
        key = (item.full_oz, item.rno_index or "")
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            repeats[key] = item
    results: list[ValidationResult] = []
    for (oz, index), count in seen.items():
        if count > 1:
            shown = f"{oz}[{index}]" if index else oz
            results.append(item_finding(
                repeats[(oz, index)], ValidationSeverity.ERROR,
                f"Duplicate OZ {shown} ({count}x) in lot {lot.rno!r}",
                rno_part=oz.rsplit(".", 1)[-1],
            ))
    return results


def _validate_alternative_groups(lot: Any) -> list[ValidationResult]:
    """Each group of base and alternative positions should leave one execution counting.

    Unmarked, the base counts. An award that accepts an alternative (AltAccept)
    rejects the base it replaces (BasReject); anything else counts the work twice
    or not at all.
    """
    groups: dict[int, list[tuple[Item, AlternativeGroup]]] = defaultdict(list)
    for item in lot.iter_items():
        if item.alternative_group is not None:
            groups[item.alternative_group.number].append((item, item.alternative_group))

    warn = ValidationSeverity.WARNING
    results: list[ValidationResult] = []
    for number, members in sorted(groups.items()):
        bases = [(i, g) for i, g in members if g.is_base]
        alternatives = [(i, g) for i, g in members if not g.is_base]
        for item, group in members:
            if group.is_base and group.decision is AlternativeDecision.ALTERNATIVE_ACCEPTED:
                results.append(item_finding(
                    item, warn, f"{item_ref(item)}: AltAccept accepts an alternative, but "
                    f"this is the base position of alternative group {number}", "Accepted",
                ))
            elif not group.is_base and group.decision is AlternativeDecision.BASE_REJECTED:
                results.append(item_finding(
                    item, warn, f"{item_ref(item)}: BasReject rejects a base position, but "
                    f"this is alternative {group.serial} of group {number}", "Accepted",
                ))
        if not bases:
            results.append(item_finding(
                alternatives[0][0], warn,
                f"Alternative group {number} has alternatives but no base position "
                f"(ALNSerNo 0)",
            ))
            continue
        accepted = [(i, g) for i, g in alternatives if g.counts]
        open_bases = [i for i, g in bases if g.counts]
        if accepted and open_bases:
            results.append(item_finding(
                open_bases[0], warn,
                f"Alternative group {number}: an alternative is accepted (AltAccept), "
                f"but base position {open_bases[0].full_oz} is not rejected (BasReject), "
                f"so both count",
            ))
        accepted_serials = sorted({g.serial for _, g in accepted})
        if len(accepted_serials) > 1:
            results.append(item_finding(
                accepted[0][0], warn,
                f"Alternative group {number}: more than one alternative is accepted "
                f"({', '.join(map(str, accepted_serials))}), so each of them counts",
            ))
        if not accepted and not open_bases:
            results.append(item_finding(
                bases[0][0], warn,
                f"Alternative group {number}: the base is rejected (BasReject) but no "
                f"alternative is accepted (AltAccept), so the group adds nothing to the total",
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
