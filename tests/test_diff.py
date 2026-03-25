"""Tests for the BoQ document diff engine."""

from __future__ import annotations  # noqa: I001

from decimal import Decimal

import pytest

from pygaeb.diff.boq_diff import BoQDiff
from pygaeb.diff.field_comparator import compare_items
from pygaeb.diff.item_matcher import match_items
from pygaeb.diff.models import (
    DiffMode,
    DiffResult,
    FieldChange,
    ItemModified,
    Significance,
)
from pygaeb.diff.structure_diff import compare_structure, detect_moved_items
from pygaeb.api.boq_tree import BoQTree
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument
from pygaeb.models.enums import ExchangePhase, ItemType, SourceVersion
from pygaeb.models.item import Item


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_item(
    oz: str = "01.0010",
    short_text: str = "Test item",
    qty: Decimal | None = Decimal("10"),
    unit: str = "m2",
    unit_price: Decimal | None = Decimal("100"),
    total_price: Decimal | None = Decimal("1000"),
    item_type: ItemType = ItemType.NORMAL,
    **kwargs: object,
) -> Item:
    return Item(
        oz=oz, short_text=short_text, qty=qty, unit=unit,
        unit_price=unit_price, total_price=total_price,
        item_type=item_type, **kwargs,
    )


def _make_boq(
    items: list[Item] | None = None,
    lot_rno: str = "1",
    lot_label: str = "Default",
    ctgy_rno: str = "01",
    ctgy_label: str = "Section A",
) -> BoQ:
    items = items or [_make_item()]
    ctgy = BoQCtgy(rno=ctgy_rno, label=ctgy_label, items=items)
    lot = Lot(rno=lot_rno, label=lot_label, body=BoQBody(categories=[ctgy]))
    return BoQ(lots=[lot])


def _make_doc(
    boq: BoQ | None = None,
    project_no: str | None = "PRJ-001",
    project_name: str | None = "Test Project",
    currency: str = "EUR",
    exchange_phase: ExchangePhase = ExchangePhase.X83,
    source_version: SourceVersion = SourceVersion.DA_XML_33,
) -> GAEBDocument:
    boq = boq or _make_boq()
    return GAEBDocument(
        source_version=source_version,
        exchange_phase=exchange_phase,
        award=AwardInfo(
            project_no=project_no,
            project_name=project_name,
            currency=currency,
            boq=boq,
        ),
    )


# ── Item Matcher Tests ─────────────────────────────────────────────────

