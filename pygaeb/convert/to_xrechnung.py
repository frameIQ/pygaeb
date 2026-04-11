"""XRechnung (UBL 2.1) export from GAEB X89 invoice documents.

XRechnung is the German national e-invoicing standard based on UBL 2.1.
This module maps a GAEB X89/X89B invoice into a minimal valid
XRechnung XML document suitable for submission to public authority
e-invoicing portals.

Note: This is a basic mapping. Production use should be validated
against the official XRechnung schematron rules
(https://github.com/itplr-kosit/xrechnung-schematron).

Usage::

    from pygaeb import GAEBParser
    from pygaeb.convert.to_xrechnung import to_xrechnung

    invoice = GAEBParser.parse("invoice.X89")
    to_xrechnung(invoice, "invoice_xrechnung.xml")
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from pathlib import Path

from lxml import etree

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase

# UBL namespaces
_UBL = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

NSMAP = {None: _UBL, "cac": _CAC, "cbc": _CBC}


def to_xrechnung(
    doc: GAEBDocument,
    path: str | Path,
    *,
    invoice_number: str | None = None,
    issue_date: date_type | None = None,
    seller_name: str = "",
    buyer_name: str = "",
    leitweg_id: str = "",
) -> None:
    """Export a GAEB X89 invoice as an XRechnung-compliant UBL 2.1 invoice.

    Args:
        doc: A parsed GAEB document with phase X89 or X89B.
        path: Output file path (.xml).
        invoice_number: Invoice number (defaults to project_no or "AUTO").
        issue_date: Invoice issue date (defaults to today).
        seller_name: Seller (contractor) legal name.
        buyer_name: Buyer (owner) legal name.
        leitweg_id: Buyer reference / Leitweg-ID required for German
            public authorities.

    Raises:
        ValueError: If the document is not an X89/X89B invoice.
    """
    phase = doc.exchange_phase.normalized() if hasattr(
        doc.exchange_phase, "normalized",
    ) else doc.exchange_phase
    if phase not in (ExchangePhase.X89, ExchangePhase.X89B):
        raise ValueError(
            f"XRechnung export requires X89 invoice phase, got {phase.value}"
        )

    if issue_date is None:
        issue_date = date_type.today()

    if invoice_number is None:
        invoice_number = doc.award.project_no or "AUTO-INVOICE"

    if not seller_name:
        seller_name = "Auftragnehmer"
    if not buyer_name:
        buyer_name = doc.award.client or "Auftraggeber"

    root = etree.Element(f"{{{_UBL}}}Invoice", nsmap=NSMAP)  # type: ignore[arg-type]

    _add(root, _CBC, "CustomizationID",
         "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.0")
    _add(root, _CBC, "ID", invoice_number)
    _add(root, _CBC, "IssueDate", issue_date.isoformat())
    _add(root, _CBC, "InvoiceTypeCode", "380")  # Commercial invoice
    _add(root, _CBC, "DocumentCurrencyCode", doc.award.currency or "EUR")
    if leitweg_id:
        _add(root, _CBC, "BuyerReference", leitweg_id)

    # Seller (contractor)
    seller_party = etree.SubElement(root, f"{{{_CAC}}}AccountingSupplierParty")
    seller_inner = etree.SubElement(seller_party, f"{{{_CAC}}}Party")
    seller_legal = etree.SubElement(seller_inner, f"{{{_CAC}}}PartyLegalEntity")
    _add(seller_legal, _CBC, "RegistrationName", seller_name)

    # Buyer (owner)
    buyer_party = etree.SubElement(root, f"{{{_CAC}}}AccountingCustomerParty")
    buyer_inner = etree.SubElement(buyer_party, f"{{{_CAC}}}Party")
    buyer_legal = etree.SubElement(buyer_inner, f"{{{_CAC}}}PartyLegalEntity")
    _add(buyer_legal, _CBC, "RegistrationName", buyer_name)

    # Tax totals (placeholder — assumes single 19% German rate)
    grand_total = doc.grand_total or Decimal("0")
    vat_rate = Decimal("19")
    vat_amount = (grand_total * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    gross_total = grand_total + vat_amount

    tax_total = etree.SubElement(root, f"{{{_CAC}}}TaxTotal")
    _add(tax_total, _CBC, "TaxAmount", str(vat_amount), currencyID="EUR")
    tax_subtotal = etree.SubElement(tax_total, f"{{{_CAC}}}TaxSubtotal")
    _add(tax_subtotal, _CBC, "TaxableAmount", str(grand_total), currencyID="EUR")
    _add(tax_subtotal, _CBC, "TaxAmount", str(vat_amount), currencyID="EUR")
    tax_category = etree.SubElement(tax_subtotal, f"{{{_CAC}}}TaxCategory")
    _add(tax_category, _CBC, "ID", "S")
    _add(tax_category, _CBC, "Percent", str(vat_rate))
    tax_scheme = etree.SubElement(tax_category, f"{{{_CAC}}}TaxScheme")
    _add(tax_scheme, _CBC, "ID", "VAT")

    # Monetary totals
    legal_total = etree.SubElement(root, f"{{{_CAC}}}LegalMonetaryTotal")
    _add(legal_total, _CBC, "LineExtensionAmount", str(grand_total), currencyID="EUR")
    _add(legal_total, _CBC, "TaxExclusiveAmount", str(grand_total), currencyID="EUR")
    _add(legal_total, _CBC, "TaxInclusiveAmount", str(gross_total), currencyID="EUR")
    _add(legal_total, _CBC, "PayableAmount", str(gross_total), currencyID="EUR")

    # Invoice lines (one per BoQ item)
    for idx, item in enumerate(doc.iter_items(), start=1):
        if item.total_price is None:
            continue
        line = etree.SubElement(root, f"{{{_CAC}}}InvoiceLine")
        _add(line, _CBC, "ID", str(idx))
        if item.qty is not None:
            qty_el = etree.SubElement(line, f"{{{_CBC}}}InvoicedQuantity")
            qty_el.set("unitCode", _ubl_unit(item.unit))
            qty_el.text = str(item.qty)
        _add(line, _CBC, "LineExtensionAmount",
             str(item.total_price), currencyID="EUR")
        item_el = etree.SubElement(line, f"{{{_CAC}}}Item")
        _add(item_el, _CBC, "Name", (item.short_text or item.oz)[:200])
        item_tax = etree.SubElement(item_el, f"{{{_CAC}}}ClassifiedTaxCategory")
        _add(item_tax, _CBC, "ID", "S")
        _add(item_tax, _CBC, "Percent", str(vat_rate))
        item_scheme = etree.SubElement(item_tax, f"{{{_CAC}}}TaxScheme")
        _add(item_scheme, _CBC, "ID", "VAT")
        if item.unit_price is not None:
            price_el = etree.SubElement(line, f"{{{_CAC}}}Price")
            _add(price_el, _CBC, "PriceAmount",
                 str(item.unit_price), currencyID="EUR")

    tree = etree.ElementTree(root)
    tree.write(
        str(path),
        xml_declaration=True,
        encoding="utf-8",
        pretty_print=True,
    )


def _add(parent: etree._Element, ns: str, tag: str, text: str, **attrs: str) -> etree._Element:
    """Helper: create a child element with text content and attributes."""
    el = etree.SubElement(parent, f"{{{ns}}}{tag}")
    el.text = text
    for k, v in attrs.items():
        el.set(k, v)
    return el


def _ubl_unit(unit: str | None) -> str:
    """Map a GAEB unit string to a UN/ECE Recommendation 20 unit code."""
    if not unit:
        return "C62"  # one (default)
    mapping = {
        "m": "MTR", "m²": "MTK", "m2": "MTK",
        "m³": "MTQ", "m3": "MTQ",
        "kg": "KGM", "t": "TNE",
        "Stk": "H87", "h": "HUR",
        "lfm": "MTR", "psch": "LS",
    }
    return mapping.get(unit, "C62")


__all__ = ["to_xrechnung"]
