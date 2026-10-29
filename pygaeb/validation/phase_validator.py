"""Phase-specific validation: field presence/absence rules per exchange phase."""

from __future__ import annotations

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, ItemType, ValidationSeverity
from pygaeb.models.item import ValidationResult
from pygaeb.validation._common import item_finding, item_ref

_PHASES_REQUIRING_QTY = {
    ExchangePhase.X82, ExchangePhase.X83, ExchangePhase.X88,
    ExchangePhase.X89, ExchangePhase.X89B, ExchangePhase.X83Z,
}
_PHASES_REQUIRING_PRICE = {
    ExchangePhase.X82, ExchangePhase.X84, ExchangePhase.X86,
    ExchangePhase.X88, ExchangePhase.X89, ExchangePhase.X89B,
    ExchangePhase.X84Z, ExchangePhase.X86ZR, ExchangePhase.X86ZE,
}
_PHASES_REQUIRING_DESCRIPTION = {
    ExchangePhase.X81, ExchangePhase.X82, ExchangePhase.X83,
    ExchangePhase.X83Z, ExchangePhase.X88,
}


def validate_phase(doc: GAEBDocument, route: ParseRoute) -> list[ValidationResult]:
    """Validate field presence/absence based on exchange phase."""
    results: list[ValidationResult] = []
    phase = (
        doc.exchange_phase.normalized()
        if hasattr(doc.exchange_phase, "normalized")
        else doc.exchange_phase
    )

    for item in doc.award.boq.iter_items():
        if item.affects_total:
            # A markup has no quantity: its amount is its rate on its base.
            needs_qty = item.item_type is not ItemType.MARKUP
            if phase in _PHASES_REQUIRING_QTY and needs_qty and item.qty is None:
                results.append(item_finding(
                    item, ValidationSeverity.WARNING,
                    f"{item_ref(item)}: Quantity expected in phase {phase.value} but missing",
                    "Qty", version_specific=True,
                ))

            if phase in _PHASES_REQUIRING_PRICE and item.unit_price is None:
                results.append(item_finding(
                    item, ValidationSeverity.WARNING,
                    f"{item_ref(item)}: Unit price expected in phase {phase.value} but missing",
                    "UP", version_specific=True,
                ))

        if phase in _PHASES_REQUIRING_DESCRIPTION and not item.short_text:
            results.append(item_finding(
                item, ValidationSeverity.INFO,
                f"{item_ref(item)}: Description expected in phase {phase.value} but missing",
                "Description", version_specific=True,
            ))

    # X88-specific: Nachtrag items should have change order numbers
    if phase == ExchangePhase.X88:
        for item in doc.award.boq.iter_items():
            if item.affects_total and not item.change_order_number:
                results.append(item_finding(
                    item, ValidationSeverity.INFO,
                    f"{item_ref(item)}: Nachtrag item (X88) missing change order "
                    "number (CONo) — recommended for traceability",
                    "CONo", version_specific=True,
                ))

    return results