class TestItemMatcher:
    def test_identical_documents_all_matched(self):
        boq = _make_boq(items=[_make_item(oz="01.0010"), _make_item(oz="01.0020")])
        tree_a = BoQTree(boq)
        tree_b = BoQTree(boq)
        result = match_items(tree_a, tree_b)
        assert len(result.matched) == 2
        assert len(result.unmatched_a) == 0
        assert len(result.unmatched_b) == 0
        assert result.match_ratio == 1.0

    def test_item_added(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010")])
        boq_b = _make_boq(items=[_make_item(oz="01.0010"), _make_item(oz="01.0020")])
        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 1
        assert len(result.unmatched_a) == 0
        assert len(result.unmatched_b) == 1
        assert result.unmatched_b[0].rno == "01.0020"

    def test_item_removed(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010"), _make_item(oz="01.0020")])
        boq_b = _make_boq(items=[_make_item(oz="01.0010")])
        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 1
        assert len(result.unmatched_a) == 1
        assert len(result.unmatched_b) == 0
        assert result.unmatched_a[0].rno == "01.0020"

    def test_completely_different_documents(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010")])
        boq_b = _make_boq(items=[_make_item(oz="99.0010")])
        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 0
        assert len(result.unmatched_a) == 1
        assert len(result.unmatched_b) == 1
        assert result.match_ratio == 0.0

    def test_match_ratio_partial(self):
        boq_a = _make_boq(items=[
            _make_item(oz="01.0010"),
            _make_item(oz="01.0020"),
        ])
        boq_b = _make_boq(items=[
            _make_item(oz="01.0010"),
            _make_item(oz="01.0030"),
        ])
        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 1
        assert result.match_ratio == 0.5

    def test_multi_lot_same_oz(self):
        """Items in different lots with the same OZ are matched within their lot."""
        lot1_a = Lot(rno="1", label="Lot 1", body=BoQBody(categories=[
            BoQCtgy(rno="01", label="A", items=[_make_item(oz="01.0010", short_text="Lot1 A")]),
        ]))
        lot2_a = Lot(rno="2", label="Lot 2", body=BoQBody(categories=[
            BoQCtgy(rno="01", label="B", items=[_make_item(oz="01.0010", short_text="Lot2 A")]),
        ]))
        boq_a = BoQ(lots=[lot1_a, lot2_a])

        lot1_b = Lot(rno="1", label="Lot 1", body=BoQBody(categories=[
            BoQCtgy(rno="01", label="A", items=[_make_item(oz="01.0010", short_text="Lot1 B")]),
        ]))
        lot2_b = Lot(rno="2", label="Lot 2", body=BoQBody(categories=[
            BoQCtgy(rno="01", label="B", items=[_make_item(oz="01.0010", short_text="Lot2 B")]),
        ]))
        boq_b = BoQ(lots=[lot1_b, lot2_b])

        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 2
        assert result.match_ratio == 1.0

    def test_global_oz_fallback_when_lot_changes(self):
        """An item moved between lots should still be matched by global OZ fallback."""
        boq_a = BoQ(lots=[
            Lot(rno="1", label="Lot 1", body=BoQBody(categories=[
                BoQCtgy(rno="01", label="A", items=[_make_item(oz="01.0010")]),
            ])),
        ])
        boq_b = BoQ(lots=[
            Lot(rno="2", label="Lot 2", body=BoQBody(categories=[
                BoQCtgy(rno="01", label="A", items=[_make_item(oz="01.0010")]),
            ])),
        ])
        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 1
        assert len(result.unmatched_a) == 0

    def test_empty_boq(self):
        boq_a = BoQ(lots=[Lot(rno="1", label="Empty")])
        boq_b = BoQ(lots=[Lot(rno="1", label="Empty")])
        result = match_items(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.matched) == 0
        assert result.match_ratio == 0.0


# ── Field Comparator Tests ─────────────────────────────────────────────

class TestFieldComparator:
    def test_identical_items_no_changes(self):
        item = _make_item()
        changes = compare_items(item, item)
        assert changes == []

    def test_price_change_is_critical(self):
        item_a = _make_item(unit_price=Decimal("100"))
        item_b = _make_item(unit_price=Decimal("120"))
        changes = compare_items(item_a, item_b)
        price_changes = [c for c in changes if c.field == "unit_price"]
        assert len(price_changes) == 1
        assert price_changes[0].significance == Significance.CRITICAL

    def test_qty_change_has_delta(self):
        item_a = _make_item(qty=Decimal("100"))
        item_b = _make_item(qty=Decimal("150"))
        changes = compare_items(item_a, item_b)
        qty_changes = [c for c in changes if c.field == "qty"]
        assert len(qty_changes) == 1
        assert qty_changes[0].absolute_delta == Decimal("50")
        assert qty_changes[0].percent_delta == pytest.approx(50.0)

    def test_unit_change_is_high(self):
        item_a = _make_item(unit="m2")
        item_b = _make_item(unit="m3")
        changes = compare_items(item_a, item_b)
        unit_changes = [c for c in changes if c.field == "unit"]
        assert len(unit_changes) == 1
        assert unit_changes[0].significance == Significance.HIGH

    def test_text_change_is_medium(self):
        item_a = _make_item(short_text="Old text")
        item_b = _make_item(short_text="New text")
        changes = compare_items(item_a, item_b)
        text_changes = [c for c in changes if c.field == "short_text"]
        assert len(text_changes) == 1
        assert text_changes[0].significance == Significance.MEDIUM

    def test_item_type_change_is_high(self):
        item_a = _make_item(item_type=ItemType.NORMAL)
        item_b = _make_item(item_type=ItemType.ALTERNATIVE)
        changes = compare_items(item_a, item_b)
        type_changes = [c for c in changes if c.field == "item_type"]
        assert len(type_changes) == 1
        assert type_changes[0].significance == Significance.HIGH

    def test_multiple_changes_detected(self):
        item_a = _make_item(
            qty=Decimal("10"), unit_price=Decimal("100"),
            total_price=Decimal("1000"), short_text="Old",
        )
        item_b = _make_item(
            qty=Decimal("20"), unit_price=Decimal("200"),
            total_price=Decimal("4000"), short_text="New",
        )
        changes = compare_items(item_a, item_b)
        changed_fields = {c.field for c in changes}
        assert "qty" in changed_fields
        assert "unit_price" in changed_fields
        assert "short_text" in changed_fields
        assert "total_price" in changed_fields

    def test_none_to_value_is_change(self):
        item_a = _make_item(unit_price=None, total_price=None)
        item_b = _make_item(unit_price=Decimal("50"), total_price=Decimal("500"))
        changes = compare_items(item_a, item_b)
        assert len(changes) >= 1

    def test_none_and_empty_string_are_equal(self):
        item_a = _make_item(bim_guid=None)
        item_b = _make_item(bim_guid="")
        changes = compare_items(item_a, item_b)
        guid_changes = [c for c in changes if c.field == "bim_guid"]
        assert len(guid_changes) == 0

    def test_percent_delta_from_zero(self):
        item_a = _make_item(qty=Decimal("0"))
        item_b = _make_item(qty=Decimal("10"))
        changes = compare_items(item_a, item_b)
        qty_changes = [c for c in changes if c.field == "qty"]
        assert len(qty_changes) == 1
        assert qty_changes[0].absolute_delta == Decimal("10")
        assert qty_changes[0].percent_delta is None


# ── Structure Diff Tests ───────────────────────────────────────────────

class TestStructureDiff:
    def test_identical_structure_no_changes(self):
        boq = _make_boq()
        result = compare_structure(BoQTree(boq), BoQTree(boq))
        assert not result.has_changes

    def test_section_added(self):
        boq_a = _make_boq(ctgy_rno="01", ctgy_label="Section A")
        ctgy_a = BoQCtgy(rno="01", label="Section A", items=[_make_item(oz="01.0010")])
        ctgy_b = BoQCtgy(rno="02", label="Section B", items=[_make_item(oz="02.0010")])
        lot = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy_a, ctgy_b]))
        boq_b = BoQ(lots=[lot])

        result = compare_structure(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.sections_added) == 1
        assert result.sections_added[0].rno == "02"
        assert result.sections_added[0].label == "Section B"

    def test_section_removed(self):
        ctgy_a = BoQCtgy(rno="01", label="Section A", items=[_make_item(oz="01.0010")])
        ctgy_b = BoQCtgy(rno="02", label="Section B", items=[_make_item(oz="02.0010")])
        lot_a = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy_a, ctgy_b]))
        boq_a = BoQ(lots=[lot_a])

        boq_b = _make_boq(ctgy_rno="01", ctgy_label="Section A")

        result = compare_structure(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.sections_removed) == 1
        assert result.sections_removed[0].rno == "02"

    def test_section_renamed(self):
        boq_a = _make_boq(ctgy_rno="01", ctgy_label="Old Name")
        boq_b = _make_boq(ctgy_rno="01", ctgy_label="New Name")

        result = compare_structure(BoQTree(boq_a), BoQTree(boq_b))
        assert len(result.sections_renamed) == 1
        assert result.sections_renamed[0].old_label == "Old Name"
        assert result.sections_renamed[0].new_label == "New Name"

    def test_detect_moved_items(self):
        item = _make_item(oz="01.0010")

        ctgy_a = BoQCtgy(rno="01", label="Section A", items=[item])
        lot_a = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy_a]))
        boq_a = BoQ(lots=[lot_a])

        ctgy_b = BoQCtgy(rno="02", label="Section B", items=[item])
        lot_b = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy_b]))
        boq_b = BoQ(lots=[lot_b])

        tree_a = BoQTree(boq_a)
        tree_b = BoQTree(boq_b)

        match_result = match_items(tree_a, tree_b)
        moved = detect_moved_items(match_result.matched)
        assert len(moved) == 1
        assert moved[0].old_category_rno == "01"
        assert moved[0].new_category_rno == "02"


