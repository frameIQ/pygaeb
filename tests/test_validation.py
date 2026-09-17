"""Tests for the validation layer."""

from decimal import Decimal

from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument
from pygaeb.models.enums import (
    ItemType,
    ValidationSeverity,
)
from pygaeb.models.item import Item, QtySplit
from pygaeb.validation.cross_phase_validator import CrossPhaseValidator
from pygaeb.validation.item_validator import validate_items
from pygaeb.validation.numeric_validator import validate_numerics
from pygaeb.validation.structural_validator import validate_structure


class TestNumericValidator:
    def test_detects_rounding_mismatch(self):
        item = Item(
            oz="01.01.0010",
            qty=Decimal("10"),
            unit_price=Decimal("5.50"),
            total_price=Decimal("60.00"),
        )
        ctgy = BoQCtgy(items=[item])
        body = BoQBody(categories=[ctgy])
        lot = Lot(body=body)
        doc = GAEBDocument(
            award=AwardInfo(boq=BoQ(lots=[lot])),
        )
        results = validate_numerics(doc)
        assert len(results) == 1
        assert results[0].severity == ValidationSeverity.WARNING
        assert "mismatch" in results[0].message.lower()

    def test_no_mismatch_when_correct(self):
        item = Item(
            oz="01.01.0010",
            qty=Decimal("10"),
            unit_price=Decimal("5.50"),
            total_price=Decimal("55.00"),
        )
        ctgy = BoQCtgy(items=[item])
        body = BoQBody(categories=[ctgy])
        lot = Lot(body=body)
        doc = GAEBDocument(
            award=AwardInfo(boq=BoQ(lots=[lot])),
        )
        results = validate_numerics(doc)
        assert len(results) == 0


class TestItemValidator:
    def test_detects_supplement_without_cono(self):
        item = Item(
            oz="01.01.0010",
            item_type=ItemType.SUPPLEMENT,
        )
        ctgy = BoQCtgy(items=[item])
        body = BoQBody(categories=[ctgy])
        lot = Lot(body=body)
        doc = GAEBDocument(
            award=AwardInfo(boq=BoQ(lots=[lot])),
        )
        results = validate_items(doc)
        warnings = [r for r in results if "change order" in r.message.lower()]
        assert len(warnings) == 1

    def test_detects_qty_split_mismatch(self):
        item = Item(
            oz="01.01.0010",
            qty=Decimal("100"),
            qty_splits=[
                QtySplit(label="A", qty=Decimal("40")),
                QtySplit(label="B", qty=Decimal("50")),
            ],
        )
        ctgy = BoQCtgy(items=[item])
        body = BoQBody(categories=[ctgy])
        lot = Lot(body=body)
        doc = GAEBDocument(
            award=AwardInfo(boq=BoQ(lots=[lot])),
        )
        results = validate_items(doc)
        warnings = [r for r in results if "qtysplit" in r.message.lower()]
        assert len(warnings) == 1


class TestCrossPhaseValidator:
    def _make_doc(self, items):
        ctgy = BoQCtgy(items=items)
        body = BoQBody(categories=[ctgy])
        lot = Lot(body=body)
        return GAEBDocument(award=AwardInfo(boq=BoQ(lots=[lot])))

    def test_detects_missing_items(self):
        source = self._make_doc([
            Item(oz="0010", short_text="A", item_type=ItemType.NORMAL),
            Item(oz="0020", short_text="B", item_type=ItemType.NORMAL),
        ])
        response = self._make_doc([
            Item(oz="0010", short_text="A", item_type=ItemType.NORMAL),
        ])
        results = CrossPhaseValidator.check(source, response)
        errors = [r for r in results if r.severity == ValidationSeverity.ERROR]
        assert len(errors) == 1
        assert "0020" in errors[0].message

    def test_detects_modified_quantity(self):
        source = self._make_doc([
            Item(oz="0010", qty=Decimal("100"), item_type=ItemType.NORMAL),
        ])
        response = self._make_doc([
            Item(oz="0010", qty=Decimal("200"), item_type=ItemType.NORMAL),
        ])
        results = CrossPhaseValidator.check(source, response)
        warnings = [r for r in results if "quantity" in r.message.lower()]
        assert len(warnings) == 1

    def test_clean_comparison(self):
        items = [
            Item(oz="0010", qty=Decimal("100"), unit_price=Decimal("50"),
                 item_type=ItemType.NORMAL),
        ]
        source = self._make_doc(items)
        response = self._make_doc(items)
        results = CrossPhaseValidator.check(source, response)
        errors = [r for r in results if r.severity == ValidationSeverity.ERROR]
        assert len(errors) == 0


