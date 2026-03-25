"""Tests for the BoQ Builder API."""

from __future__ import annotations  # noqa: I001

from decimal import Decimal

import pytest

from pygaeb.builder import BoQBuilder, CategoryBuilder, ItemHandle, LotBuilder
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, ItemType, SourceVersion


# ── Basic Construction ──────────────────────────────────────────────────

class TestBasicConstruction:
    def test_minimal_build(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "Section A")
        cat.add_item("01.0010", "Test item", qty=10, unit="m2", unit_price=50)
        doc = builder.build()
        assert isinstance(doc, GAEBDocument)
        assert doc.item_count == 1

    def test_single_lot_explicit(self):
        builder = BoQBuilder(phase="X83", version="3.3")
        lot = builder.add_lot("1", "Lot 1")
        cat = lot.add_category("01", "Concrete")
        cat.add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)
        doc = builder.build()
        assert len(doc.award.boq.lots) == 1
        assert doc.award.boq.lots[0].rno == "1"
        assert doc.item_count == 1

    def test_multi_lot(self):
        builder = BoQBuilder()
        lot1 = builder.add_lot("1", "Structural")
        lot1.add_category("01", "Concrete").add_item(
            "01.0010", "Foundation", qty=10, unit="m3", unit_price=85
        )
        lot2 = builder.add_lot("2", "MEP")
        lot2.add_category("01", "Electrical").add_item(
            "01.0010", "Cable tray", qty=200, unit="m", unit_price=15
        )
        doc = builder.build()
        assert len(doc.award.boq.lots) == 2
        assert doc.item_count == 2

    def test_nested_subcategories(self):
        builder = BoQBuilder()
        lot = builder.add_lot("1", "Default")
        rohbau = lot.add_category("01", "Rohbau")
        mauer = rohbau.add_subcategory("01.01", "Mauerwerk")
        mauer.add_item("01.01.0010", "Innenwand", qty=100, unit="m2", unit_price=45)
        mauer.add_item("01.01.0020", "Aussenwand", qty=80, unit="m2", unit_price=68)
        doc = builder.build()
        assert doc.item_count == 2
        ctgy = doc.award.boq.lots[0].body.categories[0]
        assert len(ctgy.subcategories) == 1
        assert ctgy.subcategories[0].rno == "01.01"

    def test_project_metadata(self):
        builder = BoQBuilder()
        builder.project(no="PRJ-001", name="School Renovation", currency="EUR", client="City")
        builder.add_category("01", "A").add_item("01.0010", "Item")
        doc = builder.build()
        assert doc.award.project_no == "PRJ-001"
        assert doc.award.project_name == "School Renovation"
        assert doc.award.currency == "EUR"
        assert doc.award.client == "City"

    def test_exchange_phase_and_version(self):
        builder = BoQBuilder(phase="X84", version="3.2")
        builder.add_category("01", "A").add_item("01.0010", "Item", unit_price=10)
        doc = builder.build()
        assert doc.exchange_phase == ExchangePhase.X84
        assert doc.source_version == SourceVersion.DA_XML_32

    def test_returns_builder_handles(self):
        builder = BoQBuilder()
        lot = builder.add_lot("1", "L")
        assert isinstance(lot, LotBuilder)
        cat = lot.add_category("01", "C")
        assert isinstance(cat, CategoryBuilder)
        handle = cat.add_item("01.0010", "Item")
        assert isinstance(handle, ItemHandle)


# ── Implicit Lot ────────────────────────────────────────────────────────

class TestImplicitLot:
    def test_implicit_lot_created(self):
        builder = BoQBuilder()
        builder.add_category("01", "Section")
        doc = builder.build()
        assert len(doc.award.boq.lots) == 1
        assert doc.award.boq.lots[0].rno == "1"

    def test_cannot_mix_implicit_and_explicit(self):
        builder = BoQBuilder()
        builder.add_lot("1", "Lot 1")
        with pytest.raises(ValueError, match="Cannot use add_category"):
            builder.add_category("01", "Section")


# ── Auto OZ Generation ─────────────────────────────────────────────────

class TestAutoOZ:
    def test_auto_oz_from_category_rno(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "Section")
        cat.add_item(short_text="First")
        cat.add_item(short_text="Second")
        cat.add_item(short_text="Third")
        doc = builder.build()
        items = list(doc.award.boq.iter_items())
        assert items[0].oz == "01.0010"
        assert items[1].oz == "01.0020"
        assert items[2].oz == "01.0030"

    def test_explicit_oz_overrides(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "Section")
        cat.add_item("99.9999", "Custom OZ")
        doc = builder.build()
        items = list(doc.award.boq.iter_items())
        assert items[0].oz == "99.9999"

    def test_mixed_auto_and_explicit(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "Section")
        cat.add_item(short_text="Auto 1")
        cat.add_item("01.CUSTOM", "Explicit")
        cat.add_item(short_text="Auto 2")
        doc = builder.build()
        items = list(doc.award.boq.iter_items())
        assert items[0].oz == "01.0010"
        assert items[1].oz == "01.CUSTOM"
        assert items[2].oz == "01.0030"