# ── BoQDiff Integration Tests ─────────────────────────────────────────

class TestBoQDiff:
    def test_identical_documents(self):
        doc = _make_doc()
        result = BoQDiff.compare(doc, doc)
        assert isinstance(result, DiffResult)
        assert result.summary.has_changes is False
        assert result.summary.items_unchanged == 1
        assert result.summary.match_ratio == 1.0

    def test_item_added(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010")])
        boq_b = _make_boq(items=[
            _make_item(oz="01.0010"),
            _make_item(oz="01.0020", short_text="New item"),
        ])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.items_added == 1
        assert result.items.added[0].oz == "01.0020"

    def test_item_removed(self):
        boq_a = _make_boq(items=[
            _make_item(oz="01.0010"),
            _make_item(oz="01.0020", short_text="To remove"),
        ])
        boq_b = _make_boq(items=[_make_item(oz="01.0010")])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.items_removed == 1
        assert result.items.removed[0].oz == "01.0020"

    def test_item_modified_price(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010", unit_price=Decimal("100"))])
        boq_b = _make_boq(items=[_make_item(oz="01.0010", unit_price=Decimal("120"))])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.items_modified == 1
        modified = result.items.modified[0]
        assert any(c.field == "unit_price" for c in modified.changes)

    def test_financial_impact(self):
        boq_a = _make_boq(items=[
            _make_item(oz="01.0010", total_price=Decimal("1000")),
        ])
        boq_b = _make_boq(items=[
            _make_item(oz="01.0010", total_price=Decimal("1500")),
        ])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.financial_impact == Decimal("500")

    def test_metadata_change_detected(self):
        doc_a = _make_doc(currency="EUR")
        doc_b = _make_doc(currency="USD")
        result = BoQDiff.compare(doc_a, doc_b)
        currency_changes = [m for m in result.metadata if m.field == "currency"]
        assert len(currency_changes) == 1
        assert currency_changes[0].old_value == "EUR"
        assert currency_changes[0].new_value == "USD"

    def test_doc_info_captured(self):
        doc_a = _make_doc(project_no="PRJ-001")
        doc_b = _make_doc(project_no="PRJ-001")
        result = BoQDiff.compare(doc_a, doc_b)
        assert result.doc_a.project_no == "PRJ-001"
        assert result.doc_b.project_no == "PRJ-001"
        assert result.summary.is_likely_same_project is True

    def test_different_project_warning(self):
        doc_a = _make_doc(project_no="PRJ-001")
        doc_b = _make_doc(project_no="PRJ-002")
        result = BoQDiff.compare(doc_a, doc_b)
        assert result.summary.is_likely_same_project is False
        assert any("different projects" in w for w in result.warnings)

    def test_strict_mode_raises_for_different_projects(self):
        doc_a = _make_doc(project_no="PRJ-001")
        doc_b = _make_doc(project_no="PRJ-002")
        with pytest.raises(ValueError, match="different projects"):
            BoQDiff.compare(doc_a, doc_b, mode=DiffMode.STRICT)

    def test_force_mode_suppresses_warnings(self):
        doc_a = _make_doc(project_no="PRJ-001", currency="EUR")
        doc_b = _make_doc(project_no="PRJ-002", currency="USD")
        result = BoQDiff.compare(doc_a, doc_b, mode=DiffMode.FORCE)
        assert result.warnings == []

    def test_low_match_ratio_warning(self):
        boq_a = _make_boq(items=[_make_item(oz=f"01.{i:04d}") for i in range(10)])
        boq_b = _make_boq(items=[_make_item(oz=f"99.{i:04d}") for i in range(10)])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert any("Low match ratio" in w for w in result.warnings)

    def test_version_mismatch_warning(self):
        doc_a = _make_doc(source_version=SourceVersion.DA_XML_33)
        doc_b = _make_doc(source_version=SourceVersion.DA_XML_20)
        result = BoQDiff.compare(doc_a, doc_b)
        assert any("versions differ" in w for w in result.warnings)

    def test_max_significance_critical(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010", unit_price=Decimal("100"))])
        boq_b = _make_boq(items=[_make_item(oz="01.0010", unit_price=Decimal("200"))])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.max_significance == Significance.CRITICAL


# ── DiffResult Model Tests ─────────────────────────────────────────────

class TestDiffResultModels:
    def test_item_modified_max_significance(self):
        changes = [
            FieldChange(field="short_text", significance=Significance.MEDIUM),
            FieldChange(field="unit_price", significance=Significance.CRITICAL),
        ]
        modified = ItemModified(oz="01.0010", changes=changes)
        assert modified.max_significance == Significance.CRITICAL

    def test_item_modified_filter_changes(self):
        changes = [
            FieldChange(field="bim_guid", significance=Significance.LOW),
            FieldChange(field="short_text", significance=Significance.MEDIUM),
            FieldChange(field="unit_price", significance=Significance.CRITICAL),
        ]
        modified = ItemModified(oz="01.0010", changes=changes)
        high_plus = modified.filter_changes(Significance.HIGH)
        assert len(high_plus) == 1
        assert high_plus[0].field == "unit_price"

    def test_item_modified_no_changes_is_low(self):
        modified = ItemModified(oz="01.0010")
        assert modified.max_significance == Significance.LOW

    def test_field_change_is_numeric(self):
        fc = FieldChange(
            field="qty", absolute_delta=Decimal("10"), percent_delta=50.0,
        )
        assert fc.is_numeric is True

    def test_field_change_non_numeric(self):
        fc = FieldChange(field="short_text")
        assert fc.is_numeric is False

    def test_significance_ordering(self):
        assert Significance.CRITICAL.value == "critical"
        assert Significance.HIGH.value == "high"
        assert Significance.MEDIUM.value == "medium"
        assert Significance.LOW.value == "low"

    def test_diff_mode_values(self):
        assert DiffMode.DEFAULT.value == "default"
        assert DiffMode.STRICT.value == "strict"
        assert DiffMode.FORCE.value == "force"


# ── Lazy Import Tests ──────────────────────────────────────────────────

class TestLazyImports:
    def test_import_boq_diff_from_pygaeb(self):
        from pygaeb import BoQDiff as BD
        assert BD is BoQDiff

    def test_import_diff_mode_from_pygaeb(self):
        from pygaeb import DiffMode as DM
        assert DM is DiffMode

    def test_import_diff_result_from_pygaeb(self):
        from pygaeb import DiffResult as DR
        assert DR is DiffResult

    def test_import_significance_from_pygaeb(self):
        from pygaeb import Significance as S
        assert S is Significance


# ── Edge Cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_documents(self):
        boq = BoQ(lots=[Lot(rno="1", label="Empty")])
        doc = _make_doc(boq=boq)
        result = BoQDiff.compare(doc, doc)
        assert result.summary.has_changes is False
        assert result.summary.total_changes == 0

    def test_single_item_added_to_empty(self):
        boq_a = BoQ(lots=[Lot(rno="1", label="Empty")])
        boq_b = _make_boq(items=[_make_item(oz="01.0010")])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.items_added == 1
        assert result.summary.items_removed == 0

    def test_all_items_removed(self):
        boq_a = _make_boq(items=[_make_item(oz="01.0010")])
        boq_b = BoQ(lots=[Lot(rno="1", label="Empty")])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.items_removed == 1
        assert result.summary.items_added == 0

    def test_many_items_performance(self):
        """Verify diff handles a moderately large BoQ without error."""
        items_a = [_make_item(oz=f"01.{i:04d}") for i in range(200)]
        items_b = [_make_item(oz=f"01.{i:04d}") for i in range(200)]
        items_b[50] = _make_item(oz="01.0050", unit_price=Decimal("999"))
        boq_a = _make_boq(items=items_a)
        boq_b = _make_boq(items=items_b)
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        assert result.summary.items_modified >= 1
        assert result.summary.items_unchanged >= 190

    def test_serialization_round_trip(self):
        """DiffResult should serialize to JSON and back."""
        boq_a = _make_boq(items=[_make_item(oz="01.0010", unit_price=Decimal("100"))])
        boq_b = _make_boq(items=[_make_item(oz="01.0010", unit_price=Decimal("120"))])
        result = BoQDiff.compare(_make_doc(boq=boq_a), _make_doc(boq=boq_b))
        json_str = result.model_dump_json()
        restored = DiffResult.model_validate_json(json_str)
        assert restored.summary.items_modified == result.summary.items_modified
        assert len(restored.items.modified) == len(result.items.modified)

    def test_no_project_no_still_compares(self):
        doc_a = _make_doc(project_no=None)
        doc_b = _make_doc(project_no=None)
        result = BoQDiff.compare(doc_a, doc_b)
        assert result.summary.is_likely_same_project is True
        assert not any("different projects" in w for w in result.warnings)
