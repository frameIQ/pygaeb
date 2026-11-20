"""XRechnung 3.0 export: what the GAEB file gives, what the caller adds, and
every missing mandatory field named."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from pygaeb.convert.to_xrechnung import (
    CUSTOMIZATION_ID,
    PROFILE_ID,
    InvoiceParty,
    PaymentDetails,
    to_xrechnung,
)
from pygaeb.models.boq import BoQInfo, Totals
from pygaeb.models.document import GAEBDocument, Party
from pygaeb.models.enums import ExchangePhase, ItemType, Provis
from pygaeb.models.item import Item
from pygaeb.models.order import Address
from pygaeb.parser._xml_safety import SAFE_PARSER
from tests.test_tier23_features import _make_doc

NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

SELLER = InvoiceParty(
    name="Acme Bau GmbH", street="Hauptstr. 1", postcode="10115", city="Berlin",
    vat_id="DE123456789", contact_name="Anna Bau", phone="+49 30 23125 000",
    email="rechnung@acme.example",
)
BUYER = InvoiceParty(name="Stadt Musterstadt", postcode="12345", city="Musterstadt")
COMPLETE: dict[str, Any] = {
    "invoice_number": "R-2026-1",
    "leitweg_id": "04011000-12345-03",
    "seller": SELLER,
    "buyer": BUYER,
    "payment": PaymentDetails(iban="DE89 3704 0044 0532 0130 00"),
    "payment_terms": "Zahlbar innerhalb von 30 Tagen",
    "service_period": (date(2026, 10, 1), date(2026, 10, 31)),
    "vat_rate": Decimal("19"),
}

# The KoSIT validator jar and its unpacked XRechnung configuration folder.
_KOSIT_JAR = os.environ.get("PYGAEB_KOSIT_JAR")
_KOSIT_CONFIG = os.environ.get("PYGAEB_KOSIT_CONFIG")
# KoSIT's report format: rep:assessment/rep:accept, and one rep:message per finding.
_VARL = "http://www.xoev.de/de/validator/varl/1"


def _x89() -> GAEBDocument:
    # Two positions: 100 m2 at 45.50 (4550.00) and 50 m3 at 180.00 (9000.00).
    return _make_doc(phase=ExchangePhase.X89)


def _invoice(
    tmp_path: Path, doc: GAEBDocument | None = None, **changes: Any,
) -> tuple[list[str], etree._Element]:
    out = tmp_path / "invoice.xml"
    problems = to_xrechnung(doc or _x89(), out, **{**COMPLETE, **changes})
    return problems, etree.parse(str(out)).getroot()


def _text(root: etree._Element, path: str) -> str | None:
    return root.findtext(path, namespaces=NS)


def _texts(root: etree._Element, path: str) -> list[str]:
    return [e.text or "" for e in root.findall(path, namespaces=NS)]


def _items(doc: GAEBDocument) -> list[Item]:
    return doc.award.boq.lots[0].body.categories[0].items


class TestCompleteInvoice:
    def test_has_no_problems_and_names_xrechnung_3(self, tmp_path: Path) -> None:
        problems, root = _invoice(tmp_path)
        assert problems == []
        assert _text(root, "cbc:CustomizationID") == CUSTOMIZATION_ID
        assert _text(root, "cbc:ProfileID") == PROFILE_ID
        assert "xrechnung_3.0" in CUSTOMIZATION_ID

    def test_carries_both_electronic_addresses(self, tmp_path: Path) -> None:
        _, root = _invoice(tmp_path)
        seller = root.find("cac:AccountingSupplierParty/cac:Party/cbc:EndpointID", NS)
        buyer = root.find("cac:AccountingCustomerParty/cac:Party/cbc:EndpointID", NS)
        assert seller is not None and buyer is not None
        assert (seller.text, seller.get("schemeID")) == ("rechnung@acme.example", "EM")
        # A public client's Leitweg-ID doubles as its electronic address.
        assert (buyer.text, buyer.get("schemeID")) == ("04011000-12345-03", "0204")

    def test_totals_add_up(self, tmp_path: Path) -> None:
        _, root = _invoice(tmp_path)
        totals = "cac:LegalMonetaryTotal/cbc:"
        assert _text(root, totals + "LineExtensionAmount") == "13550.00"
        assert _text(root, "cac:TaxTotal/cbc:TaxAmount") == "2574.50"
        assert _text(root, totals + "PayableAmount") == "16124.50"

    def test_iban_is_written_without_spaces(self, tmp_path: Path) -> None:
        _, root = _invoice(tmp_path)
        iban = _text(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID")
        assert iban == "DE89370400440532013000"


class TestProblems:
    def test_each_missing_input_is_named(self, tmp_path: Path) -> None:
        out = tmp_path / "invoice.xml"
        problems = to_xrechnung(_x89(), out)
        for term in ("BT-1 ", "BT-10 ", "BT-27 ", "BT-31/BT-32 ", "BT-34 ", "BT-43 ",
                     "BT-44 ", "BT-49 ", "BG-16 ", "BT-9/BT-20 ", "BT-72/BG-14 ", "BT-152 "):
            assert any(p.startswith(term) for p in problems), term
        assert out.exists()  # written anyway unless strict

    def test_strict_raises_before_writing(self, tmp_path: Path) -> None:
        out = tmp_path / "invoice.xml"
        with pytest.raises(ValueError, match="BT-34"):
            to_xrechnung(_x89(), out, strict=True)
        assert not out.exists()

    def test_requires_an_invoice(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="X89"):
            to_xrechnung(_make_doc(phase=ExchangePhase.X86), tmp_path / "out.xml")


class TestServiceDate:
    """§ 14 UStG asks for the time of the service; XRechnung warns without it."""

    def test_the_service_period_is_written(self, tmp_path: Path) -> None:
        _, root = _invoice(tmp_path)
        assert _text(root, "cac:InvoicePeriod/cbc:StartDate") == "2026-10-01"
        assert _text(root, "cac:InvoicePeriod/cbc:EndDate") == "2026-10-31"

    def test_a_delivery_date_serves_as_well(self, tmp_path: Path) -> None:
        problems, root = _invoice(
            tmp_path, service_period=None, delivery_date=date(2026, 10, 15),
        )
        assert problems == []
        assert _text(root, "cac:Delivery/cbc:ActualDeliveryDate") == "2026-10-15"

    def test_neither_is_a_problem(self, tmp_path: Path) -> None:
        problems, _ = _invoice(tmp_path, service_period=None)
        assert any(p.startswith("BT-72/BG-14 ") for p in problems)

    def test_a_period_that_ends_before_it_starts_is_a_problem(self, tmp_path: Path) -> None:
        problems, _ = _invoice(tmp_path, service_period=(date(2026, 10, 31), date(2026, 10, 1)))
        assert any("BR-29" in p for p in problems)


class TestVat:
    def test_rates_come_from_the_positions(self, tmp_path: Path) -> None:
        doc = _x89()
        _items(doc)[0].vat = Decimal("7")
        _items(doc)[1].vat = Decimal("19")
        problems, root = _invoice(tmp_path, doc, vat_rate=None)
        assert problems == []
        rates = _texts(root, "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent")
        amounts = _texts(root, "cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount")
        assert dict(zip(rates, amounts, strict=True)) == {"7": "318.50", "19": "1710.00"}
        assert _text(root, "cac:TaxTotal/cbc:TaxAmount") == "2028.50"

    def test_the_boq_totals_give_the_default_rate(self, tmp_path: Path) -> None:
        doc = _x89()
        doc.award.boq.boq_info = BoQInfo(totals=Totals(vat=Decimal("19")))
        problems, root = _invoice(tmp_path, doc, vat_rate=None)
        assert problems == []
        assert _texts(root, ".//cac:ClassifiedTaxCategory/cbc:Percent") == ["19", "19"]

    def test_reverse_charge_is_category_ae_without_tax(self, tmp_path: Path) -> None:
        buyer = BUYER.model_copy(update={"vat_id": "DE987654321"})
        problems, root = _invoice(tmp_path, reverse_charge=True, buyer=buyer)
        assert problems == []
        category = root.find("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory", NS)
        assert category is not None
        assert _text(category, "cbc:ID") == "AE"
        assert _text(category, "cbc:TaxExemptionReasonCode") == "VATEX-EU-AE"
        assert _text(root, "cac:TaxTotal/cbc:TaxAmount") == "0.00"

    def test_reverse_charge_needs_the_buyer_vat_id(self, tmp_path: Path) -> None:
        problems, _ = _invoice(tmp_path, reverse_charge=True)
        assert any(p.startswith("BT-48 ") for p in problems)


class TestLines:
    def test_only_positions_that_count_become_lines(self, tmp_path: Path) -> None:
        doc = _x89()
        _items(doc).extend([
            Item(oz="01.0030", short_text="Alternative", qty=Decimal("1"), unit="Stk",
                 unit_price=Decimal("10"), total_price=Decimal("10.00"),
                 item_type=ItemType.ALTERNATIVE),
            Item(oz="01.0040", short_text="Bedarf ohne GB", qty=Decimal("1"), unit="Stk",
                 unit_price=Decimal("10"), total_price=Decimal("10.00"),
                 item_type=ItemType.EVENTUAL, provis=Provis.WITHOUT_TOTAL),
            Item(oz="01.0050", short_text="Entfällt", qty=Decimal("1"), unit="Stk",
                 unit_price=Decimal("10"), total_price=Decimal("10.00"), not_applicable=True),
            Item(oz="01.0060", short_text="Zuschlag", unit_price=Decimal("10"),
                 total_price=Decimal("100.00"), item_type=ItemType.MARKUP),
        ])
        _, root = _invoice(tmp_path, doc)
        assert _texts(root, "cac:InvoiceLine/cbc:ID") == ["01.0010", "01.0020", "01.0060"]
        markup = root.findall("cac:InvoiceLine", NS)[-1]
        quantity = markup.find("cbc:InvoicedQuantity", NS)
        assert quantity is not None
        assert (quantity.text, quantity.get("unitCode")) == ("1", "C62")
        assert _text(markup, "cac:Price/cbc:PriceAmount") == "100"

    def test_a_negative_amount_keeps_a_positive_price(self, tmp_path: Path) -> None:
        # BR-27: the net price is never negative; the quantity carries the sign.
        doc = _x89()
        _items(doc).append(Item(oz="01.0070", short_text="Nachlass-Zuschlag",
                                total_price=Decimal("-50.00"), item_type=ItemType.MARKUP))
        _, root = _invoice(tmp_path, doc)
        line = root.findall("cac:InvoiceLine", NS)[-1]
        assert _text(line, "cbc:InvoicedQuantity") == "-1"
        assert _text(line, "cac:Price/cbc:PriceAmount") == "50"
        assert _text(line, "cbc:LineExtensionAmount") == "-50.00"

    def test_units_map_to_un_ece_codes(self, tmp_path: Path) -> None:
        doc = _x89()
        _items(doc)[0].unit = "psch"
        _items(doc)[1].unit = "Stk"
        _, root = _invoice(tmp_path, doc)
        units = [e.get("unitCode") for e in root.findall(".//cbc:InvoicedQuantity", NS)]
        assert units == ["LS", "H87"]

    def test_an_unknown_unit_is_a_problem_until_mapped(self, tmp_path: Path) -> None:
        doc = _x89()
        _items(doc)[0].unit = "Fass"
        problems, _ = _invoice(tmp_path, doc)
        assert any(p.startswith("BT-130 unit 'Fass'") for p in problems)
        problems, root = _invoice(tmp_path, doc, unit_codes={"Fass": "BA"})
        assert problems == []
        assert root.findall(".//cbc:InvoicedQuantity", NS)[0].get("unitCode") == "BA"


class TestAmounts:
    def test_a_currency_symbol_becomes_its_iso_code(self, tmp_path: Path) -> None:
        doc = _x89()
        doc.award.currency = "€"
        problems, root = _invoice(tmp_path, doc)
        assert problems == []
        assert _text(root, "cbc:DocumentCurrencyCode") == "EUR"

    def test_a_boq_discount_becomes_an_allowance(self, tmp_path: Path) -> None:
        doc = _x89()
        doc.award.boq.boq_info = BoQInfo(totals=Totals(discount_pcnt=Decimal("3")))
        _, root = _invoice(tmp_path, doc)
        totals = "cac:LegalMonetaryTotal/cbc:"
        assert _text(root, "cac:AllowanceCharge/cbc:Amount") == "406.50"  # 3 % of 13550.00
        assert _text(root, totals + "TaxExclusiveAmount") == "13143.50"
        # 13143.50 x 19 % = 2497.265, rounded half-up to the cent.
        assert _text(root, "cac:TaxTotal/cbc:TaxAmount") == "2497.27"
        assert _text(root, totals + "PayableAmount") == "15640.77"

    def test_a_prepaid_amount_is_deducted(self, tmp_path: Path) -> None:
        _, root = _invoice(tmp_path, prepaid_amount=Decimal("10000"))
        totals = "cac:LegalMonetaryTotal/cbc:"
        assert _text(root, totals + "PrepaidAmount") == "10000.00"
        assert _text(root, totals + "PayableAmount") == "6124.50"


class TestParties:
    def test_the_gaeb_file_supplies_the_parties(self, tmp_path: Path) -> None:
        doc = _x89()
        doc.award.contractor = Party(address=Address(
            name="Bau GmbH", street="Ringstr. 5", pcode="50667", city="Köln",
            vat_id="DE111111111", contact="Max Bau", phone="+49 221 1", email="re@bau.example",
        ))
        doc.award.owner_address = Address(
            name="Stadt Beispielstadt", pcode="54321", city="Beispielstadt",
        )
        problems, root = _invoice(tmp_path, doc, seller=None, buyer=None)
        assert problems == []
        names = _texts(root, ".//cac:PartyLegalEntity/cbc:RegistrationName")
        assert names == ["Bau GmbH", "Stadt Beispielstadt"]

    def test_the_caller_overrides_the_file_field_by_field(self, tmp_path: Path) -> None:
        doc = _x89()
        doc.award.contractor = Party(address=Address(name="Bau GmbH", city="Köln"))
        _, root = _invoice(tmp_path, doc, seller=InvoiceParty(city="Bonn"))
        party = "cac:AccountingSupplierParty/cac:Party/"
        assert _text(root, party + "cac:PartyLegalEntity/cbc:RegistrationName") == "Bau GmbH"
        assert _text(root, party + "cac:PostalAddress/cbc:CityName") == "Bonn"


def _kosit_variants() -> dict[str, tuple[GAEBDocument, dict[str, Any]]]:
    """One invoice per feature, each expected to pass KoSIT without a finding."""
    mixed_vat = _x89()
    _items(mixed_vat)[0].vat = Decimal("7")
    _items(mixed_vat)[1].vat = Decimal("19")
    line_kinds = _x89()
    _items(line_kinds)[0].unit = "psch"
    _items(line_kinds)[1].unit = "Stk"
    _items(line_kinds).extend([
        Item(oz="01.0030", short_text="Alternative", qty=Decimal("1"), unit="Stk",
             unit_price=Decimal("10"), total_price=Decimal("10.00"),
             item_type=ItemType.ALTERNATIVE),
        Item(oz="01.0040", short_text="Entfällt", qty=Decimal("1"), unit="Stk",
             unit_price=Decimal("10"), total_price=Decimal("10.00"), not_applicable=True),
        Item(oz="01.0050", short_text="Zuschlag", total_price=Decimal("100.00"),
             item_type=ItemType.MARKUP),
        Item(oz="01.0060", short_text="Nachlass", total_price=Decimal("-50.00"),
             item_type=ItemType.MARKUP),
    ])
    discounted = _x89()
    discounted.award.boq.boq_info = BoQInfo(totals=Totals(discount_pcnt=Decimal("3")))
    parties_in_file = _x89()
    parties_in_file.award.contractor = Party(address=Address(
        name="Bau GmbH", street="Ringstr. 5", pcode="50667", city="Köln",
        vat_id="DE111111111", contact="Max Bau", phone="+49 221 1", email="re@bau.example",
    ))
    parties_in_file.award.owner_address = Address(
        name="Stadt Beispielstadt", pcode="54321", city="Beispielstadt",
    )
    buyer_with_vat_id = BUYER.model_copy(update={"vat_id": "DE987654321"})
    return {
        "complete": (_x89(), {}),
        "delivery-date": (_x89(), {"service_period": None, "delivery_date": date(2026, 10, 15)}),
        "due-date": (_x89(), {"payment_terms": None, "due_date": date(2026, 11, 30)}),
        "mixed-vat": (mixed_vat, {"vat_rate": None}),
        "reverse-charge": (_x89(), {"reverse_charge": True, "buyer": buyer_with_vat_id}),
        "line-kinds": (line_kinds, {}),
        "discount-and-prepaid": (discounted, {"prepaid_amount": Decimal("10000")}),
        "parties-in-file": (parties_in_file, {"seller": None, "buyer": None}),
    }


@pytest.mark.skipif(
    not (_KOSIT_JAR and _KOSIT_CONFIG and shutil.which("java")),
    reason="set PYGAEB_KOSIT_JAR and PYGAEB_KOSIT_CONFIG to run the KoSIT validator",
)
def test_the_kosit_validator_accepts_every_variant_without_findings(tmp_path: Path) -> None:
    assert _KOSIT_JAR is not None and _KOSIT_CONFIG is not None
    variants = _kosit_variants()
    for name, (doc, changes) in variants.items():
        problems = to_xrechnung(doc, tmp_path / f"{name}.xml", **{**COMPLETE, **changes})
        assert problems == [], name
    config = Path(_KOSIT_CONFIG)
    # One run for all files: starting the JVM takes longer than validating them.
    result = subprocess.run(
        ["java", "-jar", _KOSIT_JAR, "-s", str(config / "scenarios.xml"), "-r", str(config),
         "-o", str(tmp_path), *(str(tmp_path / f"{name}.xml") for name in variants)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    findings: dict[str, list[str]] = {}
    for name in variants:
        report = tmp_path / f"{name}-report.xml"
        assert report.exists(), result.stdout[-3000:] + result.stderr[-3000:]
        root = etree.parse(str(report), SAFE_PARSER).getroot()
        # Accepted is not enough: a warning such as BR-DE-TMP-32 is a message as well.
        messages = [f"{m.get('level')} {m.get('code')}" for m in root.iter(f"{{{_VARL}}}message")]
        if root.find("rep:assessment/rep:accept", {"rep": _VARL}) is None:
            messages.insert(0, "rejected")
        if messages:
            findings[name] = messages
    assert findings == {}
