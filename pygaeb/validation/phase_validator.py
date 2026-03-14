"""Phase-specific validation: field presence/absence rules per exchange phase."""

from __future__ import annotations

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, ValidationSeverity
from pygaeb.models.item import ValidationResult

_PHASES_REQUIRING_QTY = {
    ExchangePhase.X83, ExchangePhase.X89, ExchangePhase.X89B,
    ExchangePhase.X83Z, ExchangePhase.X80,
}
_PHASES_REQUIRING_PRICE = {
    ExchangePhase.X84, ExchangePhase.X86, ExchangePhase.X89,
    ExchangePhase.X89B, ExchangePhase.X84Z, ExchangePhase.X86ZR,
    ExchangePhase.X86ZE,
}
_PHASES_REQUIRING_DESCRIPTION = {
    ExchangePhase.X83, ExchangePhase.X81, ExchangePhase.X83Z,
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
        if item.item_type.affects_total:
            if phase in _PHASES_REQUIRING_QTY and item.qty is None:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Quantity expected in phase {phase.value} but missing"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/Qty",
                    version_specific=True,
                ))

            if phase in _PHASES_REQUIRING_PRICE and item.unit_price is None:
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Item {item.oz}: Unit price expected in phase {phase.value} "
                        "but missing"
                    ),
                    xpath_location=f"Item[@RNoPart='{item.oz}']/UP",
                    version_specific=True,
                ))

        if phase in _PHASES_REQUIRING_DESCRIPTION and not item.short_text:
            results.append(ValidationResult(
                severity=ValidationSeverity.INFO,
                message=f"Item {item.oz}: Description expected in phase {phase.value} but missing",
                xpath_location=f"Item[@RNoPart='{item.oz}']/Description",
                version_specific=True,
            ))

    return results