class TestFullOzMessages:
    def _doc(self, categories):
        return GAEBDocument(award=AwardInfo(boq=BoQ(lots=[
            Lot(rno="1", body=BoQBody(categories=categories)),
        ])))

    def test_messages_name_the_full_oz_and_the_node_kind(self):
        doc = self._doc([
            BoQCtgy(rno="02", items=[
                Item(oz="0030", oz_path=["02"], item_type=ItemType.MARKUP),
                Item(oz="0010", oz_path=["02"], short_text="Fenster", item_type=ItemType.NORMAL),
            ]),
        ])
        messages = [r.message for r in validate_items(doc)]
        assert "Item 02.0010: Normal item has no quantity" in messages
        assert not any(m.startswith("Item 0010") for m in messages)
        # A markup item never carries a ShortText in 3.x files, so no note for it.
        assert not any("02.0030" in m for m in messages)

    def test_markup_ref_names_the_kind(self):
        from pygaeb.validation._common import item_ref

        markup = Item(oz="0030", oz_path=["02"], item_type=ItemType.MARKUP)
        assert item_ref(markup) == "MarkupItem 02.0030"

    def test_duplicate_oz_within_a_lot_is_an_error(self):
        doc = self._doc([
            BoQCtgy(rno="001", items=[
                Item(oz="0010", oz_path=["001"], short_text="Baustelle", item_type=ItemType.NORMAL),
                Item(oz="0010", oz_path=["001"], short_text="Wasserhaltung"),
                Item(oz="0010", oz_path=["001"], short_text="Überwachung"),
            ]),
        ])
        results = validate_structure(doc)
        errors = [r for r in results if r.severity == ValidationSeverity.ERROR]
        assert [e.message for e in errors] == ["Duplicate OZ 001.0010 (3x) in lot '1'"]

    def test_same_leaf_in_different_categories_is_not_a_duplicate(self):
        doc = self._doc([
            BoQCtgy(rno="01", items=[Item(oz="0010", oz_path=["01"], short_text="A")]),
            BoQCtgy(rno="02", items=[Item(oz="0010", oz_path=["02"], short_text="B")]),
        ])
        assert not [r for r in validate_structure(doc) if "Duplicate" in r.message]

    def test_index_positions_share_a_leaf_legitimately(self):
        doc = self._doc([
            BoQCtgy(rno="01", items=[
                Item(oz="0010", oz_path=["01"], rno_index="1", short_text="Variante 1"),
                Item(oz="0010", oz_path=["01"], rno_index="A", short_text="Variante A"),
            ]),
        ])
        assert not [r for r in validate_structure(doc) if "Duplicate" in r.message]

    def test_cross_phase_compares_by_full_oz(self):
        def item(ctgy: str, price: str | None) -> Item:
            return Item(oz="0010", oz_path=[ctgy], qty=Decimal("1"),
                        unit_price=Decimal(price) if price else None, item_type=ItemType.NORMAL)

        def make(price_for_03: str | None):
            return self._doc([
                BoQCtgy(rno="02", items=[item("02", "5")]),
                BoQCtgy(rno="03", items=[item("03", price_for_03)]),
            ])
        results = CrossPhaseValidator.check(make("5"), make(None))
        assert [r.message for r in results] == [
            "Item 03.0010: Priced item missing unit price in response"
        ]
