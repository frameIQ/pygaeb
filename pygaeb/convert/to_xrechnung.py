"""XRechnung 3.0 (UBL 2.1) export from GAEB X89 invoice documents.

XRechnung is the German e-invoicing standard: EN 16931 with the German
rules on top. Public clients require it, and German B2B invoices become
e-invoices from 2027 on. This module maps a GAEB X89/X89B invoice to an
XRechnung 3.0 UBL invoice.

A GAEB file carries the positions, quantities, prices, VAT rates and the
parties' addresses. An invoice needs more: its number and date, electronic
addresses, contact details, the bank account, the payment terms and the
time of the service. Pass those as arguments. The function returns every
problem that would make the result invalid or leave out what § 14 UStG
requires, or raises before writing with ``strict=True``.

Check production output with the KoSIT validator and its XRechnung
configuration (https://github.com/itplr-kosit/validator).

Usage::

    from datetime import date

    from pygaeb import GAEBParser
    from pygaeb.convert.to_xrechnung import InvoiceParty, PaymentDetails, to_xrechnung

    invoice = GAEBParser.parse("invoice.X89")
    problems = to_xrechnung(
        invoice, "invoice.xml",
        invoice_number="R-2026-0042",
        leitweg_id="04011000-12345-03",
        seller=InvoiceParty(vat_id="DE123456789", contact_name="Anna Bau",
                            phone="+49 30 23125 000", email="rechnung@bau.example"),
        buyer=InvoiceParty(email="rechnungseingang@stadt.example"),
        payment=PaymentDetails(iban="DE89370400440532013000"),
        payment_terms="Zahlbar innerhalb von 30 Tagen ohne Abzug",
        service_period=(date(2026, 10, 1), date(2026, 10, 31)),
    )
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from lxml import etree
from pydantic import BaseModel

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, ItemType
from pygaeb.models.item import Item
from pygaeb.models.order import Address
from pygaeb.units import normalize_unit

logger = logging.getLogger("pygaeb.convert.xrechnung")

# UBL namespaces
_UBL = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

NSMAP = {None: _UBL, "cac": _CAC, "cbc": _CBC}

#: BT-24, the specification identifier of XRechnung 3.0; patch releases such as
#: 3.0.2 keep it. Validators choose their rule set by this exact string, so it
#: names the rules this module writes and is not a caller's option.
CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
#: BT-23, the business process: Peppol billing, the one for an ordinary invoice.
#: XRechnung requires a business process (rule PEPPOL-EN16931-R001).
PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)

#: GAEB units, as :func:`normalize_unit` spells them, to UN/ECE Recommendation 20.
_UNIT_CODES: dict[str, str] = {
    "m": "MTR", "lfm": "MTR", "m²": "MTK", "m³": "MTQ",
    "km": "KMT", "cm": "CMT", "mm": "MMT",
    "Stk": "H87", "psch": "LS", "Satz": "SET", "Paar": "PR",
    "kg": "KGM", "g": "GRM", "t": "TNE", "l": "LTR",
    "h": "HUR", "min": "MIN", "d": "DAY", "Tag": "DAY",
    "Wo": "WEE", "Woche": "WEE", "Mon": "MON", "Monat": "MON", "a": "ANN", "Jahr": "ANN",
    "%": "P1", "kW": "KWT", "kWh": "KWH",
}
_UNIT_CODES_FOLDED = {k.casefold(): v for k, v in _UNIT_CODES.items()}

_CURRENCY_ALIASES = {"€": "EUR", "EURO": "EUR"}
_COUNTRY_ALIASES = {
    "D": "DE", "DEUTSCHLAND": "DE", "GERMANY": "DE",
    "A": "AT", "ÖSTERREICH": "AT", "AUSTRIA": "AT", "SCHWEIZ": "CH", "SWITZERLAND": "CH",
}

#: BT-120/BT-121 for reverse charge on construction services (§ 13b UStG).
_REVERSE_CHARGE_CODE = "VATEX-EU-AE"
_REVERSE_CHARGE_REASON = "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)"


class InvoiceParty(BaseModel):
    """Seller or buyer details an XRechnung needs.

    Fields left unset come from the GAEB file: the contractor's address for the
    seller, the owner's for the buyer. ``electronic_address`` (BT-34 / BT-49)
    falls back to the e-mail address; for the buyer, to ``leitweg_id`` first.
    """

    name: str | None = None
    street: str | None = None
    postcode: str | None = None
    city: str | None = None
    #: ISO 3166-1 alpha-2; ``D`` and ``Deutschland`` are read as ``DE``. Default ``DE``.
    country: str | None = None
    vat_id: str | None = None
    #: Seller only: the tax number (Steuernummer), BT-32.
    tax_number: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    electronic_address: str | None = None
    #: EAS code of ``electronic_address``: ``EM`` for e-mail, ``0204`` for a Leitweg-ID.
    electronic_address_scheme: str = "EM"


class PaymentDetails(BaseModel):
    """BG-16/BG-17: how the invoice is paid; by default a SEPA credit transfer."""

    iban: str
    bic: str | None = None
    account_name: str | None = None
    #: UNTDID 4461: ``58`` SEPA credit transfer, ``30`` other credit transfer.
    means_code: str = "58"


@dataclass
class _Line:
    line_id: str
    name: str
    qty: Decimal
    unit_code: str
    amount: Decimal
    price: Decimal
    category: str
    rate: Decimal


def to_xrechnung(
    doc: GAEBDocument,
    path: str | Path,
    *,
    invoice_number: str | None = None,
    issue_date: date_type | None = None,
    seller_name: str = "",
    buyer_name: str = "",
    leitweg_id: str = "",
    seller: InvoiceParty | None = None,
    buyer: InvoiceParty | None = None,
    payment: PaymentDetails | None = None,
    due_date: date_type | None = None,
    payment_terms: str | None = None,
    delivery_date: date_type | None = None,
    service_period: tuple[date_type, date_type] | None = None,
    vat_rate: Decimal | None = None,
    reverse_charge: bool = False,
    prepaid_amount: Decimal | None = None,
    unit_codes: dict[str, str] | None = None,
    strict: bool = False,
) -> list[str]:
    """Export a GAEB X89 invoice as an XRechnung 3.0 UBL invoice.

    Only positions that count become invoice lines: alternatives, Bedarfs-
    positionen ohne GB, text-only and not-applicable positions stay off. A
    markup becomes one line of its own amount.

    Args:
        doc: A parsed GAEB document with phase X89 or X89B.
        path: Output file path (.xml).
        invoice_number: BT-1. Without it the project number stands in.
        issue_date: BT-2 (default: today).
        seller_name: Seller name, used when ``seller.name`` is not given.
        buyer_name: Buyer name, used when ``buyer.name`` is not given.
        leitweg_id: BT-10, the buyer reference; a public client's Leitweg-ID.
        seller: Seller (contractor) details beyond the GAEB file.
        buyer: Buyer (owner) details beyond the GAEB file.
        payment: BG-16, the payment instructions; required.
        due_date: BT-9. This or ``payment_terms`` is required for an amount due.
        payment_terms: BT-20, e.g. "Zahlbar innerhalb von 30 Tagen".
        delivery_date: BT-72, the date the work was done. This or
            ``service_period`` is required: § 14 UStG asks for the time of the
            service, and XRechnung warns without it (BR-DE-TMP-32).
        service_period: BG-14, ``(start, end)`` of the work billed, e.g. the
            month a progress invoice covers.
        vat_rate: VAT percentage for positions without their own. Without it the
            BoQ totals' rate applies.
        reverse_charge: Reverse charge under § 13b UStG (construction services
            to a construction business): category AE at 0 %. Needs both VAT IDs.
        prepaid_amount: BT-113, amounts already paid, e.g. earlier progress
            invoices; deducted from the amount due.
        unit_codes: Extra unit mappings to UN/ECE Recommendation 20 codes, for
            units pyGAEB does not know (``{"Fass": "BA"}``).
        strict: Raise instead of writing an invoice with problems.

    Returns:
        The problems that make the invoice invalid against XRechnung 3.0, or
        leave out what § 14 UStG requires, each naming the business term and
        the argument that fills it. Empty when every check passes.

    Raises:
        ValueError: If the document is not an X89/X89B invoice, or with
            ``strict=True`` when there are problems.
    """
    phase = doc.exchange_phase.normalized() if hasattr(
        doc.exchange_phase, "normalized",
    ) else doc.exchange_phase
    if phase not in (ExchangePhase.X89, ExchangePhase.X89B):
        raise ValueError(
            f"XRechnung export requires X89 invoice phase, got {phase.value}"
        )

    problems: list[str] = []

    if invoice_number is None:
        invoice_number = doc.award.project_no or "AUTO-INVOICE"
        problems.append(
            f"BT-1 invoice number (invoice_number) is missing; {invoice_number!r} stands in"
        )
    if issue_date is None:
        issue_date = date_type.today()

    currency = _currency(doc.award.currency)
    if currency is None:
        problems.append(
            f"BT-5 currency {doc.award.currency!r} is not an ISO 4217 code; EUR stands in"
        )
        currency = "EUR"

    contractor_address = doc.award.contractor.address if doc.award.contractor else None
    seller_party = _resolve(contractor_address, None, seller_name, seller)
    buyer_party = _resolve(doc.award.owner_address, doc.award.client, buyer_name, buyer)
    seller_endpoint = _endpoint(seller_party, None)
    buyer_endpoint = _endpoint(buyer_party, leitweg_id or None)

    default_rate = _default_vat_rate(doc, vat_rate)
    lines = _lines(doc, default_rate, reverse_charge, unit_codes or {}, problems)
    if default_rate is None and any(line.rate.is_nan() for line in lines):
        problems.append(
            "BT-152 VAT rate: neither the positions, the BoQ totals nor vat_rate give "
            "one; 19 % stands in"
        )
        for line in lines:
            if line.rate.is_nan():
                line.rate = Decimal(19)
    if not lines:
        problems.append("BR-16 the invoice has no lines: no position that counts has a total")

    line_total = sum((line.amount for line in lines), Decimal(0))
    groups: dict[tuple[str, Decimal], Decimal] = defaultdict(Decimal)
    for line in lines:
        groups[(line.category, line.rate)] += line.amount

    allowance = _allowance(doc, line_total, groups, problems)
    if allowance and len(groups) == 1:
        key = next(iter(groups))
        groups[key] -= allowance
    tax_exclusive = line_total - allowance
    taxes = {key: _money(taxable * key[1] / _HUNDRED) for key, taxable in groups.items()}
    tax_total = sum(taxes.values(), Decimal(0))
    tax_inclusive = tax_exclusive + tax_total
    payable = tax_inclusive - (prepaid_amount or Decimal(0))

    _check_parties(
        seller_party, buyer_party, seller_endpoint, buyer_endpoint, reverse_charge, problems,
    )
    if not leitweg_id:
        problems.append("BT-10 buyer reference (leitweg_id) is missing")
    if payment is None:
        problems.append("BG-16 payment instructions (payment) are missing")
    if payable > 0 and due_date is None and not payment_terms:
        problems.append(
            "BT-9/BT-20 a due date (due_date) or payment terms (payment_terms) are missing"
        )
    if delivery_date is None and service_period is None:
        problems.append(
            "BT-72/BG-14 a delivery date (delivery_date) or service period (service_period) "
            "is missing; § 14 UStG requires one and XRechnung warns (BR-DE-TMP-32)"
        )
    if service_period is not None and service_period[0] > service_period[1]:
        problems.append("BG-14 the service period ends before it starts (BR-29)")

    if problems and strict:
        raise ValueError(
            f"The XRechnung would be invalid ({len(problems)} problems): " + "; ".join(problems)
        )
    if problems:
        logger.warning(
            "XRechnung %s written with %d problems: %s",
            invoice_number, len(problems), "; ".join(problems),
        )

    root = etree.Element(f"{{{_UBL}}}Invoice", nsmap=NSMAP)  # type: ignore[arg-type]
    _add(root, _CBC, "CustomizationID", CUSTOMIZATION_ID)
    _add(root, _CBC, "ProfileID", PROFILE_ID)
    _add(root, _CBC, "ID", invoice_number)
    _add(root, _CBC, "IssueDate", issue_date.isoformat())
    if due_date is not None:
        _add(root, _CBC, "DueDate", due_date.isoformat())
    _add(root, _CBC, "InvoiceTypeCode", "380")  # commercial invoice
    _add(root, _CBC, "DocumentCurrencyCode", currency)
    if leitweg_id:
        _add(root, _CBC, "BuyerReference", leitweg_id)
    if service_period is not None:
        period = etree.SubElement(root, f"{{{_CAC}}}InvoicePeriod")
        _add(period, _CBC, "StartDate", service_period[0].isoformat())
        _add(period, _CBC, "EndDate", service_period[1].isoformat())
    if doc.award.contract_no:
        _add(etree.SubElement(root, f"{{{_CAC}}}ContractDocumentReference"),
             _CBC, "ID", doc.award.contract_no)
    if doc.award.project_no:
        _add(etree.SubElement(root, f"{{{_CAC}}}ProjectReference"),
             _CBC, "ID", doc.award.project_no)

    _add_party(root, "AccountingSupplierParty", seller_party, seller_endpoint, is_seller=True)
    _add_party(root, "AccountingCustomerParty", buyer_party, buyer_endpoint, is_seller=False)
    if delivery_date is not None:
        _add(etree.SubElement(root, f"{{{_CAC}}}Delivery"),
             _CBC, "ActualDeliveryDate", delivery_date.isoformat())

    if payment is not None:
        _add_payment(root, payment)
    if payment_terms:
        _add(etree.SubElement(root, f"{{{_CAC}}}PaymentTerms"), _CBC, "Note", payment_terms)

    if allowance:
        category, rate = next(iter(groups))
        charge = etree.SubElement(root, f"{{{_CAC}}}AllowanceCharge")
        _add(charge, _CBC, "ChargeIndicator", "false")
        _add(charge, _CBC, "AllowanceChargeReason", "Nachlass")
        _add(charge, _CBC, "Amount", _fmt_money(allowance), currencyID=currency)
        _add_tax_category(charge, "TaxCategory", category, rate)

    tax_total_el = etree.SubElement(root, f"{{{_CAC}}}TaxTotal")
    _add(tax_total_el, _CBC, "TaxAmount", _fmt_money(tax_total), currencyID=currency)
    for (category, rate), taxable in groups.items():
        subtotal = etree.SubElement(tax_total_el, f"{{{_CAC}}}TaxSubtotal")
        _add(subtotal, _CBC, "TaxableAmount", _fmt_money(taxable), currencyID=currency)
        _add(subtotal, _CBC, "TaxAmount", _fmt_money(taxes[(category, rate)]),
             currencyID=currency)
        _add_tax_category(subtotal, "TaxCategory", category, rate)

    totals = etree.SubElement(root, f"{{{_CAC}}}LegalMonetaryTotal")
    _add(totals, _CBC, "LineExtensionAmount", _fmt_money(line_total), currencyID=currency)
    _add(totals, _CBC, "TaxExclusiveAmount", _fmt_money(tax_exclusive), currencyID=currency)
    _add(totals, _CBC, "TaxInclusiveAmount", _fmt_money(tax_inclusive), currencyID=currency)
    if allowance:
        _add(totals, _CBC, "AllowanceTotalAmount", _fmt_money(allowance), currencyID=currency)
    if prepaid_amount:
        _add(totals, _CBC, "PrepaidAmount", _fmt_money(prepaid_amount), currencyID=currency)
    _add(totals, _CBC, "PayableAmount", _fmt_money(payable), currencyID=currency)

    for line in lines:
        line_el = etree.SubElement(root, f"{{{_CAC}}}InvoiceLine")
        _add(line_el, _CBC, "ID", line.line_id)
        _add(line_el, _CBC, "InvoicedQuantity", _fmt_number(line.qty), unitCode=line.unit_code)
        _add(line_el, _CBC, "LineExtensionAmount", _fmt_money(line.amount), currencyID=currency)
        item_el = etree.SubElement(line_el, f"{{{_CAC}}}Item")
        _add(item_el, _CBC, "Name", line.name)
        _add_tax_category(item_el, "ClassifiedTaxCategory", line.category, line.rate,
                          with_reason=False)
        price_el = etree.SubElement(line_el, f"{{{_CAC}}}Price")
        _add(price_el, _CBC, "PriceAmount", _fmt_number(line.price), currencyID=currency)

    etree.ElementTree(root).write(
        str(path), xml_declaration=True, encoding="utf-8", pretty_print=True,
    )
    return problems


def _lines(
    doc: GAEBDocument,
    default_rate: Decimal | None,
    reverse_charge: bool,
    unit_codes: dict[str, str],
    problems: list[str],
) -> list[_Line]:
    """One line per position that counts; NaN marks a rate still to be filled."""
    lines: list[_Line] = []
    seen: set[str] = set()
    unknown_units: dict[str, list[str]] = defaultdict(list)
    no_total: list[str] = []
    for index, item in enumerate(doc.iter_items(), start=1):
        if not isinstance(item, Item) or not item.affects_total:
            continue
        name = item.full_oz or item.oz or str(index)
        amount = item.total_price if item.total_price is not None else item.computed_total
        if amount is None:
            no_total.append(name)
            continue
        amount = _money(amount)

        is_markup = item.item_type is ItemType.MARKUP
        qty = Decimal(1) if is_markup or item.qty is None else item.qty
        unit = None if is_markup else item.unit
        code = "C62" if not unit else _unit_code(unit, unit_codes)
        if code is None:
            unknown_units[unit or ""].append(name)
            code = "C62"
        if is_markup or item.unit_price is None:
            price = amount / qty if qty else amount
        else:
            price = item.unit_price
        if price < 0:  # BR-27: a net price is never negative; the quantity carries the sign
            price, qty = -price, -qty

        if reverse_charge:
            category, rate = "AE", Decimal(0)
        else:
            rate = item.vat if item.vat is not None else (
                default_rate if default_rate is not None else Decimal("NaN")
            )
            category = "Z" if rate == 0 else "S"

        line_id = name if name not in seen else f"{name}-{index}"
        seen.add(line_id)
        lines.append(_Line(
            line_id=line_id,
            name=item.short_text or name,
            qty=qty,
            unit_code=code,
            amount=amount,
            price=price,
            category=category,
            rate=rate,
        ))

    for unit, names in unknown_units.items():
        problems.append(
            f"BT-130 unit {unit!r} has no UN/ECE code ({_sample(names)}); C62 stands in. "
            f"Pass unit_codes={{{unit!r}: '...'}}"
        )
    if no_total:
        problems.append(
            f"{len(no_total)} position(s) that count have no total and are not on the "
            f"invoice ({_sample(no_total)})"
        )
    return lines


def _allowance(
    doc: GAEBDocument,
    line_total: Decimal,
    groups: dict[tuple[str, Decimal], Decimal],
    problems: list[str],
) -> Decimal:
    """A BoQ-level discount as one document-level allowance (BG-20)."""
    info = doc.award.boq.boq_info
    totals = info.totals if info is not None else None
    if totals is None:
        return Decimal(0)
    if totals.discount_pcnt is not None:
        allowance = _money(line_total * totals.discount_pcnt / _HUNDRED)
    elif totals.discount_amt is not None:
        allowance = _money(totals.discount_amt)
    else:
        return Decimal(0)
    if len(groups) != 1:
        problems.append(
            "BG-20 the BoQ discount spans several VAT rates and is not on the invoice; "
            "give each position its discounted total instead"
        )
        return Decimal(0)
    return allowance


def _check_parties(
    seller: InvoiceParty,
    buyer: InvoiceParty,
    seller_endpoint: tuple[str, str] | None,
    buyer_endpoint: tuple[str, str] | None,
    reverse_charge: bool,
    problems: list[str],
) -> None:
    required: list[tuple[str, str, object]] = [
        ("BT-27", "seller name (seller.name)", seller.name),
        ("BT-37", "seller city (seller.city)", seller.city),
        ("BT-38", "seller post code (seller.postcode)", seller.postcode),
        ("BT-31/BT-32", "seller VAT ID or tax number (seller.vat_id, seller.tax_number)",
         seller.vat_id or seller.tax_number),
        ("BT-41", "seller contact name (seller.contact_name)", seller.contact_name),
        ("BT-42", "seller phone (seller.phone)", seller.phone),
        ("BT-43", "seller e-mail (seller.email)", seller.email),
        ("BT-34", "seller electronic address (seller.electronic_address or seller.email)",
         seller_endpoint),
        ("BT-44", "buyer name (buyer.name)", buyer.name),
        ("BT-52", "buyer city (buyer.city)", buyer.city),
        ("BT-53", "buyer post code (buyer.postcode)", buyer.postcode),
        ("BT-49", "buyer electronic address (buyer.electronic_address, leitweg_id or "
         "buyer.email)", buyer_endpoint),
    ]
    if reverse_charge:
        required.append(("BT-48", "buyer VAT ID for reverse charge (buyer.vat_id)", buyer.vat_id))
    for term, what, value in required:
        if not value:
            problems.append(f"{term} {what} is missing")
    for role, party in (("seller", seller), ("buyer", buyer)):
        if _country(party.country) is None:
            problems.append(
                f"BT-40/BT-55 {role} country {party.country!r} is not an ISO 3166 code; "
                f"DE stands in"
            )


def _resolve(
    address: Address | None,
    fallback_name: str | None,
    legacy_name: str,
    given: InvoiceParty | None,
) -> InvoiceParty:
    """The GAEB file's party, overridden field by field by the caller's."""
    data: dict[str, object] = {"name": fallback_name}
    if address is not None:
        data.update({
            "name": address.name or fallback_name,
            "street": address.street,
            "postcode": address.pcode,
            "city": address.city,
            "country": address.country,
            "vat_id": address.vat_id,
            "contact_name": address.contact,
            "phone": address.phone,
            "email": address.email,
        })
    if legacy_name:
        data["name"] = legacy_name
    if given is not None:
        data.update({
            key: value for key, value in given.model_dump(exclude_unset=True).items()
            if value is not None
        })
    return InvoiceParty.model_validate({k: v for k, v in data.items() if v is not None})


def _endpoint(party: InvoiceParty, leitweg_id: str | None) -> tuple[str, str] | None:
    """BT-34 / BT-49 as (address, EAS scheme): explicit, else Leitweg-ID, else e-mail."""
    if party.electronic_address:
        return party.electronic_address, party.electronic_address_scheme
    if leitweg_id:
        return leitweg_id, "0204"
    if party.email:
        return party.email, "EM"
    return None


def _default_vat_rate(doc: GAEBDocument, given: Decimal | None) -> Decimal | None:
    if given is not None:
        return given
    info = doc.award.boq.boq_info
    totals = info.totals if info is not None else None
    if totals is None:
        return None
    if totals.vat is not None:
        return totals.vat
    if len(totals.vat_parts) == 1:
        return totals.vat_parts[0].vat_pcnt
    return None


def _currency(raw: str | None) -> str | None:
    text = (raw or "EUR").strip()
    alias = _CURRENCY_ALIASES.get(text.upper())
    if alias:
        return alias
    if len(text) == 3 and text.isalpha():
        return text.upper()
    return None


def _country(raw: str | None) -> str | None:
    if not raw:
        return "DE"
    text = raw.strip().upper()
    if text in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[text]
    if len(text) == 2 and text.isalpha():
        return text
    return None


def _unit_code(unit: str, extra: dict[str, str]) -> str | None:
    """UN/ECE Recommendation 20 code for a GAEB unit, or None when unknown."""
    extra_folded = {k.casefold(): v for k, v in extra.items()}
    for candidate in (unit.strip(), normalize_unit(unit) or unit):
        code = (
            extra.get(candidate)
            or extra_folded.get(candidate.casefold())
            or _UNIT_CODES.get(candidate)
            or _UNIT_CODES_FOLDED.get(candidate.casefold())
        )
        if code:
            return code
    return None


def _add_party(
    root: etree._Element,
    tag: str,
    party: InvoiceParty,
    endpoint: tuple[str, str] | None,
    *,
    is_seller: bool,
) -> None:
    party_el = etree.SubElement(etree.SubElement(root, f"{{{_CAC}}}{tag}"), f"{{{_CAC}}}Party")
    if endpoint is not None:
        _add(party_el, _CBC, "EndpointID", endpoint[0], schemeID=endpoint[1])

    address = etree.SubElement(party_el, f"{{{_CAC}}}PostalAddress")
    if party.street:
        _add(address, _CBC, "StreetName", party.street)
    if party.city:
        _add(address, _CBC, "CityName", party.city)
    if party.postcode:
        _add(address, _CBC, "PostalZone", party.postcode)
    country = etree.SubElement(address, f"{{{_CAC}}}Country")
    _add(country, _CBC, "IdentificationCode", _country(party.country) or "DE")

    if party.vat_id:
        _add_tax_scheme(party_el, party.vat_id, "VAT")
    if is_seller and party.tax_number:
        _add_tax_scheme(party_el, party.tax_number, "FC")

    legal = etree.SubElement(party_el, f"{{{_CAC}}}PartyLegalEntity")
    _add(legal, _CBC, "RegistrationName", party.name or "")

    if party.contact_name or party.phone or party.email:
        contact = etree.SubElement(party_el, f"{{{_CAC}}}Contact")
        if party.contact_name:
            _add(contact, _CBC, "Name", party.contact_name)
        if party.phone:
            _add(contact, _CBC, "Telephone", party.phone)
        if party.email:
            _add(contact, _CBC, "ElectronicMail", party.email)


def _add_tax_scheme(party_el: etree._Element, company_id: str, scheme: str) -> None:
    tax_scheme = etree.SubElement(party_el, f"{{{_CAC}}}PartyTaxScheme")
    _add(tax_scheme, _CBC, "CompanyID", company_id)
    _add(etree.SubElement(tax_scheme, f"{{{_CAC}}}TaxScheme"), _CBC, "ID", scheme)


def _add_payment(root: etree._Element, payment: PaymentDetails) -> None:
    means = etree.SubElement(root, f"{{{_CAC}}}PaymentMeans")
    _add(means, _CBC, "PaymentMeansCode", payment.means_code)
    account = etree.SubElement(means, f"{{{_CAC}}}PayeeFinancialAccount")
    _add(account, _CBC, "ID", payment.iban.replace(" ", ""))
    if payment.account_name:
        _add(account, _CBC, "Name", payment.account_name)
    if payment.bic:
        branch = etree.SubElement(account, f"{{{_CAC}}}FinancialInstitutionBranch")
        _add(branch, _CBC, "ID", payment.bic)


def _add_tax_category(
    parent: etree._Element, tag: str, category: str, rate: Decimal, *, with_reason: bool = True,
) -> None:
    tax_category = etree.SubElement(parent, f"{{{_CAC}}}{tag}")
    _add(tax_category, _CBC, "ID", category)
    _add(tax_category, _CBC, "Percent", _fmt_number(rate))
    if category == "AE" and with_reason:
        _add(tax_category, _CBC, "TaxExemptionReasonCode", _REVERSE_CHARGE_CODE)
        _add(tax_category, _CBC, "TaxExemptionReason", _REVERSE_CHARGE_REASON)
    _add(etree.SubElement(tax_category, f"{{{_CAC}}}TaxScheme"), _CBC, "ID", "VAT")


def _money(value: Decimal) -> Decimal:
    """An amount to the cent, rounded half-up (EN 16931 allows two decimals)."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _fmt_money(value: Decimal) -> str:
    return format(_money(value), "f")


def _fmt_number(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral() else format(value, "f")


def _sample(names: list[str]) -> str:
    return ", ".join(names[:3]) + (", …" if len(names) > 3 else "")


def _add(parent: etree._Element, ns: str, tag: str, text: str, **attrs: str) -> etree._Element:
    """Helper: create a child element with text content and attributes."""
    el = etree.SubElement(parent, f"{{{ns}}}{tag}")
    el.text = text
    for k, v in attrs.items():
        el.set(k, v)
    return el


__all__ = ["CUSTOMIZATION_ID", "PROFILE_ID", "InvoiceParty", "PaymentDetails", "to_xrechnung"]
