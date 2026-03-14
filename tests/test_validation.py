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