# ── Decimal Convenience ────────────────────────────────────────────────

class TestDecimalConvenience:
    def test_int_to_decimal(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=100, unit="m2", unit_price=50)
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert isinstance(item.qty, Decimal)
        assert item.qty == Decimal("100")
        assert isinstance(item.unit_price, Decimal)
        assert item.unit_price == Decimal("50")

    def test_float_to_decimal(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10.5, unit="m2", unit_price=45.99)
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert item.qty == Decimal("10.5")
        assert item.unit_price == Decimal("45.99")

    def test_auto_total_price(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50)
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert item.total_price == Decimal("500.00")

    def test_explicit_total_price_overrides(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50, total_price=499)
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert item.total_price == Decimal("499")

    def test_none_values(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item")
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert item.qty is None
        assert item.unit_price is None
        assert item.total_price is None

    def test_invalid_decimal_raises(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        with pytest.raises(ValueError, match="Cannot convert"):
            cat.add_item("01.0010", "Item", qty="not-a-number")


# ── Field Name Validation ──────────────────────────────────────────────

class TestFieldValidation:
    def test_typo_in_item_field(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        with pytest.raises(ValueError, match="Unknown Item field 'unit_prce'"):
            cat.add_item("01.0010", "Item", unit_prce=50)

    def test_typo_suggestion(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        with pytest.raises(ValueError, match="Did you mean"):
            cat.add_item("01.0010", "Item", short_tex="test")

    def test_typo_in_project(self):
        builder = BoQBuilder()
        with pytest.raises(ValueError, match="Unknown AwardInfo field"):
            builder.project(curreny="EUR")

    def test_typo_in_category(self):
        builder = BoQBuilder()
        with pytest.raises(ValueError, match="Unknown BoQCtgy field"):
            builder.add_category("01", "A", labl="test")

    def test_typo_in_lot(self):
        builder = BoQBuilder()
        with pytest.raises(ValueError, match="Unknown Lot field"):
            builder.add_lot("1", "L", labl="test")

    def test_valid_kwargs_accepted(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item(
            "01.0010", "Item",
            qty=10, unit="m2", unit_price=50,
            item_type=ItemType.ALTERNATIVE,
            bim_guid="abc-123",
        )
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert item.item_type == ItemType.ALTERNATIVE
        assert item.bim_guid == "abc-123"


# ── ItemHandle (Long Text / Attachments) ───────────────────────────────

class TestItemHandle:
    def test_set_long_text(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        handle = cat.add_item("01.0010", "Item")
        handle.set_long_text("Detailed specification text.")
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert item.long_text is not None
        assert item.long_text.plain_text == "Detailed specification text."

    def test_add_attachment(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        handle = cat.add_item("01.0010", "Item")
        handle.add_attachment("plan.pdf", b"PDF_CONTENT", mime_type="application/pdf")
        doc = builder.build()
        item = next(doc.award.boq.iter_items())
        assert len(item.attachments) == 1
        assert item.attachments[0].filename == "plan.pdf"

    def test_fluent_chaining(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        handle = (
            cat.add_item("01.0010", "Item")
            .set_long_text("Details")
            .add_attachment("a.pdf", b"data")
        )
        assert isinstance(handle, ItemHandle)


# ── Phase-Aware Rules ──────────────────────────────────────────────────

class TestPhaseRules:
    def test_x80_warns_on_prices(self):
        builder = BoQBuilder(phase="X80")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50)
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert any("X80" in w for w in warnings)

    def test_x83_warns_on_missing_price(self):
        builder = BoQBuilder(phase="X83")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10, unit="m2")
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert any("unit_price" in w and "missing" in w for w in warnings)

    def test_x83_no_warning_when_price_present(self):
        builder = BoQBuilder(phase="X83")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50)
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert not any("unit_price" in w for w in warnings)

    def test_strict_mode_raises_on_phase_violation(self):
        builder = BoQBuilder(phase="X80")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", unit_price=50)
        with pytest.raises(ValueError, match=r"unit_price.*X80"):
            builder.build(strict=True)


# ── Version Compatibility ──────────────────────────────────────────────

class TestVersionCompat:
    def test_bim_guid_warns_for_old_version(self):
        builder = BoQBuilder(version="3.2")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", bim_guid="abc-123")
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert any("bim_guid" in w and "3.3" in w for w in warnings)

    def test_bim_guid_ok_for_33(self):
        builder = BoQBuilder(version="3.3")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", bim_guid="abc-123")
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert not any("bim_guid" in w for w in warnings)

    def test_strict_mode_raises_on_version_violation(self):
        builder = BoQBuilder(version="3.0")
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", unit_price=10, bim_guid="abc-123")
        with pytest.raises(ValueError, match=r"bim_guid.*3\.3"):
            builder.build(strict=True)


# ── Duplicate OZ Detection ─────────────────────────────────────────────

class TestDuplicateOZ:
    def test_duplicate_oz_warning(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "First")
        cat.add_item("01.0010", "Duplicate")
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert any("duplicate" in w.lower() for w in warnings)

    def test_duplicate_oz_strict_raises(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "First")
        cat.add_item("01.0010", "Duplicate")
        with pytest.raises(ValueError, match="duplicate"):
            builder.build(strict=True)

    def test_same_oz_different_lots_ok(self):
        builder = BoQBuilder()
        lot1 = builder.add_lot("1", "L1")
        lot1.add_category("01", "A").add_item("01.0010", "Item in lot 1")
        lot2 = builder.add_lot("2", "L2")
        lot2.add_category("01", "A").add_item("01.0010", "Item in lot 2")
        doc = builder.build()
        warnings = [r.message for r in doc.validation_results]
        assert not any("duplicate" in w.lower() for w in warnings)


# ── Auto Totals & BoQBkdn ─────────────────────────────────────────────

class TestAutoTotals:
    def test_lot_totals_computed(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item A", qty=10, unit="m2", unit_price=50)
        cat.add_item("01.0020", "Item B", qty=5, unit="m2", unit_price=100)
        doc = builder.build()
        lot = doc.award.boq.lots[0]
        assert lot.totals is not None
        assert lot.totals.total == Decimal("1000.00")

    def test_boq_bkdn_inferred(self):
        builder = BoQBuilder()
        lot = builder.add_lot("1", "L")
        lot.add_category("01", "A").add_item("01.0010", "Item")
        doc = builder.build()
        bkdn = doc.award.boq.boq_info.bkdn
        assert len(bkdn) >= 1


# ── Lazy Import ────────────────────────────────────────────────────────

class TestLazyImport:
    def test_import_from_pygaeb(self):
        from pygaeb import BoQBuilder as BB
        assert BB is BoQBuilder


# ── Edge Cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_document(self):
        builder = BoQBuilder()
        builder.add_category("01", "Empty")
        doc = builder.build()
        assert doc.item_count == 0

    def test_many_items(self):
        builder = BoQBuilder()
        cat = builder.add_category("01", "Bulk")
        for i in range(200):
            cat.add_item(f"01.{i:04d}", f"Item {i}", qty=1, unit="Stk", unit_price=10)
        doc = builder.build()
        assert doc.item_count == 200

    def test_round_trip_with_writer(self):
        """Built document should serialize to bytes without error."""
        from pygaeb.writer.gaeb_writer import GAEBWriter

        builder = BoQBuilder(phase="X83", version="3.3")
        builder.project(no="PRJ-001", name="Test", currency="EUR")
        cat = builder.add_category("01", "Section")
        cat.add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)
        cat.add_item("01.0020", "Columns", qty=40, unit="m3", unit_price=95)
        doc = builder.build()

        xml_bytes, _warnings = GAEBWriter.to_bytes(doc)
        assert b"<GAEB" in xml_bytes
        assert b"Foundation" in xml_bytes
        assert b"01.0010" in xml_bytes

    def test_serialization_round_trip(self):
        """Built document should serialize to JSON and back."""
        builder = BoQBuilder()
        cat = builder.add_category("01", "A")
        cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50)
        doc = builder.build()
        json_str = doc.model_dump_json()
        restored = GAEBDocument.model_validate_json(json_str)
        assert restored.item_count == 1

    def test_string_phase_and_version(self):
        builder = BoQBuilder(phase="X84", version="3.1")
        assert builder._phase == ExchangePhase.X84
        assert builder._version == SourceVersion.DA_XML_31

    def test_enum_phase_and_version(self):
        builder = BoQBuilder(
            phase=ExchangePhase.X83,
            version=SourceVersion.DA_XML_33,
        )
        assert builder._phase == ExchangePhase.X83
