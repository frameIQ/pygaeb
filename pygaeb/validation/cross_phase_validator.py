"""Cross-phase validation: verify structural compatibility between source and response files."""

from __future__ import annotations

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ValidationSeverity
from pygaeb.models.item import ValidationResult


class CrossPhaseValidator:
    """Opt-in validator for verifying source ↔ response file compatibility.

    Example:
        tender = GAEBParser.parse("tender.X83")
        bid = GAEBParser.parse("bid.X84")
        issues = CrossPhaseValidator.check(source=tender, response=bid)
    """

    @staticmethod
    def check(
        source: GAEBDocument,
        response: GAEBDocument,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        source_ozs = {item.oz for item in source.award.boq.iter_items()}
        response_ozs = {item.oz for item in response.award.boq.iter_items()}

        missing_in_response = source_ozs - response_ozs
        extra_in_response = response_ozs - source_ozs

        for oz in sorted(missing_in_response):
            source_item = source.award.boq.get_item(oz)
            if source_item and source_item.item_type.affects_total:
                results.append(ValidationResult(
                    severity=ValidationSeverity.ERROR,
                    message=f"Item {oz} present in source but missing in response",
                    xpath_location=f"Item[@RNoPart='{oz}']",
                ))

        for oz in sorted(extra_in_response):
            response_item = response.award.boq.get_item(oz)
            from pygaeb.models.enums import ItemType
            if response_item and response_item.item_type not in (
                ItemType.ALTERNATIVE, ItemType.SUPPLEMENT
            ):
                results.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=f"Item {oz} present in response but not in source",
                    xpath_location=f"Item[@RNoPart='{oz}']",
                ))

        for oz in sorted(source_ozs & response_ozs):
            source_item = source.award.boq.get_item(oz)
            response_item = response.award.boq.get_item(oz)
            if source_item and response_item:
                if (source_item.qty is not None and response_item.qty is not None
                        and source_item.qty != response_item.qty):
                    results.append(ValidationResult(
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Item {oz}: Quantity modified in response "
                            f"(source={source_item.qty}, response={response_item.qty})"
                        ),
                        xpath_location=f"Item[@RNoPart='{oz}']/Qty",
                    ))

                if response_item.item_type.affects_total and response_item.unit_price is None:
                    results.append(ValidationResult(
                        severity=ValidationSeverity.WARNING,
                        message=f"Item {oz}: Priced item missing unit price in response",
                        xpath_location=f"Item[@RNoPart='{oz}']/UP",
                    ))

        return results
