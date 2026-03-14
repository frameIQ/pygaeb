"""Tests for the unified domain model."""

from decimal import Decimal

from pygaeb.models.enums import (
    ExchangePhase,
    ItemType,
    ValidationSeverity,
)
from pygaeb.models.item import (
    Attachment,
    ClassificationResult,
    Item,
    QtySplit,
    RichText,
)


class TestItemType:
    def test_normal_affects_total(self):
        assert ItemType.NORMAL.affects_total is True

    def test_lump_sum_affects_total(self):
        assert ItemType.LUMP_SUM.affects_total is True

    def test_alternative_does_not_affect_total(self):
        assert ItemType.ALTERNATIVE.affects_total is False

    def test_eventual_does_not_affect_total(self):
        assert ItemType.EVENTUAL.affects_total is False

    def test_text_only_does_not_affect_total(self):
        assert ItemType.TEXT_ONLY.affects_total is False

    def test_supplement_affects_total(self):
        assert ItemType.SUPPLEMENT.affects_total is True


class TestExchangePhase:
    def test_d83_normalizes_to_x83(self):
        assert ExchangePhase.D83.normalized() == ExchangePhase.X83

    def test_x83_normalizes_to_itself(self):
        assert ExchangePhase.X83.normalized() == ExchangePhase.X83

    def test_d86_normalizes_to_x86(self):
        assert ExchangePhase.D86.normalized() == ExchangePhase.X86


class TestItem:
    def test_computed_total(self):
        item = Item(qty=Decimal("10"), unit_price=Decimal("5.50"))
        assert item.computed_total == Decimal("55.00")

    def test_computed_total_none_when_missing_qty(self):
        item = Item(unit_price=Decimal("5.50"))
        assert item.computed_total is None

    def test_computed_total_rounding(self):
        item = Item(qty=Decimal("3"), unit_price=Decimal("1.005"))
        assert item.computed_total == Decimal("3.02")

    def test_rounding_discrepancy(self):
        item = Item(
            qty=Decimal("10"),
            unit_price=Decimal("5.50"),
            total_price=Decimal("56.00"),
        )
        assert item.has_rounding_discrepancy is True

    def test_no_rounding_discrepancy(self):
        item = Item(
            qty=Decimal("10"),
            unit_price=Decimal("5.50"),
            total_price=Decimal("55.00"),
        )
        assert item.has_rounding_discrepancy is False

    def test_hierarchy_path_str(self):
        item = Item(hierarchy_path=["Rohbau", "Mauerwerk", "Innenwände"])
        assert item.hierarchy_path_str == "Rohbau > Mauerwerk > Innenwände"


class TestQtySplit:
    def test_basic_split(self):
        split = QtySplit(label="Floor 1", qty=Decimal("100"))
        assert split.label == "Floor 1"
        assert split.qty == Decimal("100")


class TestRichText:
    def test_from_plain(self):
        rt = RichText.from_plain("Simple text")
        assert rt.plain_text == "Simple text"
        assert rt.paragraphs == ["Simple text"]

    def test_from_empty(self):
        rt = RichText.from_plain("")
        assert rt.plain_text == ""
        assert rt.paragraphs == []


class TestAttachment:
    def test_auto_size(self):
        att = Attachment(filename="test.pdf", mime_type="application/pdf", data=b"hello")
        assert att.size_bytes == 5


class TestClassificationResult:
    def test_confidence_clamped(self):
        result = ClassificationResult(confidence=1.5)
        assert result.confidence == 1.0

    def test_confidence_floor(self):
        result = ClassificationResult(confidence=-0.5)
        assert result.confidence == 0.0


class TestGAEBDocument:
    def test_grand_total(self, sample_document):
        expected = Decimal("53235.00") + Decimal("57834.00") + Decimal("11250.00")
        assert sample_document.grand_total == expected

    def test_computed_grand_total(self, sample_document):
        expected = Decimal("53235.00") + Decimal("57834.00") + Decimal("11250.00")
        assert sample_document.computed_grand_total == expected

    def test_item_count(self, sample_document):
        assert sample_document.item_count == 3

    def test_add_warning(self, sample_document):
        sample_document.add_warning("test warning")
        assert len(sample_document.validation_results) == 1
        assert sample_document.validation_results[0].severity == ValidationSeverity.WARNING


class TestBoQ:
    def test_iter_items(self, sample_document):
        items = list(sample_document.award.boq.iter_items())
        assert len(items) == 3

    def test_get_item(self, sample_document):
        item = sample_document.award.boq.get_item("01.01.0010")
        assert item is not None
        assert item.short_text == "Mauerwerk Innenwand"

    def test_get_item_not_found(self, sample_document):
        item = sample_document.award.boq.get_item("99.99.9999")
        assert item is None

    def test_is_not_multi_lot(self, sample_document):
        assert sample_document.award.boq.is_multi_lot is False

    def test_lot_subtotal(self, sample_document):
        lot = sample_document.award.boq.lots[0]
        expected = Decimal("53235.00") + Decimal("57834.00") + Decimal("11250.00")
        assert lot.subtotal == expected
