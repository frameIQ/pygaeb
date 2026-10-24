"""Export GAEBDocument to Excel (.xlsx) with structure-aware layout.

Supports all four document kinds (procurement, trade, cost, quantity) and
two modes: ``structured`` (single hierarchy-aware sheet) or ``full``
(multi-sheet workbook with BoQ, Items, Summary, and Info sheets).

Requires ``openpyxl``: ``pip install pyGAEB[excel]``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pygaeb.models.boq import Lot
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import DocumentKind, ItemType
from pygaeb.models.item import Item

_CURRENCY_FMT = '#,##0.00'
_QTY_FMT = '#,##0.000'
_RATE_FMT = '0.00" %"'
_MAX_COL_WIDTH = 60
_MIN_COL_WIDTH = 8
_MAX_DEPTH = 50
_MAX_SUM_ARGS = 255  # Excel accepts at most 255 arguments per function


@dataclass(frozen=True)
class ColumnDef:
    """Definition of an Excel column."""

    key: str
    header: str
    width: int = 14
    number_format: str | None = None


@dataclass(frozen=True)
class ExcelCell:
    """One cell written by :func:`to_excel`, and where its value came from.

    ``key`` is the column's field for item rows (``"full_oz"``, ``"qty"``, …) and the
    row's kind otherwise: ``"header"``, ``"lot"``, ``"category"``, ``"subtotal"``,
    ``"lot_subtotal"``, ``"grand_total"``, ``"summary"`` or ``"info"``.
    """

    sheet: str
    coordinate: str
    row: int
    column: int
    value: Any
    key: str
    item: BaseModel | None = None
    category: BaseModel | None = None
    lot: Lot | None = None


_PROCUREMENT_COLS = [
    ColumnDef("full_oz", "OZ", 14),
    ColumnDef("short_text", "Description", 40),
    ColumnDef("qty", "Qty", 12, _QTY_FMT),
    ColumnDef("unit", "Unit", 8),
    ColumnDef("unit_price", "Unit Price", 14, _CURRENCY_FMT),
    ColumnDef("total_price", "Total Price", 16, _CURRENCY_FMT),
    ColumnDef("computed_total", "Computed Total", 16, _CURRENCY_FMT),
    ColumnDef("item_type", "Item Type", 14),
    ColumnDef("hierarchy_path", "Hierarchy", 30),
]

_TRADE_COLS = [
    ColumnDef("item_id", "Item ID", 14),
    ColumnDef("art_no", "Article No.", 16),
    ColumnDef("short_text", "Description", 40),
    ColumnDef("qty", "Qty", 12, _QTY_FMT),
    ColumnDef("unit", "Unit", 8),
    ColumnDef("offer_price", "Offer Price", 14, _CURRENCY_FMT),
    ColumnDef("net_price", "Net Price", 14, _CURRENCY_FMT),
    ColumnDef("price_basis", "Price Basis", 12),
    ColumnDef("line_total", "Line Total", 16, _CURRENCY_FMT),
    ColumnDef("is_service", "Service", 10),
]

_COST_COLS = [
    ColumnDef("ele_no", "Element No.", 14),
    ColumnDef("short_text", "Description", 40),
    ColumnDef("qty", "Qty", 12, _QTY_FMT),
    ColumnDef("unit", "Unit", 8),
    ColumnDef("unit_price", "Unit Price", 14, _CURRENCY_FMT),
    ColumnDef("item_total", "Total", 16, _CURRENCY_FMT),
    ColumnDef("markup", "Markup", 12, _CURRENCY_FMT),
    ColumnDef("cat_id", "Category ID", 14),
]

_QTY_COLS = [
    ColumnDef("oz", "OZ", 14),
    ColumnDef("rno_part", "RNo Part", 12),
    ColumnDef("qty", "Qty", 12, _QTY_FMT),
    ColumnDef("determ_count", "Determinations", 16),
]

_OPTIONAL_COLS = {
    "long_text": ColumnDef("long_text_plain", "Long Text", 50),
    "classification_trade": ColumnDef("classification_trade", "Trade", 16),
    "classification_element": ColumnDef("classification_element_type", "Element Type", 20),
    "classification_confidence": ColumnDef("classification_confidence", "Confidence", 12, '0.00'),
    "bim_guid": ColumnDef("bim_guid", "BIM GUID", 36),
}

_COLUMNS_BY_KIND = {
    DocumentKind.PROCUREMENT: _PROCUREMENT_COLS,
    DocumentKind.TRADE: _TRADE_COLS,
    DocumentKind.COST: _COST_COLS,
    DocumentKind.QUANTITY: _QTY_COLS,
}


@dataclass(frozen=True)
class _RowSource:
    kind: str
    item: BaseModel | None = None
    category: BaseModel | None = None
    lot: Lot | None = None


@dataclass
class _Sheet:
    """A worksheet being written, with what each row holds."""

    ws: Any
    columns: list[ColumnDef]
    formulas: bool = False
    rows: dict[int, _RowSource] = field(default_factory=dict)
    #: Coordinates of the formulas pyGAEB wrote; every other formula-like value is text.
    own_formulas: set[str] = field(default_factory=set)

    def column(self, key: str) -> int:
        """1-based index of the column with ``key``, or 0 if the sheet has none."""
        for index, col in enumerate(self.columns, start=1):
            if col.key == key:
                return index
        return 0


def _ensure_openpyxl() -> Any:
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        raise ImportError(
            "Excel export requires openpyxl. Install it with: pip install pyGAEB[excel]"
        ) from None


def _get_columns(
    doc: GAEBDocument,
    include_long_text: bool,
    include_classification: bool,
    include_bim_guid: bool,
) -> list[ColumnDef]:
    cols = list(_COLUMNS_BY_KIND[doc.document_kind])
    if include_long_text:
        cols.append(_OPTIONAL_COLS["long_text"])
    if include_classification:
        cols.append(_OPTIONAL_COLS["classification_trade"])
        cols.append(_OPTIONAL_COLS["classification_element"])
        cols.append(_OPTIONAL_COLS["classification_confidence"])
    if include_bim_guid and doc.document_kind == DocumentKind.PROCUREMENT:
        cols.append(_OPTIONAL_COLS["bim_guid"])
    return cols


def _get_item_value(item: Any, col: ColumnDef) -> Any:
    """Extract a value from an item for a given column definition."""
    key = col.key
    if key == "computed_total":
        return getattr(item, "computed_total", None)
    if key == "hierarchy_path":
        path = getattr(item, "hierarchy_path", None)
        return " > ".join(path) if path else ""
    if key == "item_type":
        it = getattr(item, "item_type", None)
        return it.value if it is not None else ""
    if key == "determ_count":
        determ = getattr(item, "determ_items", None)
        return len(determ) if determ else 0
    if key == "long_text_plain":
        return getattr(item, "long_text_plain", "")
    if key.startswith("classification_"):
        cls_obj = getattr(item, "classification", None)
        if cls_obj is None:
            return ""
        suffix = key.replace("classification_", "")
        return getattr(cls_obj, suffix, "")
    if key == "is_service":
        return "Yes" if getattr(item, "is_service", False) else ""

    val = getattr(item, key, None)
    if isinstance(val, Decimal):
        return float(val)
    return val if val is not None else ""


def to_excel(
    doc: GAEBDocument,
    path: str | Path,
    *,
    mode: str = "structured",
    include_long_text: bool = False,
    include_classification: bool = False,
    include_bim_guid: bool = False,
    formulas: bool = False,
    on_cell: Callable[[ExcelCell], None] | None = None,
) -> None:
    """Export a GAEBDocument to an Excel workbook.

    Args:
        doc: The document to export.
        path: Output file path (.xlsx).
        mode: ``"structured"`` for a single hierarchy-aware sheet, or
              ``"full"`` for a multi-sheet workbook (BoQ + Items + Summary + Info).
        include_long_text: Add a "Long Text" column.
        include_classification: Add classification columns (trade, element_type, confidence).
        include_bim_guid: Add a "BIM GUID" column (procurement only).
        formulas: When ``True``, item totals become ``=ROUND(Qty*UnitPrice,2)`` and
            category, lot and grand totals become ``=SUM`` over the cells they add up,
            so changing a quantity or price in Excel updates every total above it.
            Procurement only.
        on_cell: Called with an :class:`ExcelCell` for every non-empty cell written,
            sheet by sheet in row order.
    """
    openpyxl = _ensure_openpyxl()
    if mode not in ("structured", "full"):
        raise ValueError(f"Invalid mode {mode!r}. Use 'structured' or 'full'.")

    wb = openpyxl.Workbook()
    columns = _get_columns(doc, include_long_text, include_classification, include_bim_guid)
    live = formulas and doc.is_procurement

    boq = _Sheet(wb.active, columns, live)
    boq.ws.title = "BoQ"
    _write_structured_sheet(boq, doc)
    _apply_formatting(boq.ws, columns)
    sheets = [(boq, "boq")]

    if mode == "full":
        items = _Sheet(wb.create_sheet("Items"), columns, live)
        _write_flat_items(items, doc)
        _apply_formatting(items.ws, columns)

        summary = _Sheet(wb.create_sheet("Summary"), [])
        _write_summary_sheet(summary.ws, doc)
        _apply_formatting_auto(summary.ws)

        info = _Sheet(wb.create_sheet("Info"), [])
        _write_info_sheet(info.ws, doc)
        _apply_formatting_auto(info.ws)
        sheets += [(items, "items"), (summary, "summary"), (info, "info")]

    for sheet, _ in sheets:
        store_text_as_text(sheet.ws, sheet.own_formulas)

    if on_cell is not None:
        for sheet, default_key in sheets:
            _report_cells(sheet, on_cell, default_key)

    wb.save(Path(path))


def store_text_as_text(ws: Any, own_formulas: Collection[str] = ()) -> None:
    """Turn every formula pyGAEB did not write back into a plain text cell.

    openpyxl makes any string that starts with ``=`` a formula, so a document's text
    (a short text such as ``=HYPERLINK(...)``) would run when the workbook is opened.
    """
    for row in ws.iter_rows():
        for cell in row:
            if cell.data_type == "f" and cell.coordinate not in own_formulas:
                cell.data_type = "s"


def _report_cells(sheet: _Sheet, on_cell: Callable[[ExcelCell], None], default_key: str) -> None:
    for row in sheet.ws.iter_rows():
        for cell in row:
            if cell.value is None or cell.value == "":
                continue
            source = sheet.rows.get(cell.row, _RowSource(default_key))
            key = sheet.columns[cell.column - 1].key if source.kind == "item" else source.kind
            on_cell(ExcelCell(
                sheet=sheet.ws.title,
                coordinate=cell.coordinate,
                row=cell.row,
                column=cell.column,
                value=cell.value,
                key=key,
                item=source.item,
                category=source.category,
                lot=source.lot,
            ))


# ---------------------------------------------------------------------------
# Structured sheet writers (dispatched by DocumentKind)
# ---------------------------------------------------------------------------

def _write_structured_sheet(sheet: _Sheet, doc: GAEBDocument) -> None:
    writers = {
        DocumentKind.PROCUREMENT: _write_procurement_structured,
        DocumentKind.TRADE: _write_trade_structured,
        DocumentKind.COST: _write_cost_structured,
        DocumentKind.QUANTITY: _write_quantity_structured,
    }
    writers[doc.document_kind](sheet, doc)


def _write_header_row(sheet: _Sheet, row: int = 1) -> int:
    from openpyxl.styles import Font

    for col_idx, col_def in enumerate(sheet.columns, 1):
        cell = sheet.ws.cell(row=row, column=col_idx, value=col_def.header)
        cell.font = Font(bold=True)
    sheet.rows[row] = _RowSource("header")
    return row + 1


def _write_item_row(sheet: _Sheet, row: int, item: Any, source: _RowSource) -> int:
    # A markup's unit_price is its percentage, shown as one; total_price is its own amount.
    markup = isinstance(item, Item) and item.item_type is ItemType.MARKUP
    for col_idx, col_def in enumerate(sheet.columns, 1):
        val = _get_item_value(item, col_def)
        number_format = col_def.number_format
        if markup and col_def.key == "unit_price":
            number_format = _RATE_FMT
        cell = sheet.ws.cell(row=row, column=col_idx, value=val)
        if number_format and isinstance(val, (int, float)):
            cell.number_format = number_format
    if sheet.formulas and isinstance(item, Item) and not markup:
        _write_total_formula(sheet, row, item)
    sheet.rows[row] = source
    return row + 1


def _write_total_formula(sheet: _Sheet, row: int, item: Item) -> None:
    """``=ROUND(Qty*UnitPrice,2)``, rounding like :attr:`Item.computed_total`."""
    from openpyxl.utils import get_column_letter

    qty_col = sheet.column("qty")
    up_col = sheet.column("unit_price")
    total_col = sheet.column("total_price")
    if 0 in (qty_col, up_col, total_col) or item.total_price is None:
        return
    if item.qty is None or item.unit_price is None:
        return
    qty, up = get_column_letter(qty_col), get_column_letter(up_col)
    cell = sheet.ws.cell(row=row, column=total_col, value=f"=ROUND({qty}{row}*{up}{row},2)")
    sheet.own_formulas.add(cell.coordinate)


def _write_label_row(
    sheet: _Sheet, row: int, label: str, source: _RowSource, *, bold: bool = True
) -> int:
    from openpyxl.styles import Font

    cell = sheet.ws.cell(row=row, column=1, value=label)
    cell.font = Font(bold=bold)
    sheet.rows[row] = source
    return row + 1


def _write_subtotal_row(
    sheet: _Sheet,
    row: int,
    label: str,
    value: Decimal | float,
    source: _RowSource,
    parts: list[int] | None = None,
) -> int:
    """A labelled total; with formulas on, ``=SUM`` over the rows in ``parts``."""
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    total_col = _find_total_column(sheet.columns)
    cell_label = sheet.ws.cell(row=row, column=max(1, total_col - 1), value=label)
    cell_label.font = Font(bold=True)
    val: str | float = float(value) if isinstance(value, Decimal) else value
    if sheet.formulas and parts:
        val = _sum_formula(get_column_letter(total_col), parts)
    cell_val = sheet.ws.cell(row=row, column=total_col, value=val)
    if isinstance(val, str):
        sheet.own_formulas.add(cell_val.coordinate)
    cell_val.font = Font(bold=True)
    cell_val.number_format = _CURRENCY_FMT
    sheet.rows[row] = source
    return row + 1


def _sum_formula(letter: str, rows: list[int]) -> str:
    """``=SUM`` over ``rows`` of one column, consecutive rows written as one range."""
    refs: list[str] = []
    for first, last in _runs(sorted(rows)):
        refs.append(f"{letter}{first}" if first == last else f"{letter}{first}:{letter}{last}")
    while len(refs) > _MAX_SUM_ARGS:
        refs = [
            f"SUM({','.join(refs[i:i + _MAX_SUM_ARGS])})"
            for i in range(0, len(refs), _MAX_SUM_ARGS)
        ]
    return f"=SUM({','.join(refs)})"


def _runs(rows: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for r in rows:
        if runs and r == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], r)
        else:
            runs.append((r, r))
    return runs


def _find_total_column(columns: list[ColumnDef]) -> int:
    for i, c in enumerate(columns, 1):
        if c.key in ("total_price", "line_total", "item_total"):
            return i
    return len(columns)


# ---------------------------------------------------------------------------
# Procurement structured writer
# ---------------------------------------------------------------------------

def _write_procurement_structured(sheet: _Sheet, doc: GAEBDocument) -> None:
    row = _write_header_row(sheet)
    lot_rows: list[int] = []

    for lot in doc.award.boq.lots:
        lot_label = f"Lot {lot.rno}"
        if lot.label:
            lot_label += f" — {lot.label}"
        row = _write_label_row(sheet, row, lot_label, _RowSource("lot", lot=lot))

        category_rows: list[int] = []
        for ctgy in lot.body.categories:
            row, subtotal_row = _write_procurement_category(sheet, row, ctgy, lot, depth=1)
            if subtotal_row is not None:
                category_rows.append(subtotal_row)

        lot_total = float(lot.subtotal)
        if lot_total:
            lot_rows.append(row)
            row = _write_subtotal_row(sheet, row, "Lot Subtotal", lot_total,
                                      _RowSource("lot_subtotal", lot=lot), category_rows)

    grand = float(doc.grand_total)
    if grand:
        row = _write_subtotal_row(sheet, row, "GRAND TOTAL", grand,
                                  _RowSource("grand_total"), lot_rows)


def _write_procurement_category(
    sheet: _Sheet, row: int, ctgy: Any, lot: Lot, depth: int
) -> tuple[int, int | None]:
    """Write a category; returns the next row and the row of its subtotal, if any."""
    if depth > _MAX_DEPTH:
        return row, None
    indent = "  " * depth
    label = f"{indent}{ctgy.rno}"
    if ctgy.label:
        label += f" — {ctgy.label}"
    row = _write_label_row(sheet, row, label, _RowSource("category", category=ctgy, lot=lot))

    # The rows a live subtotal adds up: what ctgy.subtotal sums, nothing else.
    parts: list[int] = []
    for item in ctgy.items:
        if item.affects_total and item.total_price is not None:
            parts.append(row)
        source = _RowSource("item", item=item, category=ctgy, lot=lot)
        row = _write_item_row(sheet, row, item, source)

    for sub in ctgy.subcategories:
        row, sub_row = _write_procurement_category(sheet, row, sub, lot, depth + 1)
        if sub_row is not None:
            parts.append(sub_row)

    subtotal = float(ctgy.subtotal)
    if subtotal and (ctgy.items or ctgy.subcategories):
        subtotal_row = row
        row = _write_subtotal_row(sheet, row, f"{indent}Subtotal {ctgy.rno}", subtotal,
                                  _RowSource("subtotal", category=ctgy, lot=lot), parts)
        return row, subtotal_row
    return row, None


# ---------------------------------------------------------------------------
# Trade structured writer
# ---------------------------------------------------------------------------

def _write_trade_structured(sheet: _Sheet, doc: GAEBDocument) -> None:
    row = _write_header_row(sheet)

    if doc.order is None:
        return

    for item in doc.order.items:
        row = _write_item_row(sheet, row, item, _RowSource("item", item=item))

    grand = float(doc.order.grand_total)
    if grand:
        row = _write_subtotal_row(sheet, row, "TOTAL", grand, _RowSource("grand_total"))


# ---------------------------------------------------------------------------
# Cost structured writer
# ---------------------------------------------------------------------------

def _write_cost_structured(sheet: _Sheet, doc: GAEBDocument) -> None:
    row = _write_header_row(sheet)

    if doc.elemental_costing is None:
        return

    ec = doc.elemental_costing
    for ctgy in ec.body.categories:
        row = _write_cost_category(sheet, row, ctgy, depth=0)

    for ce in ec.body.cost_elements:
        row = _write_cost_element(sheet, row, ce, None, depth=0)

    grand = float(ec.grand_total)
    if grand:
        row = _write_subtotal_row(sheet, row, "GRAND TOTAL", grand, _RowSource("grand_total"))


def _write_cost_category(sheet: _Sheet, row: int, ctgy: Any, depth: int) -> int:
    if depth > _MAX_DEPTH:
        return row
    indent = "  " * depth
    label = f"{indent}{ctgy.ele_no}"
    if ctgy.description:
        label += f" — {ctgy.description}"
    row = _write_label_row(sheet, row, label, _RowSource("category", category=ctgy))

    if ctgy.body is not None:
        for sub in ctgy.body.categories:
            row = _write_cost_category(sheet, row, sub, depth + 1)
        for ce in ctgy.body.cost_elements:
            row = _write_cost_element(sheet, row, ce, ctgy, depth + 1)

    return row


def _write_cost_element(sheet: _Sheet, row: int, ce: Any, ctgy: Any, depth: int) -> int:
    if depth > _MAX_DEPTH:
        return row
    row = _write_item_row(sheet, row, ce, _RowSource("item", item=ce, category=ctgy))
    for child in ce.children:
        row = _write_cost_element(sheet, row, child, ctgy, depth + 1)
    return row


# ---------------------------------------------------------------------------
# Quantity structured writer
# ---------------------------------------------------------------------------

def _write_quantity_structured(sheet: _Sheet, doc: GAEBDocument) -> None:
    row = _write_header_row(sheet)

    if doc.qty_determination is None:
        return

    qd = doc.qty_determination
    for ctgy in qd.boq.body.categories:
        row = _write_qty_category(sheet, row, ctgy, depth=0)


def _write_qty_category(sheet: _Sheet, row: int, ctgy: Any, depth: int) -> int:
    if depth > _MAX_DEPTH:
        return row
    indent = "  " * depth
    label = f"{indent}Category {ctgy.rno}"
    row = _write_label_row(sheet, row, label, _RowSource("category", category=ctgy))

    for item in ctgy.items:
        row = _write_item_row(sheet, row, item, _RowSource("item", item=item, category=ctgy))

    for sub in ctgy.subcategories:
        row = _write_qty_category(sheet, row, sub, depth + 1)

    return row


# ---------------------------------------------------------------------------
# Flat items sheet (shared)
# ---------------------------------------------------------------------------

def _write_flat_items(sheet: _Sheet, doc: GAEBDocument) -> None:
    row = _write_header_row(sheet)
    for item in doc.iter_items():
        row = _write_item_row(sheet, row, item, _RowSource("item", item=item))


# ---------------------------------------------------------------------------
# Summary sheet
# ---------------------------------------------------------------------------

def _write_summary_sheet(ws: Any, doc: GAEBDocument) -> None:
    from openpyxl.styles import Font

    headers = ["Metric", "Value"]
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True)

    row = 2

    if doc.is_procurement:
        for lot in doc.award.boq.lots:
            lot_label = f"Lot {lot.rno}"
            if lot.label:
                lot_label += f" — {lot.label}"
            ws.cell(row=row, column=1, value=lot_label)
            ws.cell(row=row, column=2)
            row += 1

            item_count = sum(1 for _ in lot.iter_items())
            ws.cell(row=row, column=1, value="  Items")
            ws.cell(row=row, column=2, value=item_count)
            row += 1

            subtotal = float(lot.subtotal)
            ws.cell(row=row, column=1, value="  Subtotal")
            cell = ws.cell(row=row, column=2, value=subtotal)
            cell.number_format = _CURRENCY_FMT
            row += 1

        row += 1

    ws.cell(row=row, column=1, value="Total Items")
    ws.cell(row=row, column=2, value=doc.item_count)
    row += 1

    cell_label = ws.cell(row=row, column=1, value="Grand Total")
    cell_label.font = Font(bold=True)
    cell_val = ws.cell(row=row, column=2, value=float(doc.grand_total))
    cell_val.font = Font(bold=True)
    cell_val.number_format = _CURRENCY_FMT


# ---------------------------------------------------------------------------
# Info sheet
# ---------------------------------------------------------------------------

def _write_info_sheet(ws: Any, doc: GAEBDocument) -> None:
    from openpyxl.styles import Font

    headers = ["Property", "Value"]
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = Font(bold=True)

    info_rows: list[tuple[str, Any]] = [
        ("Document Kind", doc.document_kind.value),
        ("Exchange Phase", doc.exchange_phase.value),
        ("Source Version", doc.source_version.value),
        ("Source File", doc.source_file or ""),
    ]

    if doc.gaeb_info.prog_system:
        info_rows.append(("Program System", doc.gaeb_info.prog_system))
    if doc.gaeb_info.prog_system_version:
        info_rows.append(("Program Version", doc.gaeb_info.prog_system_version))

    if doc.is_procurement:
        award = doc.award
        if award.project_name:
            info_rows.append(("Project Name", award.project_name))
        if award.project_no:
            info_rows.append(("Project No.", award.project_no))
        if award.currency:
            info_rows.append(("Currency", award.currency))
        if award.client:
            info_rows.append(("Client", award.client))

    if doc.is_trade and doc.order is not None:
        oi = doc.order.order_info
        if oi is not None:
            if oi.order_no:
                info_rows.append(("Order No.", oi.order_no))
            if oi.currency:
                info_rows.append(("Currency", oi.currency))

    if doc.is_cost and doc.elemental_costing is not None:
        ec_info = doc.elemental_costing.ec_info
        if ec_info.name:
            info_rows.append(("Cost Estimation Name", ec_info.name))
        if ec_info.currency:
            info_rows.append(("Currency", ec_info.currency))

    for row_idx, (prop, val) in enumerate(info_rows, 2):
        ws.cell(row=row_idx, column=1, value=prop)
        ws.cell(row=row_idx, column=2, value=str(val) if val else "")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _apply_formatting(ws: Any, columns: list[ColumnDef]) -> None:
    """Apply minimal formatting: column widths and frozen header."""
    for col_idx, col_def in enumerate(columns, 1):
        max_len = col_def.width
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, values_only=False):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, min(len(str(cell.value)), _MAX_COL_WIDTH))
        col_letter = _col_letter(col_idx)
        ws.column_dimensions[col_letter].width = max(max_len + 2, _MIN_COL_WIDTH)

    ws.freeze_panes = "A2"


def _apply_formatting_auto(ws: Any) -> None:
    """Auto-width for simple sheets (Summary, Info)."""
    for col in ws.columns:
        max_len = _MIN_COL_WIDTH
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value is not None:
                max_len = max(max_len, min(len(str(cell.value)), _MAX_COL_WIDTH))
        ws.column_dimensions[col_letter].width = max_len + 2

    ws.freeze_panes = "A2"


def _col_letter(col_idx: int) -> str:
    from openpyxl.utils import get_column_letter
    return str(get_column_letter(col_idx))


__all__ = ["ColumnDef", "ExcelCell", "to_excel"]
