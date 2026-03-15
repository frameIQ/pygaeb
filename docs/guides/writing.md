# Writing & Export

pyGAEB supports writing GAEB DA XML files and exporting to JSON and CSV.

## Write GAEB DA XML

Write a document back to a GAEB file:

```python
from pygaeb import GAEBParser, GAEBWriter

doc = GAEBParser.parse("tender.X83")
GAEBWriter.write(doc, "output.X83")
```

### Round-Trip Editing

Parse a file, modify it, and write it back:

```python
from decimal import Decimal
from pygaeb import GAEBParser, GAEBWriter, ExchangePhase

doc = GAEBParser.parse("tender.X83")

# Modify prices (procurement)
for item in doc.award.boq.iter_items():
    if item.unit_price:
        item.unit_price = item.unit_price * Decimal("1.05")  # 5% markup

# Write as a bid (X84)
GAEBWriter.write(doc, "bid.X84", phase=ExchangePhase.X84)
```

### Phase Override

Change the exchange phase when writing:

```python
GAEBWriter.write(doc, "bid.X84", phase=ExchangePhase.X84)
GAEBWriter.write(doc, "invoice.X86", phase=ExchangePhase.X86)
```

### Writing Trade Documents

Trade documents (X93–X97) are written the same way:

```python
from pygaeb import GAEBParser, GAEBWriter, ExchangePhase

doc = GAEBParser.parse("order.X96")

# Modify a trade item
for item in doc.order.items:
    if item.net_price:
        item.net_price = item.net_price * Decimal("0.95")  # 5% discount

# Write as order confirmation
GAEBWriter.write(doc, "confirmation.X97", phase=ExchangePhase.X97)
```

The writer automatically detects trade documents and uses the correct XML structure (`<Order>/<OrderItem>`) and trade-specific namespaces.

### Target Version

By default, documents are written as DA XML 3.3. The writer outputs:

**Procurement documents:**

- Standard GAEB DA XML 3.3 namespace
- All BoQ structure (lots, categories, items)
- Item attributes (quantities, prices, units, text)
- Attachments (base64-encoded)
- GAEBInfo metadata (auto-populated with pyGAEB version)

**Trade documents:**

- Trade-specific namespace (e.g., `DA96/3.3`)
- Order structure (supplier/customer info, flat item list)
- Trade-specific fields (EAN, article number, delivery details)

## Export to JSON

Export the full nested BoQ tree as JSON:

```python
from pygaeb.convert import to_json, to_json_string

# Write to file
to_json(doc, "boq.json")

# Get as string
json_str = to_json_string(doc)

# Include binary attachments (base64)
to_json(doc, "boq_full.json", include_attachments=True)
```

By default, binary attachment data is stripped (metadata like filename and MIME type is kept). Pass `include_attachments=True` to include base64-encoded data.

## Export to CSV

Export a flat item table:

```python
from pygaeb.convert import to_csv

to_csv(doc, "items.csv")
```

The CSV includes columns for:

- Item identification: `oz`, `lot`, `hierarchy_path`
- Item text: `short_text`, `long_text`
- Quantities: `qty`, `unit`, `unit_price`, `total_price`, `computed_total`
- Type: `item_type`
- Classification (if available): `classification_trade`, `classification_element_type`, `classification_sub_type`, `classification_confidence`, `classification_flag`

!!! tip
    CSV export is useful for spreadsheet analysis, pivot tables, and feeding data into BI tools. The classification columns are only populated after running `LLMClassifier.enrich()`.
