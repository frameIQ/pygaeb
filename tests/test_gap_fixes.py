"""Tests for gap analysis fixes (v1.12.0).

Covers:
  - P0.1: X80 phase validation bug fix (no longer requires quantity)
  - P0.4: Section/lot total validation (declared vs computed)
  - P0.5: X88 (Nachtrag/Claims) exchange phase support
  - P1.1: GAEB precision limit validation
  - P1.2: Cross-phase validation X86->X89 (unit price match)
  - P1.2: Cross-phase validation X86->X88 (addendum traceability)
  - P1.3: Alternative item total exclusion validation
  - P1.4: Writer up_frac_dig formatting
  - P1.5: SQLiteCache file permissions
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

from pygaeb import (
    ExchangePhase,
    GAEBParser,
    GAEBWriter,
    ItemType,
    SourceVersion,
)
from pygaeb.models.boq import (
    BoQ,
    BoQBkdn,
    BoQBody,
    BoQCtgy,
    BoQInfo,
    Lot,
    Totals,
)
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import BkdnType, ValidationSeverity
from pygaeb.models.item import Item
from pygaeb.validation.cross_phase_validator import CrossPhaseValidator
from pygaeb.validation.numeric_validator import (
    _decimal_places,
    _pre_decimal_digits,
    validate_numerics,
)
from pygaeb.validation.totals_validator import validate_totals

# ── Helpers ──────────────────────────────────────────────────────────


def _make_doc(
    phase: ExchangePhase = ExchangePhase.X86,
    items: list[Item] | None = None,
    totals: Totals | None = None,
    up_frac_dig: int | None = None,
) -> GAEBDocument:
    """Build a minimal procurement GAEBDocument for testing."""
    if items is None:
        items = [
            Item(
                oz="01.0010",
                short_text="Mauerwerk KS 240mm",
                qty=Decimal("100"),
                unit="m2",
                unit_price=Decimal("45.50"),
                total_price=Decimal("4550.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
    ctgy = BoQCtgy(rno="01", label="Rohbau", items=items, totals=totals)
    body = BoQBody(categories=[ctgy])
    boq_info = BoQInfo(
        name="Test",
        bkdn=[
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.ITEM, length=4),
        ],
    )
    lot = Lot(rno="1", label="Lot 1", body=body)
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=phase,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(
            project_no="P-TEST",
            currency="EUR",
            boq=BoQ(boq_info=boq_info, lots=[lot]),
            up_frac_dig=up_frac_dig,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# P0.1: X80 Phase Validation — No False Positives
# ═══════════════════════════════════════════════════════════════════════


class TestX80PhaseValidation:
    """X80 (BoQ Catalogue) should NOT require quantity on items."""

    def test_x80_no_qty_no_warning(self) -> None:
        """Items in X80 without quantity must not trigger validation warnings."""
        items = [
            Item(
                oz="01.0010",
                short_text="Mauerwerk KS 240mm Katalogposition",
                qty=None,
                unit=None,
                unit_price=None,
                total_price=None,
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(phase=ExchangePhase.X80, items=items)
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA80/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P1</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Cat</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Katalogposition ohne Menge</ShortText>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="catalog.X80")
        qty_warnings = [
            r for r in doc.validation_results
            if "Quantity expected" in r.message and "X80" in r.message
        ]
        assert len(qty_warnings) == 0, (
            f"X80 should not require quantity, but got: {qty_warnings}"
        )

    def test_x83_still_requires_qty(self) -> None:
        """X83 (tender) should still warn when quantity is missing."""
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P1</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Cat</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Tender item without qty</ShortText>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="tender.X83")
        qty_warnings = [
            r for r in doc.validation_results
            if "Quantity expected" in r.message
        ]
        assert len(qty_warnings) > 0, "X83 should still warn when qty is missing"


# ═══════════════════════════════════════════════════════════════════════
# P0.4: Section/Lot Total Validation
# ═══════════════════════════════════════════════════════════════════════


class TestTotalsValidation:
    """Validate declared XML totals against computed subtotals."""

    def test_matching_totals_no_warning(self) -> None:
        items = [
            Item(oz="01.0010", short_text="A", qty=Decimal("10"),
                 unit="m2", unit_price=Decimal("10"), total_price=Decimal("100"),
                 item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="B", qty=Decimal("5"),
                 unit="m2", unit_price=Decimal("20"), total_price=Decimal("100"),
                 item_type=ItemType.NORMAL),
        ]
        totals = Totals(total=Decimal("200.00"))
        doc = _make_doc(items=items, totals=totals)
        results = validate_totals(doc)
        mismatch = [r for r in results if "mismatch" in r.message]
        assert len(mismatch) == 0

    def test_mismatched_category_total_warns(self) -> None:
        items = [
            Item(oz="01.0010", short_text="A", qty=Decimal("10"),
                 unit="m2", unit_price=Decimal("10"), total_price=Decimal("100"),
                 item_type=ItemType.NORMAL),
        ]
        # Declared total is 999, computed is 100
        totals = Totals(total=Decimal("999.00"))
        doc = _make_doc(items=items, totals=totals)
        results = validate_totals(doc)
        mismatch = [r for r in results if "mismatch" in r.message]
        assert len(mismatch) >= 1, "Should warn about mismatched category total"
        assert "declared=999.00" in mismatch[0].message

    def test_alternative_items_in_total_warns(self) -> None:
        """Detect when declared total incorrectly includes alternative items."""
        items = [
            Item(oz="01.0010", short_text="Normal", qty=Decimal("10"),
                 unit="m2", unit_price=Decimal("10"), total_price=Decimal("100"),
                 item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="Alternative", qty=Decimal("5"),
                 unit="m2", unit_price=Decimal("20"), total_price=Decimal("100"),
                 item_type=ItemType.ALTERNATIVE),
        ]
        doc = _make_doc(items=items)
        # Set BoQ-level total to 200 (includes alternative) instead of 100 (correct)
        doc.award.boq.boq_info = BoQInfo(
            name="Test",
            totals=Totals(total=Decimal("200.00")),
        )
        results = validate_totals(doc)
        alt_warnings = [
            r for r in results if "alternative" in r.message.lower()
        ]
        assert len(alt_warnings) >= 1, (
            "Should warn when total includes alternative items"
        )

    def test_no_totals_no_warnings(self) -> None:
        """Documents without declared totals should produce no warnings."""
        doc = _make_doc()
        results = validate_totals(doc)
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════
# P0.5: X88 (Nachtrag/Claims) Exchange Phase
# ═══════════════════════════════════════════════════════════════════════


class TestX88Support:
    """X88 Nachtrag/Addendum exchange phase support."""

    def test_x88_enum_exists(self) -> None:
        assert ExchangePhase.X88.value == "X88"

    def test_d88_enum_exists(self) -> None:
        assert ExchangePhase.D88.value == "D88"

    def test_d88_normalizes_to_x88(self) -> None:
        assert ExchangePhase.D88.normalized() == ExchangePhase.X88

    def test_x88_file_extension_detected(self) -> None:
        """Parser should detect .X88 extension."""
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA88/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P1</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Nachtrag</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Zusaetzliche Erdarbeiten</ShortText>
                        <Qty>50</Qty><QU>m3</QU>
                        <UP>25.00</UP><IT>1250.00</IT>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="nachtrag.X88")
        assert doc.exchange_phase == ExchangePhase.X88

    def test_x88_phase_validation_warns_missing_cono(self) -> None:
        """X88 items should get INFO about missing change order number."""
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA88/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P1</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Nachtrag 1</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Nachtrag Position</ShortText>
                        <Qty>10</Qty><QU>m2</QU>
                        <UP>50.00</UP><IT>500.00</IT>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="nachtrag.X88")
        cono_warnings = [
            r for r in doc.validation_results
            if "CONo" in r.message or "change order" in r.message.lower()
        ]
        assert len(cono_warnings) >= 1, (
            "X88 should warn about missing change order number"
        )

    def test_x88_round_trip(self, tmp_path: Path) -> None:
        """X88 document should survive parse -> write -> parse."""
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA88/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P1</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Nachtrag</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Erdarbeiten Nachtrag</ShortText>
                        <Qty>50</Qty><QU>m3</QU>
                        <UP>25.00</UP><IT>1250.00</IT>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc1 = GAEBParser.parse_string(xml, filename="nachtrag.X88")
        out = tmp_path / "nachtrag_out.X88"
        GAEBWriter.write(doc1, out, phase=ExchangePhase.X88)
        doc2 = GAEBParser.parse_string(out.read_text(), filename="nachtrag_out.X88")
        items1 = list(doc1.award.boq.iter_items())
        items2 = list(doc2.award.boq.iter_items())
        assert len(items1) == len(items2)
        assert items1[0].oz == items2[0].oz
        assert items1[0].total_price == items2[0].total_price


# ═══════════════════════════════════════════════════════════════════════
# P1.1: GAEB Precision Limit Validation
# ═══════════════════════════════════════════════════════════════════════


class TestGAEBPrecisionLimits:
    """GAEB Fachdokumentation precision limits."""

    def test_pre_decimal_digits_normal(self) -> None:
        assert _pre_decimal_digits(Decimal("12345.67")) == 5
        assert _pre_decimal_digits(Decimal("0.99")) == 1
        assert _pre_decimal_digits(Decimal("9999999999.99")) == 10

    def test_pre_decimal_digits_zero(self) -> None:
        assert _pre_decimal_digits(Decimal("0")) == 1
        assert _pre_decimal_digits(Decimal("0.001")) == 1

    def test_pre_decimal_digits_negative(self) -> None:
        assert _pre_decimal_digits(Decimal("-123.45")) == 3

    def test_decimal_places_normal(self) -> None:
        assert _decimal_places(Decimal("1.23")) == 2
        assert _decimal_places(Decimal("1.000")) == 3
        assert _decimal_places(Decimal("100")) == 0

    def test_decimal_places_integer(self) -> None:
        assert _decimal_places(Decimal("42")) == 0

    def test_unit_price_exceeds_limit_warns(self) -> None:
        """Unit price with >10 pre-decimal digits should warn."""
        items = [
            Item(
                oz="01.0010", short_text="Overpriced",
                qty=Decimal("1"), unit="Stk",
                unit_price=Decimal("99999999999.00"),  # 11 digits
                total_price=Decimal("99999999999.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(items=items)
        results = validate_numerics(doc)
        ep_warnings = [
            r for r in results
            if "Unit price" in r.message and "pre-decimal" in r.message
        ]
        assert len(ep_warnings) >= 1

    def test_quantity_exceeds_limit_warns(self) -> None:
        """Quantity with >8 pre-decimal digits should warn."""
        items = [
            Item(
                oz="01.0010", short_text="Huge qty",
                qty=Decimal("999999999.000"),  # 9 digits
                unit="m2", unit_price=Decimal("1"),
                total_price=Decimal("999999999.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(items=items)
        results = validate_numerics(doc)
        qty_warnings = [
            r for r in results
            if "Quantity" in r.message and "pre-decimal" in r.message
        ]
        assert len(qty_warnings) >= 1

    def test_quantity_excess_decimal_warns(self) -> None:
        """Quantity with >3 decimal places should warn."""
        items = [
            Item(
                oz="01.0010", short_text="Precise qty",
                qty=Decimal("10.1234"),  # 4 decimal places
                unit="m2", unit_price=Decimal("10"),
                total_price=Decimal("101.23"),
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(items=items)
        results = validate_numerics(doc)
        dec_warnings = [r for r in results if "decimal places" in r.message]
        assert len(dec_warnings) >= 1

    def test_valid_precision_no_warnings(self) -> None:
        """Normal values within GAEB limits should not warn."""
        items = [
            Item(
                oz="01.0010", short_text="Normal",
                qty=Decimal("1170.000"), unit="m2",
                unit_price=Decimal("45.50"),
                total_price=Decimal("53235.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(items=items)
        results = validate_numerics(doc)
        precision_warnings = [
            r for r in results
            if "pre-decimal" in r.message or "decimal places" in r.message
        ]
        assert len(precision_warnings) == 0

    def test_up_components_exceed_limit_warns(self) -> None:
        """More than 6 unit price components should warn."""
        items = [
            Item(
                oz="01.0010", short_text="Many components",
                qty=Decimal("10"), unit="m2",
                unit_price=Decimal("100"), total_price=Decimal("1000"),
                item_type=ItemType.NORMAL,
                up_components=[Decimal("10")] * 7,  # 7 > max 6
            ),
        ]
        doc = _make_doc(items=items)
        results = validate_numerics(doc)
        comp_warnings = [r for r in results if "unit price components" in r.message]
        assert len(comp_warnings) >= 1


# ═══════════════════════════════════════════════════════════════════════
# P1.2: Cross-Phase Validation X86->X89 and X86->X88
# ═══════════════════════════════════════════════════════════════════════


class TestCrossPhaseX86X89:
    """X86 (contract) -> X89 (invoice) cross-phase validation."""

    def _make_contract(self) -> GAEBDocument:
        items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=Decimal("45.50"),
                 total_price=Decimal("4550.00"), item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="Beton", qty=Decimal("50"),
                 unit="m3", unit_price=Decimal("180.00"),
                 total_price=Decimal("9000.00"), item_type=ItemType.NORMAL),
        ]
        return _make_doc(phase=ExchangePhase.X86, items=items)

    def _make_invoice(
        self, unit_prices: list[Decimal] | None = None,
        extra_oz: str | None = None,
    ) -> GAEBDocument:
        up1 = unit_prices[0] if unit_prices else Decimal("45.50")
        up2 = unit_prices[1] if unit_prices and len(unit_prices) > 1 else Decimal("180.00")
        items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("95"),
                 unit="m2", unit_price=up1,
                 total_price=(Decimal("95") * up1).quantize(Decimal("0.01")),
                 item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="Beton", qty=Decimal("55"),
                 unit="m3", unit_price=up2,
                 total_price=(Decimal("55") * up2).quantize(Decimal("0.01")),
                 item_type=ItemType.NORMAL),
        ]
        if extra_oz:
            items.append(
                Item(oz=extra_oz, short_text="Invented", qty=Decimal("1"),
                     unit="Stk", unit_price=Decimal("100"),
                     total_price=Decimal("100"), item_type=ItemType.NORMAL),
            )
        return _make_doc(phase=ExchangePhase.X89, items=items)

    def test_matching_unit_prices_no_errors(self) -> None:
        contract = self._make_contract()
        invoice = self._make_invoice()
        results = CrossPhaseValidator.check(contract, invoice)
        price_errors = [r for r in results if "unit price" in r.message.lower()]
        assert len(price_errors) == 0

    def test_mismatched_unit_price_detected(self) -> None:
        contract = self._make_contract()
        invoice = self._make_invoice(unit_prices=[Decimal("50.00"), Decimal("180.00")])
        results = CrossPhaseValidator.check(contract, invoice)
        price_errors = [
            r for r in results
            if "unit price" in r.message.lower() and r.severity == ValidationSeverity.ERROR
        ]
        assert len(price_errors) >= 1, "Should detect unit price mismatch"
        assert "45.50" in price_errors[0].message or "50.00" in price_errors[0].message

    def test_invented_invoice_item_detected(self) -> None:
        contract = self._make_contract()
        invoice = self._make_invoice(extra_oz="99.0010")
        results = CrossPhaseValidator.check(contract, invoice)
        not_found = [r for r in results if "not found in contract" in r.message]
        assert len(not_found) >= 1

    def test_auto_dispatch_by_phase(self) -> None:
        """check() should auto-dispatch to contract-invoice logic."""
        contract = self._make_contract()
        invoice = self._make_invoice(unit_prices=[Decimal("999.00"), Decimal("180.00")])
        # Auto-dispatch should detect X86->X89
        results = CrossPhaseValidator.check(contract, invoice)
        assert any("unit price" in r.message.lower() for r in results)


class TestCrossPhaseX86X88:
    """X86 (contract) -> X88 (addendum) cross-phase validation."""

    def _make_contract(self) -> GAEBDocument:
        items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=Decimal("45.50"),
                 total_price=Decimal("4550.00"), item_type=ItemType.NORMAL),
        ]
        return _make_doc(phase=ExchangePhase.X86, items=items)

    def test_new_item_without_cono_warns(self) -> None:
        """New addendum items without CONo should warn."""
        contract = self._make_contract()
        addendum_items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=Decimal("45.50"),
                 total_price=Decimal("4550.00"), item_type=ItemType.NORMAL),
            Item(oz="02.0010", short_text="Nachtrag Erdarbeiten",
                 qty=Decimal("50"), unit="m3", unit_price=Decimal("30.00"),
                 total_price=Decimal("1500.00"), item_type=ItemType.NORMAL,
                 change_order_number=None),
        ]
        addendum = _make_doc(phase=ExchangePhase.X88, items=addendum_items)
        results = CrossPhaseValidator.check(contract, addendum)
        cono_warnings = [r for r in results if "change order" in r.message.lower()]
        assert len(cono_warnings) >= 1

    def test_new_item_with_cono_ok(self) -> None:
        """New addendum items WITH CONo should not warn about CONo."""
        contract = self._make_contract()
        addendum_items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=Decimal("45.50"),
                 total_price=Decimal("4550.00"), item_type=ItemType.NORMAL),
            Item(oz="02.0010", short_text="Nachtrag Erdarbeiten",
                 qty=Decimal("50"), unit="m3", unit_price=Decimal("30.00"),
                 total_price=Decimal("1500.00"), item_type=ItemType.NORMAL,
                 change_order_number="NT-001"),
        ]
        addendum = _make_doc(phase=ExchangePhase.X88, items=addendum_items)
        results = CrossPhaseValidator.check(contract, addendum)
        cono_warnings = [r for r in results if "change order" in r.message.lower()]
        assert len(cono_warnings) == 0

    def test_modified_price_without_cono_warns(self) -> None:
        """Existing item with changed price but no CONo should warn."""
        contract = self._make_contract()
        addendum_items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=Decimal("55.00"),  # changed from 45.50
                 total_price=Decimal("5500.00"), item_type=ItemType.NORMAL,
                 change_order_number=None),
        ]
        addendum = _make_doc(phase=ExchangePhase.X88, items=addendum_items)
        results = CrossPhaseValidator.check(contract, addendum)
        mod_warnings = [r for r in results if "modified" in r.message.lower()]
        assert len(mod_warnings) >= 1


# ═══════════════════════════════════════════════════════════════════════
# P1.4: Writer up_frac_dig Formatting
# ═══════════════════════════════════════════════════════════════════════


class TestWriterUpFracDig:
    """Writer should format unit prices to up_frac_dig decimal places."""

    def test_up_frac_dig_3_formats_unit_price(self, tmp_path: Path) -> None:
        """With UPFracDig=3, unit price should be written with 3 decimal places."""
        items = [
            Item(
                oz="01.0010", short_text="Precision item",
                qty=Decimal("100"), unit="m2",
                unit_price=Decimal("45.505"),
                total_price=Decimal("4550.50"),
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(items=items, up_frac_dig=3)
        out = tmp_path / "precision.X86"
        GAEBWriter.write(doc, out)
        content = out.read_text()
        assert "<UP>45.505</UP>" in content, (
            f"Expected 3-decimal UP in output, got: {content}"
        )

    def test_no_up_frac_dig_preserves_precision(self, tmp_path: Path) -> None:
        """Without UPFracDig, unit price should preserve original precision."""
        items = [
            Item(
                oz="01.0010", short_text="Normal",
                qty=Decimal("100"), unit="m2",
                unit_price=Decimal("45.50"),
                total_price=Decimal("4550.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
        doc = _make_doc(items=items, up_frac_dig=None)
        out = tmp_path / "normal.X86"
        GAEBWriter.write(doc, out)
        content = out.read_text()
        assert "<UP>45.50</UP>" in content


# ═══════════════════════════════════════════════════════════════════════
# P1.5: SQLiteCache File Permissions
# ═══════════════════════════════════════════════════════════════════════


class TestSQLiteCachePermissions:
    """SQLiteCache should create DB files with restrictive permissions."""

    def test_db_file_permissions(self, tmp_path: Path) -> None:
        from pygaeb.cache import SQLiteCache

        cache = SQLiteCache(str(tmp_path / "test_cache"))
        cache.put("test_key", "test_value")
        db_path = Path(cache._db_path)
        assert db_path.exists()
        mode = db_path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
        cache.close()

    def test_cache_dir_permissions(self, tmp_path: Path) -> None:
        from pygaeb.cache import SQLiteCache

        cache_dir = tmp_path / "restricted_cache"
        cache = SQLiteCache(str(cache_dir))
        mode = cache_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700 for directory, got {oct(mode)}"
        cache.close()


# ═══════════════════════════════════════════════════════════════════════
# Backward Compatibility: Existing Cross-Phase Still Works
# ═══════════════════════════════════════════════════════════════════════


class TestCrossPhaseBackwardCompat:
    """Ensure X83->X84 cross-phase validation still works after refactor."""

    def test_x83_x84_clean_check(self) -> None:
        """Identical structure should produce no errors."""
        items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=None, total_price=None,
                 item_type=ItemType.NORMAL),
        ]
        tender = _make_doc(phase=ExchangePhase.X83, items=items)
        bid_items = [
            Item(oz="01.0010", short_text="Mauerwerk", qty=Decimal("100"),
                 unit="m2", unit_price=Decimal("45.50"),
                 total_price=Decimal("4550.00"), item_type=ItemType.NORMAL),
        ]
        bid = _make_doc(phase=ExchangePhase.X84, items=bid_items)
        results = CrossPhaseValidator.check(tender, bid)
        errors = [r for r in results if r.severity == ValidationSeverity.ERROR]
        assert len(errors) == 0

    def test_x83_x84_missing_item_detected(self) -> None:
        """Missing item in bid should produce ERROR."""
        tender_items = [
            Item(oz="01.0010", short_text="A", qty=Decimal("10"),
                 unit="m2", item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="B", qty=Decimal("20"),
                 unit="m2", item_type=ItemType.NORMAL),
        ]
        bid_items = [
            Item(oz="01.0010", short_text="A", qty=Decimal("10"),
                 unit="m2", unit_price=Decimal("10"),
                 total_price=Decimal("100"), item_type=ItemType.NORMAL),
            # Missing 01.0020
        ]
        tender = _make_doc(phase=ExchangePhase.X83, items=tender_items)
        bid = _make_doc(phase=ExchangePhase.X84, items=bid_items)
        results = CrossPhaseValidator.check(tender, bid)
        errors = [r for r in results if r.severity == ValidationSeverity.ERROR]
        assert len(errors) >= 1
        assert "01.0020" in errors[0].message
