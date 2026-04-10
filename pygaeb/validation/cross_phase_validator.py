"""Cross-phase validation: verify structural compatibility between source and response files."""

from __future__ import annotations

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, ItemType, ValidationSeverity
from pygaeb.models.item import ValidationResult


class CrossPhaseValidator:
    """Opt-in validator for verifying source <-> response file compatibility.

    Supports:
      - X83 -> X84 (tender -> bid): structural identity, prices required
      - X86 -> X88 (contract -> addendum): new items allowed with CONo traceability
      - X86 -> X89 (contract -> invoice): unit prices must match, qty may differ

    Example::

        tender = GAEBParser.parse("tender.X83")
        bid = GAEBParser.parse("bid.X84")
        issues = CrossPhaseValidator.check(source=tender, response=bid)
    """

    @staticmethod
    def check(
        source: GAEBDocument,
        response: GAEBDocument,
    ) -> list[ValidationResult]:
        """Validate cross-phase compatibility between source and response.

        Automatically dispatches to the appropriate validation logic based
        on the detected phase pair.
        """
        src_phase = source.exchange_phase.normalized()
        rsp_phase = response.exchange_phase.normalized()

        if src_phase == ExchangePhase.X86 and rsp_phase == ExchangePhase.X89:
            return _check_contract_invoice(source, response)

        if src_phase == ExchangePhase.X86 and rsp_phase == ExchangePhase.X88:
            return _check_contract_addendum(source, response)

        # Default: X83->X84 style structural identity check
        return _check_tender_bid(source, response)

    @staticmethod
    def check_tender_bid(
        source: GAEBDocument,
        response: GAEBDocument,
    ) -> list[ValidationResult]:
        """Explicitly validate X83 -> X84 structural identity."""
        return _check_tender_bid(source, response)

    @staticmethod
    def check_contract_invoice(
        source: GAEBDocument,
        response: GAEBDocument,
    ) -> list[ValidationResult]:
        """Explicitly validate X86 -> X89 contract-invoice consistency."""
        return _check_contract_invoice(source, response)

    @staticmethod
    def check_contract_addendum(
        source: GAEBDocument,
        response: GAEBDocument,
    ) -> list[ValidationResult]:
        """Explicitly validate X86 -> X88 contract-addendum consistency."""
        return _check_contract_addendum(source, response)


def _check_tender_bid(
    source: GAEBDocument,
    response: GAEBDocument,
) -> list[ValidationResult]:
    """X83 -> X84: Bidder may not add/remove/reorder OZ items. Must add prices."""
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


def _check_contract_invoice(
    source: GAEBDocument,
    response: GAEBDocument,
) -> list[ValidationResult]:
    """X86 -> X89: Invoice must reference contract items with matching unit prices.

    Rules:
      - Invoice items must exist in the contract (no invented OZ numbers)
      - Unit prices in invoice must match contract unit prices exactly
      - Executed quantities in invoice may differ from contracted quantities
      - All invoiced items must have quantities (executed qty)
    """
    results: list[ValidationResult] = []

    contract_items = {
        item.oz: item for item in source.award.boq.iter_items()
    }
    invoice_items = {
        item.oz: item for item in response.award.boq.iter_items()
    }

    # Invoice items must reference existing contract items
    for oz in sorted(invoice_items.keys() - contract_items.keys()):
        inv_item = invoice_items[oz]
        if inv_item.item_type.affects_total:
            results.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Item {oz}: Invoice item not found in contract — "
                    f"invoiced items must reference existing contract OZ numbers"
                ),
                xpath_location=f"Item[@RNoPart='{oz}']",
            ))

    # Check matching items: unit prices must be identical
    for oz in sorted(contract_items.keys() & invoice_items.keys()):
        contract_item = contract_items[oz]
        inv_item = invoice_items[oz]

        if not inv_item.item_type.affects_total:
            continue

        # Unit price must match contract
        if (contract_item.unit_price is not None
                and inv_item.unit_price is not None
                and contract_item.unit_price != inv_item.unit_price):
            results.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Item {oz}: Invoice unit price ({inv_item.unit_price}) "
                    f"does not match contract unit price ({contract_item.unit_price})"
                ),
                xpath_location=f"Item[@RNoPart='{oz}']/UP",
            ))

        # Invoice must have executed quantity
        if inv_item.qty is None:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=f"Item {oz}: Invoice item missing executed quantity",
                xpath_location=f"Item[@RNoPart='{oz}']/Qty",
            ))

    return results


def _check_contract_addendum(
    source: GAEBDocument,
    response: GAEBDocument,
) -> list[ValidationResult]:
    """X86 -> X88: Nachtrag may add new items but must reference the contract.

    Rules:
      - New OZ numbers are allowed (this is the core purpose of X88)
      - Existing items referenced from contract should have matching OZ
      - Addendum items should have change order numbers (CONo) for traceability
      - Addendum items should have both quantities and prices
    """
    results: list[ValidationResult] = []

    contract_items = {
        item.oz: item for item in source.award.boq.iter_items()
    }
    addendum_items = {
        item.oz: item for item in response.award.boq.iter_items()
    }

    new_items = addendum_items.keys() - contract_items.keys()
    modified_items = addendum_items.keys() & contract_items.keys()

    # New items in addendum should have change order numbers
    for oz in sorted(new_items):
        add_item = addendum_items[oz]
        if add_item.item_type.affects_total and not add_item.change_order_number:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Item {oz}: New Nachtrag item missing change order number "
                    f"(CONo) — required for traceability to parent contract"
                ),
                xpath_location=f"Item[@RNoPart='{oz}']/CONo",
            ))

    # Modified items: check for quantity or price changes without CONo
    for oz in sorted(modified_items):
        contract_item = contract_items[oz]
        add_item = addendum_items[oz]

        if not add_item.item_type.affects_total:
            continue

        has_qty_change = (
            contract_item.qty is not None
            and add_item.qty is not None
            and contract_item.qty != add_item.qty
        )
        has_price_change = (
            contract_item.unit_price is not None
            and add_item.unit_price is not None
            and contract_item.unit_price != add_item.unit_price
        )

        if (has_qty_change or has_price_change) and not add_item.change_order_number:
            results.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                message=(
                    f"Item {oz}: Contract item modified in Nachtrag "
                    f"without change order number (CONo)"
                ),
                xpath_location=f"Item[@RNoPart='{oz}']/CONo",
            ))

    return results
