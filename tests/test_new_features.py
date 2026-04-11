"""Tests for v1.13+ features: Editing API, Phase Transitions, REB Parsing.

Covers:
  - F2: In-place BoQ editing (add/remove/move items, recalculate totals)
  - F3: Phase transition helpers (tender->bid, contract->addendum/invoice)
  - F5: REB 23.003 takeoff row parsing (dimensions, formulas, computed qty)
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pygaeb import (
    ExchangePhase,
    GAEBParser,
    GAEBWriter,
    ItemType,
    SourceVersion,
)
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot, Totals
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.item import Item
from pygaeb.models.quantity import ParsedTakeoff, QTakeoffRow
from pygaeb.parser.reb_parser import parse_reb_row
from pygaeb.transition import PhaseTransition

# ── Helpers ──────────────────────────────────────────────────────────


def _make_doc(
    phase: ExchangePhase = ExchangePhase.X86,
    items: list[Item] | None = None,
    totals: Totals | None = None,
) -> GAEBDocument:
    if items is None:
        items = [
            Item(
                oz="01.0010", short_text="Mauerwerk KS 240mm",
                qty=Decimal("100"), unit="m2",
                unit_price=Decimal("45.50"),
                total_price=Decimal("4550.00"),
                item_type=ItemType.NORMAL,
            ),
            Item(
                oz="01.0020", short_text="Beton C25/30",
                qty=Decimal("50"), unit="m3",
                unit_price=Decimal("180.00"),
                total_price=Decimal("9000.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
    ctgy = BoQCtgy(rno="01", label="Rohbau", items=items, totals=totals)
    ctgy2 = BoQCtgy(rno="02", label="Ausbau", items=[])
    body = BoQBody(categories=[ctgy, ctgy2])
    lot = Lot(rno="1", label="Lot 1", body=body)
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=phase,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(
            project_no="P-TEST", currency="EUR",
            boq=BoQ(lots=[lot]),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# F2: In-Place Editing API
# ═══════════════════════════════════════════════════════════════════════


class TestBoQAddItem:
    def test_add_item_to_category(self) -> None:
        doc = _make_doc()
        boq = doc.award.boq
        item = boq.add_item(
            "01.0030", "01",
            short_text="Neues Mauerwerk",
            qty=Decimal("200"), unit="m2",
            unit_price=Decimal("50.00"),
            total_price=Decimal("10000.00"),
            item_type=ItemType.NORMAL,
        )
        assert item.oz == "01.0030"
        assert item.short_text == "Neues Mauerwerk"
        # Verify it's actually in the BoQ
        found = boq.get_item("01.0030")
        assert found is not None
        assert found.total_price == Decimal("10000.00")

    def test_add_item_to_empty_category(self) -> None:
        doc = _make_doc()
        boq = doc.award.boq
        boq.add_item(
            "02.0010", "02",
            short_text="Innentuer",
            item_type=ItemType.NORMAL,
        )
        assert boq.get_item("02.0010") is not None

    def test_add_item_nonexistent_category_raises(self) -> None:
        doc = _make_doc()
        import pytest
        with pytest.raises(ValueError, match="not found"):
            doc.award.boq.add_item("99.0010", "99", short_text="Orphan")

    def test_category_add_item_directly(self) -> None:
        doc = _make_doc()
        ctgy = doc.award.boq.lots[0].body.categories[0]
        item = ctgy.add_item(
            oz="01.0040", short_text="Direct add",
            item_type=ItemType.NORMAL,
        )
        assert item.oz == "01.0040"
        assert any(i.oz == "01.0040" for i in ctgy.items)


class TestBoQRemoveItem:
    def test_remove_existing_item(self) -> None:
        doc = _make_doc()
        boq = doc.award.boq
        removed = boq.remove_item("01.0010")
        assert removed is not None
        assert removed.oz == "01.0010"
        assert boq.get_item("01.0010") is None

    def test_remove_nonexistent_returns_none(self) -> None:
        doc = _make_doc()
        assert doc.award.boq.remove_item("99.9999") is None

    def test_remove_updates_count(self) -> None:
        doc = _make_doc()
        before = sum(1 for _ in doc.award.boq.iter_items())
        doc.award.boq.remove_item("01.0010")
        after = sum(1 for _ in doc.award.boq.iter_items())
        assert after == before - 1


class TestBoQMoveItem:
    def test_move_item_between_categories(self) -> None:
        doc = _make_doc()
        boq = doc.award.boq
        moved = boq.move_item("01.0020", "02")
        assert moved.oz == "01.0020"
        # Not in original category
        ctgy01 = boq.lots[0].body.categories[0]
        assert all(i.oz != "01.0020" for i in ctgy01.items)
        # In target category
        ctgy02 = boq.lots[0].body.categories[1]
        assert any(i.oz == "01.0020" for i in ctgy02.items)

    def test_move_nonexistent_item_raises(self) -> None:
        doc = _make_doc()
        import pytest
        with pytest.raises(ValueError, match="not found"):
            doc.award.boq.move_item("99.0010", "02")

    def test_move_to_nonexistent_category_raises(self) -> None:
        doc = _make_doc()
        import pytest
        with pytest.raises(ValueError, match="not found"):
            doc.award.boq.move_item("01.0010", "99")


class TestBoQRecalculateTotals:
    def test_recalculate_updates_category_totals(self) -> None:
        totals = Totals(total=Decimal("0"))
        doc = _make_doc(totals=totals)
        doc.award.boq.recalculate_totals()
        ctgy = doc.award.boq.lots[0].body.categories[0]
        assert ctgy.totals is not None
        assert ctgy.totals.total == Decimal("13550.00")

    def test_recalculate_after_add(self) -> None:
        totals = Totals(total=Decimal("13550.00"))
        doc = _make_doc(totals=totals)
        doc.award.boq.add_item(
            "01.0030", "01",
            short_text="New",
            qty=Decimal("10"), unit="m2",
            unit_price=Decimal("100"),
            total_price=Decimal("1000.00"),
            item_type=ItemType.NORMAL,
        )
        doc.award.boq.recalculate_totals()
        ctgy = doc.award.boq.lots[0].body.categories[0]
        assert ctgy.totals.total == Decimal("14550.00")

    def test_recalculate_after_remove(self) -> None:
        totals = Totals(total=Decimal("13550.00"))
        doc = _make_doc(totals=totals)
        doc.award.boq.remove_item("01.0020")
        doc.award.boq.recalculate_totals()
        ctgy = doc.award.boq.lots[0].body.categories[0]
        assert ctgy.totals.total == Decimal("4550.00")


class TestEditRoundTrip:
    def test_edit_and_write(self, tmp_path: Path) -> None:
        doc = _make_doc(phase=ExchangePhase.X83)
        doc.award.boq.add_item(
            "01.0030", "01",
            short_text="Zusaetzlich",
            qty=Decimal("25"), unit="Stk",
            unit_price=Decimal("100"),
            total_price=Decimal("2500.00"),
            item_type=ItemType.NORMAL,
        )
        out = tmp_path / "edited.X83"
        GAEBWriter.write(doc, out)
        doc2 = GAEBParser.parse(str(out))
        assert doc2.award.boq.get_item("01.0030") is not None
        assert doc2.award.boq.get_item("01.0030").total_price == Decimal("2500.00")


# ═══════════════════════════════════════════════════════════════════════
# F3: Phase Transition Helpers
# ═══════════════════════════════════════════════════════════════════════


class TestTenderToBid:
    def test_phase_changes_to_x84(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = PhaseTransition.tender_to_bid(tender)
        assert bid.exchange_phase == ExchangePhase.X84

    def test_original_unchanged(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        PhaseTransition.tender_to_bid(tender)
        assert tender.exchange_phase == ExchangePhase.X83

    def test_prices_cleared(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = PhaseTransition.tender_to_bid(tender)
        for item in bid.iter_items():
            assert item.unit_price is None
            assert item.total_price is None

    def test_structure_preserved(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = PhaseTransition.tender_to_bid(tender)
        tender_ozs = [i.oz for i in tender.iter_items()]
        bid_ozs = [i.oz for i in bid.iter_items()]
        assert tender_ozs == bid_ozs

    def test_quantities_preserved(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = PhaseTransition.tender_to_bid(tender)
        for t_item, b_item in zip(tender.iter_items(), bid.iter_items()):
            assert t_item.qty == b_item.qty

    def test_validation_results_cleared(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = PhaseTransition.tender_to_bid(tender)
        assert bid.validation_results == []

    def test_bid_round_trip(self, tmp_path: Path) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = PhaseTransition.tender_to_bid(tender)
        # Fill prices
        for item in bid.iter_items():
            item.unit_price = Decimal("99.00")
            item.total_price = item.qty * Decimal("99.00") if item.qty else None
        out = tmp_path / "bid.X84"
        GAEBWriter.write(bid, out, phase=ExchangePhase.X84)
        doc2 = GAEBParser.parse(str(out))
        assert doc2.exchange_phase == ExchangePhase.X84


class TestContractToAddendum:
    def test_phase_changes_to_x88(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        addendum = PhaseTransition.contract_to_addendum(contract, "NT-001")
        assert addendum.exchange_phase == ExchangePhase.X88

    def test_change_order_applied(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        addendum = PhaseTransition.contract_to_addendum(contract, "NT-001")
        for item in addendum.iter_items():
            assert item.change_order_number == "NT-001"

    def test_original_unchanged(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        PhaseTransition.contract_to_addendum(contract, "NT-001")
        for item in contract.iter_items():
            assert item.change_order_number is None

    def test_prices_preserved(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        addendum = PhaseTransition.contract_to_addendum(contract, "NT-001")
        for c_item, a_item in zip(contract.iter_items(), addendum.iter_items()):
            assert c_item.unit_price == a_item.unit_price


class TestContractToInvoice:
    def test_phase_changes_to_x89(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        invoice = PhaseTransition.contract_to_invoice(contract)
        assert invoice.exchange_phase == ExchangePhase.X89

    def test_prices_preserved(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        invoice = PhaseTransition.contract_to_invoice(contract)
        for c_item, i_item in zip(contract.iter_items(), invoice.iter_items()):
            assert c_item.unit_price == i_item.unit_price

    def test_quantities_carried_over(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        invoice = PhaseTransition.contract_to_invoice(contract)
        for c_item, i_item in zip(contract.iter_items(), invoice.iter_items()):
            assert c_item.qty == i_item.qty

    def test_invoice_round_trip(self, tmp_path: Path) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        invoice = PhaseTransition.contract_to_invoice(contract)
        out = tmp_path / "invoice.X89"
        GAEBWriter.write(invoice, out, phase=ExchangePhase.X89)
        doc2 = GAEBParser.parse(str(out))
        assert doc2.exchange_phase == ExchangePhase.X89


# ═══════════════════════════════════════════════════════════════════════
# F5: REB 23.003 Takeoff Row Parsing
# ═══════════════════════════════════════════════════════════════════════


class TestREBParserBasic:
    def test_multiplication_formula(self) -> None:
        result = parse_reb_row("Fundament A  5,00 * 3,20 * 0,75 = 12,000 m3")
        assert result.description == "Fundament A"
        assert len(result.dimensions) == 3
        assert result.dimensions[0] == Decimal("5.00")
        assert result.dimensions[1] == Decimal("3.20")
        assert result.dimensions[2] == Decimal("0.75")
        assert result.computed_qty == Decimal("12.000")
        assert result.unit == "m3"
        assert result.operator == "*"

    def test_two_dimensions(self) -> None:
        result = parse_reb_row("Wand Nord   12,50 * 3,00 = 37,500 m2")
        assert result.description == "Wand Nord"
        assert len(result.dimensions) == 2
        assert result.computed_qty == Decimal("37.500")
        assert result.unit == "m2"

    def test_single_quantity(self) -> None:
        result = parse_reb_row("Aushub 120,000 m3")
        assert result.description == "Aushub"
        assert result.computed_qty == Decimal("120.000")
        assert result.unit == "m3"

    def test_with_equals_sign(self) -> None:
        result = parse_reb_row("Pauschale = 1,000")
        assert result.computed_qty == Decimal("1.000")

    def test_empty_string(self) -> None:
        result = parse_reb_row("")
        assert result.computed_qty is None
        assert result.dimensions == []

    def test_pure_text(self) -> None:
        result = parse_reb_row("Bemerkung: Fundament Typ A")
        assert result.description == "Bemerkung: Fundament Typ A"

    def test_dot_decimal(self) -> None:
        result = parse_reb_row("Wall 5.00 * 3.20 = 16.000")
        assert len(result.dimensions) == 2
        assert result.computed_qty == Decimal("16.000")

    def test_computed_qty_matches_multiplication(self) -> None:
        result = parse_reb_row("Test 4,00 * 2,50 * 0,30")
        assert result.computed_qty is not None
        expected = Decimal("4.00") * Decimal("2.50") * Decimal("0.30")
        assert result.computed_qty == expected


class TestREBParserEdgeCases:
    def test_negative_dimension(self) -> None:
        result = parse_reb_row("Abzug Fenster -1,20 * 1,50 = -1,800 m2")
        assert Decimal("-1.20") in result.dimensions or Decimal("-1.800") == result.computed_qty

    def test_whitespace_only(self) -> None:
        result = parse_reb_row("   ")
        assert result.computed_qty is None

    def test_german_umlauts(self) -> None:
        result = parse_reb_row("Aussenwand Sued 10,00 * 3,00 = 30,000 m2")
        assert "Aussenwand" in result.description
        assert result.computed_qty == Decimal("30.000")


class TestQTakeoffRowParse:
    def test_parse_method(self) -> None:
        row = QTakeoffRow(raw="Fundament 5,00 * 3,00 = 15,000 m2")
        parsed = row.parse()
        assert isinstance(parsed, ParsedTakeoff)
        assert parsed.computed_qty == Decimal("15.000")
        assert row.parsed is parsed

    def test_parse_empty_row(self) -> None:
        row = QTakeoffRow(raw="")
        parsed = row.parse()
        assert parsed.computed_qty is None

    def test_parse_preserves_raw(self) -> None:
        raw = "Wand 10,00 * 3,00 = 30,000 m2"
        row = QTakeoffRow(raw=raw)
        row.parse()
        assert row.raw == raw  # Unchanged
