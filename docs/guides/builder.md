# BoQ Builder

Build GAEB procurement documents from scratch using a fluent, Pythonic API. The builder handles OZ generation, Decimal conversion, totals computation, and validates against phase-specific and version-specific rules.

## Quick Start

```python
from pygaeb import BoQBuilder

builder = BoQBuilder(phase="X83", version="3.3")
builder.project(no="PRJ-001", name="School Renovation", currency="EUR")

cat = builder.add_category("01", "Concrete Work")
cat.add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)
cat.add_item("01.0020", "Columns",   qty=40,  unit="m3", unit_price=95)

doc = builder.build()
```

The result is a standard `GAEBDocument` — you can inspect it, serialize it, or write it to XML with `GAEBWriter`.

## Single vs Multi-Lot

### Implicit lot (most common)

If your document has only one lot, use `builder.add_category()` directly. An implicit lot with `rno="1"` is created automatically:

```python
builder = BoQBuilder()
cat = builder.add_category("01", "Structural")
cat.add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)
```

### Explicit lots

```python
builder = BoQBuilder()
lot1 = builder.add_lot("1", "Structural Work")
lot1.add_category("01", "Concrete").add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)

lot2 = builder.add_lot("2", "MEP")
lot2.add_category("01", "Electrical").add_item("01.0010", "Cable tray", qty=200, unit="m", unit_price=15)
```

You cannot mix implicit and explicit lots — calling `add_category()` after `add_lot()` raises `ValueError`.

## Nested Categories

Categories can contain subcategories for deeper hierarchy:

```python
rohbau = lot.add_category("01", "Rohbau")
mauer = rohbau.add_subcategory("01.01", "Mauerwerk")
mauer.add_item("01.01.0010", "Innenwand", qty=100, unit="m2", unit_price=45)
mauer.add_item("01.01.0020", "Aussenwand", qty=80, unit="m2", unit_price=68)
```

## Auto OZ Generation

If you omit the `oz` parameter, the builder generates it from the category `rno` + a sequence counter (10, 20, 30...):

```python
cat = builder.add_category("01", "Section")
cat.add_item(short_text="First")   # oz = "01.0010"
cat.add_item(short_text="Second")  # oz = "01.0020"
cat.add_item(short_text="Third")   # oz = "01.0030"
```

You can mix auto and explicit OZ freely within the same category.

## Decimal Convenience

Pass `int`, `float`, or `Decimal` for numeric fields — the builder converts to `Decimal` automatically:

```python
cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=45.99)
# qty → Decimal("10"), unit_price → Decimal("45.99")
```

If `qty` and `unit_price` are set but `total_price` is not, the builder computes it:

```python
cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50)
# total_price → Decimal("500.00")  (auto-computed)
```

## Long Text & Attachments

`add_item()` returns an `ItemHandle` for fluent post-construction:

```python
handle = cat.add_item("01.0010", "Item", qty=10, unit="m2", unit_price=50)
handle.set_long_text("Detailed specification for the item...")
handle.add_attachment("drawing.pdf", pdf_bytes, mime_type="application/pdf")
```

Chaining is supported:

```python
cat.add_item("01.0010", "Item") \
   .set_long_text("Details") \
   .add_attachment("plan.pdf", data)
```

## Additional Fields via kwargs

Any `Item` model field can be passed as a keyword argument:

```python
cat.add_item(
    "01.0010", "Item",
    qty=10, unit="m2", unit_price=50,
    item_type=ItemType.ALTERNATIVE,
    bim_guid="abc-123",
)
```

Unknown field names raise `ValueError` with suggestions for likely typos:

```python
cat.add_item("01.0010", "Item", unit_prce=50)
# ValueError: Unknown Item field 'unit_prce'. Did you mean: 'unit_price'?
```

## Phase-Aware Rules

The builder understands GAEB exchange phase semantics:

| Phase | Rule |
|-------|------|
| X80 (blank BoQ) | Warns if `unit_price` or `total_price` is set |
| X83 (tender with prices) | Warns if `unit_price` is missing |
| X84 (award) | Warns if `unit_price` is missing |

Warnings are attached to the document's `validation_results`:

```python
builder = BoQBuilder(phase="X80")
cat = builder.add_category("01", "A")
cat.add_item("01.0010", "Item", unit_price=50)

doc = builder.build()
for result in doc.validation_results:
    print(result.message)
# "Item 01.0010: 'unit_price' is set but phase X80 (blank BoQ) typically should not have it."
```

## Version Compatibility

Fields are checked against the target GAEB version:

```python
builder = BoQBuilder(version="3.0")
cat = builder.add_category("01", "A")
cat.add_item("01.0010", "Item", bim_guid="abc-123")

doc = builder.build()
# Warning: "'bim_guid' requires DA XML 3.3+, but target is 3.0. This field will be dropped during export."
```

## Strict Mode

By default, phase and version issues produce warnings. Use `strict=True` to raise errors instead:

```python
doc = builder.build(strict=True)
# ValueError: Item 01.0010: 'unit_price' is set but phase X80 ...
```

## Duplicate OZ Detection

The builder detects duplicate OZ numbers within a lot:

```python
cat.add_item("01.0010", "First")
cat.add_item("01.0010", "Duplicate")

doc = builder.build()  # Warning about duplicate OZ
doc = builder.build(strict=True)  # Raises ValueError
```

Same OZ across different lots is allowed (each lot is an independent namespace).

## Optional XSD Validation

If you have official GAEB XSD schemas, pass the directory at build time:

```python
doc = builder.build(xsd_dir="/path/to/schemas")
```

The builder serializes the document to XML in memory, then validates against the XSD. Validation results are attached as warnings.

## Auto Totals & BoQBkdn

The builder automatically:

- Computes **lot subtotals** from item total prices
- Infers **BoQBkdn** (breakdown structure) from the observed hierarchy depth and rno lengths

## Writing to XML

Since `build()` returns a standard `GAEBDocument`, the existing `GAEBWriter` works directly:

```python
from pygaeb import GAEBWriter

doc = builder.build()
GAEBWriter.write(doc, "output.X83")
# or
xml_bytes, warnings = GAEBWriter.to_bytes(doc)
```

## Complete Example

```python
from pygaeb import BoQBuilder, GAEBWriter

builder = BoQBuilder(phase="X83", version="3.3")
builder.project(no="PRJ-2026-001", name="Office Building", currency="EUR")

# Lot 1 — Structural
lot1 = builder.add_lot("1", "Structural Work")
concrete = lot1.add_category("01", "Concrete")
concrete.add_item("01.0010", "Foundation",  qty=120, unit="m3", unit_price=85)
concrete.add_item("01.0020", "Floor slabs", qty=800, unit="m2", unit_price=45)

masonry = lot1.add_category("02", "Masonry")
masonry.add_item("02.0010", "Exterior walls", qty=600, unit="m2", unit_price=68)

# Lot 2 — MEP
lot2 = builder.add_lot("2", "MEP")
elec = lot2.add_category("01", "Electrical")
elec.add_item("01.0010", "Cable tray", qty=200, unit="m", unit_price=15)
(
    elec.add_item("01.0020", "Distribution board")
    .set_long_text("Main distribution board 400A, 3-phase, with surge protection.")
)

doc = builder.build()
GAEBWriter.write(doc, "office-building.X83")
```
