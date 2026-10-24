"""``to_csv``: one row per item for every document kind, with that kind's columns."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from pygaeb import GAEBParser, to_csv
from pygaeb.models.document import GAEBDocument
from tests.document_kinds import DOCUMENT_KINDS

FIXTURES = Path(__file__).parent / "fixtures"

# The columns 1.19 wrote, in its order: new columns only ever go after them.
TENDER_COLUMNS_1_19 = [
    "oz", "full_oz", "short_text", "qty", "unit", "unit_price", "total_price",
    "computed_total", "item_type", "lot_label", "hierarchy_path", "has_attachments",
    "bim_guid", "trade", "element_type", "sub_type", "classification_confidence",
    "classification_flag",
]


def _rows(doc: GAEBDocument, tmp_path: Path) -> list[dict[str, str]]:
    out = tmp_path / "items.csv"
    to_csv(doc, out)
    with out.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse(kind: str) -> GAEBDocument:
    xml, filename = DOCUMENT_KINDS[kind]
    return GAEBParser.parse_string(xml, filename=filename)


@pytest.mark.parametrize("kind", list(DOCUMENT_KINDS))
def test_every_document_kind_gets_one_row_per_item(kind: str, tmp_path: Path) -> None:
    doc = _parse(kind)
    items = list(doc.iter_items())

    rows = _rows(doc, tmp_path)
    assert items
    assert len(rows) == len(items)
    assert [row["qty"] for row in rows] == [
        "" if item.qty is None else str(item.qty) for item in items
    ]


def test_tender_columns_keep_their_order_and_add_three_at_the_end(tmp_path: Path) -> None:
    out = tmp_path / "items.csv"
    to_csv(GAEBParser.parse(FIXTURES / "gaebxml.x83"), out)
    with out.open(encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))

    assert header == [*TENDER_COLUMNS_1_19, "affects_total", "provis", "markup_base"]


def test_tender_rows_rebuild_the_grand_total(tmp_path: Path) -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    rows = _rows(doc, tmp_path)

    counted = [row for row in rows if row["affects_total"] == "True"]
    assert sum(Decimal(row["total_price"]) for row in counted) == doc.grand_total
    assert doc.grand_total == Decimal("1755.00")
    markup = next(row for row in rows if row["item_type"] == "Markup")
    assert (markup["unit_price"], markup["markup_base"], markup["total_price"]) == (
        "10.00", "1000.00", "100.00",
    )
    eventual = next(row for row in rows if row["item_type"] == "Eventual")
    assert eventual["provis"] == "WithTotal"


def test_trade_rows_carry_prices_and_line_totals(tmp_path: Path) -> None:
    doc = _parse("X96 trade")
    rows = _rows(doc, tmp_path)

    assert rows[0]["art_no"] == "PIPE-DN100"
    assert rows[0]["ean"] == "4001234567890"
    assert rows[0]["delivery_date"] == "2026-02-01T00:00:00"
    assert doc.order is not None
    assert sum(Decimal(row["line_total"]) for row in rows) == doc.order.grand_total


def test_cost_rows_keep_their_tree(tmp_path: Path) -> None:
    rows = {row["ele_no"]: row for row in _rows(_parse("X50 cost elements"), tmp_path)}

    assert rows["310"]["parent_ele_no"] == ""
    assert rows["310.1"]["parent_ele_no"] == "310"
    assert rows["310.1"]["hierarchy_path"] == "Building construction costs"
    assert rows["410"]["hierarchy_path"] == "Technical installations"
    assert rows["310"]["item_total"] == "18000.00"


def test_quantity_rows_count_their_takeoff_rows(tmp_path: Path) -> None:
    rows = _rows(_parse("X31 quantities"), tmp_path)

    assert [(row["oz"], row["takeoff_rows"]) for row in rows] == [
        ("01.01.0010.A", "2"), ("01.01.0020", "1"), ("02.0010", "0"),
    ]
