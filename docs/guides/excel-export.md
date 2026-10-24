# Excel Export

Export any GAEB document to a structured Excel workbook with hierarchy-aware layout, phase-specific columns, and optional classification data.

## Installation

Excel export requires `openpyxl`:

```bash
pip install pyGAEB[excel]
```

## Quick Start

```python
from pygaeb import GAEBParser
from pygaeb.convert import to_excel

doc = GAEBParser.parse("tender.X83")
to_excel(doc, "tender.xlsx")
```

## Export Modes

### Structured (default)

A single sheet with lots and categories as header rows, items as data rows, subtotals, and a grand total:

```python
to_excel(doc, "output.xlsx", mode="structured")
```

The sheet layout preserves the BoQ hierarchy:

```
OZ       | Description      | Qty | Unit | Unit Price | Total Price
---------|------------------|-----|------|------------|------------
Lot 1 — Structural Work
  01 — Concrete
  01.0010 | Foundation       | 120 | m3   | 85.00      | 10,200.00
  01.0020 | Columns          | 40  | m3   | 95.00      | 3,800.00
  Subtotal 01: 14,000.00
Lot Subtotal: 54,800.00
GRAND TOTAL: 54,800.00
```

### Full (multi-sheet)

Four sheets for comprehensive reporting:

```python
to_excel(doc, "output.xlsx", mode="full")
```

| Sheet | Content |
|-------|---------|
| **BoQ** | Same structured layout as above |
| **Items** | Flat table with one row per item (filterable/pivotable) |
| **Summary** | Per-lot totals, item counts, grand total |
| **Info** | Project metadata: name, phase, version, currency |

## All Document Types Supported

The exporter auto-detects the document kind and uses appropriate columns:

```python
# Procurement (X80-X89)
doc = GAEBParser.parse("tender.X83")
to_excel(doc, "procurement.xlsx")

# Trade (X93-X97)
doc = GAEBParser.parse("order.X96")
to_excel(doc, "trade.xlsx")

# Cost (X50-X52)
doc = GAEBParser.parse("cost.X50")
to_excel(doc, "cost.xlsx")

# Quantity Determination (X31)
doc = GAEBParser.parse("qty.X31")
to_excel(doc, "quantity.xlsx")
```

### Phase-Specific Columns

| Document Kind | Default Columns |
|--------------|----------------|
| Procurement | OZ, Description, Qty, Unit, Unit Price, Total Price, Computed Total, Item Type, Hierarchy |
| Trade | Item ID, Article No., Description, Qty, Unit, Offer Price, Net Price, Price Basis, Line Total, Service |
| Cost | Element No., Description, Qty, Unit, Unit Price, Total, Markup, Category ID |
| Quantity | OZ, RNo Part, Qty, Determinations |

The procurement OZ column holds the full OZ (`01.01.001`), not the item's own part. A trade price refers to *Price Basis* units (5.00 per 100 pieces), so *Line Total* is net price × quantity ÷ price basis, and the sheet's total sits under it.

## Optional Columns

Add extra columns via include flags:

```python
to_excel(
    doc,
    "output.xlsx",
    include_long_text=True,         # "Long Text" column
    include_classification=True,    # Trade, Element Type, Confidence columns
    include_bim_guid=True,          # BIM GUID column (procurement only)
)
```

## Formatting

The exporter applies minimal, clean formatting:

- **Bold headers** with frozen first row
- **Auto column widths** based on content (capped at 60 characters)
- **Number formatting**: currency columns use `#,##0.00`, quantity columns use `#,##0.000`; Excel shows both in the reader's own locale
- **Markup items** show their percentage in the Unit Price column (`10.00 %`) and leave Total Price empty
- **Bold section headers** for lots and categories
- **Bold subtotals** and grand total

## Live Formulas

With `formulas=True`, a procurement workbook recalculates in Excel:

```python
to_excel(doc, "pricing.xlsx", formulas=True)
```

- Each item total becomes `=ROUND(Qty*UnitPrice,2)`, rounded the way pyGAEB rounds `Item.computed_total`.
- Each category subtotal becomes `=SUM` over its items' totals and its subcategories' subtotals; lot subtotals and the grand total sum the level below.
- Items that pyGAEB leaves out of its sums (alternatives, optional items without total, and other positions that do not count) keep their own total cell but are not part of any `=SUM`, so the formulas reproduce `ctgy.subtotal` and `doc.grand_total`. Markups and optional items with total are part of the sums.

These are the only formulas in a workbook. Text from the document is always stored as text, so a short text that starts with `=`, such as `=HYPERLINK(...)` from a bidder's file, shows as text and never runs, with or without `formulas=True`.

## Tracing Cells Back to the Document

`on_cell` is called with an `ExcelCell` for every non-empty cell, sheet by sheet in row order. It carries the sheet, coordinate, value, the column's field (`"full_oz"`, `"qty"`, …) or the row's kind (`"subtotal"`, `"grand_total"`, …), and the item, category or lot it came from.

```python
from pygaeb.convert.to_excel import to_excel

cells = []
to_excel(doc, "tender.xlsx", on_cell=cells.append)

for cell in cells:
    if cell.key == "total_price":
        print(cell.coordinate, cell.item.full_oz, cell.value)
```

## Built Documents

Documents created with `BoQBuilder` export directly:

```python
from pygaeb import BoQBuilder
from pygaeb.convert import to_excel

builder = BoQBuilder(phase="X83", version="3.3")
builder.project(no="PRJ-001", name="Office Building", currency="EUR")
cat = builder.add_category("01", "Concrete")
cat.add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)

doc = builder.build()
to_excel(doc, "built.xlsx", mode="full")
```
