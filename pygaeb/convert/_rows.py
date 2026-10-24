"""One flat row per item, for every document kind: the table behind ``to_csv``.

Values stay typed (``Decimal``, ``bool``, ``datetime``, ``None``); each export
formats them its own way.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pygaeb.models.cost import CostElement, ECBody
from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import ClassificationResult, Item
from pygaeb.models.order import OrderItem
from pygaeb.models.quantity import QtyItem

_CLASSIFICATION = [
    "trade", "element_type", "sub_type", "classification_confidence", "classification_flag",
]

TENDER_COLUMNS = [
    "oz", "full_oz", "short_text", "qty", "unit", "unit_price", "total_price",
    "computed_total", "item_type", "lot_label", "hierarchy_path", "has_attachments",
    "bim_guid", *_CLASSIFICATION,
    # After the original columns, so files read by column position keep working.
    "affects_total", "provis", "markup_base",
]
TRADE_COLUMNS = [
    "item_id", "art_no", "supplier_art_no", "ean", "short_text", "qty", "unit",
    "offer_price", "net_price", "price_basis", "line_total", "is_service", "delivery_date",
    *_CLASSIFICATION,
]
COST_COLUMNS = [
    "ele_no", "parent_ele_no", "hierarchy_path", "short_text", "qty", "unit", "unit_price",
    "item_total", "markup", "up_from", "up_avg", "up_to", "is_bill_element", "remark",
    *_CLASSIFICATION,
]
QUANTITY_COLUMNS = ["oz", "qty", "takeoff_rows"]

# Typed columns, for exports that keep types: a column with no value still gets its type.
DECIMAL_COLUMNS = frozenset({
    "qty", "unit_price", "total_price", "computed_total", "markup_base",
    "offer_price", "net_price", "price_basis", "line_total",
    "item_total", "markup", "up_from", "up_avg", "up_to",
})
FLOAT_COLUMNS = frozenset({"classification_confidence"})
DATE_COLUMNS = frozenset({"delivery_date"})


@dataclass
class ItemTable:
    """The columns of a document's kind and one row of typed values per item."""

    columns: list[str]
    rows: list[dict[str, Any]]


def item_table(doc: GAEBDocument) -> ItemTable:
    """The document's items in ``doc.iter_items()`` order, as rows of its kind's columns."""
    if doc.qty_determination is not None:
        return ItemTable(QUANTITY_COLUMNS, [
            _quantity_row(item) for item in doc.qty_determination.iter_items()
        ])
    if doc.elemental_costing is not None:
        return ItemTable(COST_COLUMNS, list(_cost_rows(doc.elemental_costing.body, [])))
    if doc.order is not None:
        return ItemTable(TRADE_COLUMNS, [_trade_row(item) for item in doc.order.iter_items()])
    return ItemTable(TENDER_COLUMNS, [_tender_row(item) for item in doc.award.boq.iter_items()])


def _tender_row(item: Item) -> dict[str, Any]:
    return {
        "oz": item.oz,
        "full_oz": item.full_oz,
        "short_text": item.short_text,
        "qty": item.qty,
        "unit": item.unit,
        "unit_price": item.unit_price,
        "total_price": item.total_price,
        "computed_total": item.computed_total,
        "item_type": item.item_type.value,
        "lot_label": item.lot_label,
        "hierarchy_path": " > ".join(item.hierarchy_path),
        "has_attachments": item.has_attachments,
        "bim_guid": item.bim_guid,
        **_classification(item.classification),
        "affects_total": item.affects_total,
        "provis": item.provis.value if item.provis is not None else None,
        "markup_base": item.markup_base,
    }


def _trade_row(item: OrderItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "art_no": item.art_no,
        "supplier_art_no": item.supplier_art_no,
        "ean": item.ean,
        "short_text": item.short_text,
        "qty": item.qty,
        "unit": item.unit,
        "offer_price": item.offer_price,
        "net_price": item.net_price,
        "price_basis": item.price_basis,
        "line_total": item.line_total,
        "is_service": item.is_service,
        "delivery_date": item.delivery_date,
        **_classification(item.classification),
    }


def _cost_rows(body: ECBody, path: list[str]) -> Iterator[dict[str, Any]]:
    """Cost elements in ``iter_items`` order, each with its category path."""
    for element in body.cost_elements:
        yield from _cost_element_rows(element, path, parent="")
    for ctgy in body.categories:
        if ctgy.body is not None:
            yield from _cost_rows(ctgy.body, [*path, ctgy.description])


def _cost_element_rows(
    element: CostElement, path: list[str], parent: str,
) -> Iterator[dict[str, Any]]:
    yield {
        "ele_no": element.ele_no,
        "parent_ele_no": parent,
        "hierarchy_path": " > ".join(path),
        "short_text": element.short_text,
        "qty": element.qty,
        "unit": element.unit,
        "unit_price": element.unit_price,
        "item_total": element.item_total,
        "markup": element.markup,
        "up_from": element.up_from,
        "up_avg": element.up_avg,
        "up_to": element.up_to,
        "is_bill_element": element.is_bill_element,
        "remark": element.remark,
        **_classification(element.classification),
    }
    for child in element.children:
        yield from _cost_element_rows(child, path, parent=element.ele_no)


def _quantity_row(item: QtyItem) -> dict[str, Any]:
    return {"oz": item.oz, "qty": item.qty, "takeoff_rows": len(item.determ_items)}


def _classification(result: ClassificationResult | None) -> dict[str, Any]:
    if result is None:
        return dict.fromkeys(_CLASSIFICATION)
    return {
        "trade": result.trade,
        "element_type": result.element_type,
        "sub_type": result.sub_type,
        "classification_confidence": result.confidence,
        "classification_flag": result.flag.value,
    }
