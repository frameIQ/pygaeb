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
| Trade | Item ID, Article No., Description, Qty, Unit, Offer Price, Net Price, Service |
| Cost | Element No., Description, Qty, Unit, Unit Price, Total, Markup, Category ID |
| Quantity | OZ, RNo Part, Qty, Determinations |

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
- **Number formatting**: currency columns use `#,##0.00`, quantity columns use `#,##0.###`
- **Bold section headers** for lots and categories
- **Bold subtotals** and grand total

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
