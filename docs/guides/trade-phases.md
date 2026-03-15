# Trade Phases (X93-X97)

pyGAEB supports GAEB trade phases alongside the standard procurement phases. Trade phases handle material ordering workflows between general contractors and suppliers.

## Supported Trade Phases

| Phase | Name                    | Description                              |
|-------|-------------------------|------------------------------------------|
| X93   | Trade Price Inquiry     | Request for quotation to suppliers       |
| X94   | Trade Price Offer       | Supplier's price response                |
| X96   | Trade Order             | Purchase order to supplier               |
| X97   | Trade Order Confirmation| Supplier's order acknowledgement         |

## Parsing Trade Files

Trade files are parsed with the same `GAEBParser.parse()` entry point — the library auto-detects trade vs. procurement:

```python
from pygaeb import GAEBParser, DocumentKind

doc = GAEBParser.parse("order.X96")

print(doc.document_kind)    # DocumentKind.TRADE
print(doc.is_trade)         # True
print(doc.exchange_phase)   # ExchangePhase.X96
```

## Document Structure

Trade documents use `<Order>` instead of `<Award>`, and contain a flat list of `OrderItem` elements instead of a hierarchical Bill of Quantities:

```python
# Trade-specific access
order = doc.order
print(order.dp)                          # "96"
print(order.order_info.order_no)         # "PO-2026-001"
print(order.supplier_info.address.name)  # "ACME Supplies"

for item in order.items:
    print(item.art_no, item.short_text)
    print(f"  Qty: {item.qty} {item.unit}")
    print(f"  Net: {item.net_price}")
```

## Universal Iteration

`doc.iter_items()` works for both procurement and trade documents, making LLM pipelines work unchanged:

```python
# Works for ANY document kind
for item in doc.iter_items():
    print(item.short_text, item.qty, item.unit)
```

## Discriminating Document Kind

Use `is_trade` / `is_procurement` or `document_kind` to branch:

```python
if doc.is_trade:
    for item in doc.order.items:
        print(item.art_no, item.net_price)
elif doc.is_procurement:
    for item in doc.award.boq.iter_items():
        print(item.oz, item.unit_price)
```

## OrderItem Fields

`OrderItem` carries trade-specific fields not found on procurement `Item`:

| Field              | Type          | Description                        |
|--------------------|---------------|------------------------------------|
| `item_id`          | `str`         | XML item identifier                |
| `ean`              | `str \| None` | EAN/GTIN barcode                   |
| `art_no`           | `str \| None` | Article number                     |
| `supplier_art_no`  | `str \| None` | Supplier's article number          |
| `customer_art_no`  | `str \| None` | Customer's article number          |
| `catalog_art_no`   | `str \| None` | Catalog article number             |
| `offer_price`      | `Decimal`     | Gross/list price                   |
| `net_price`        | `Decimal`     | Customer purchase price            |
| `price_basis`      | `Decimal`     | Price per N units                  |
| `delivery_chara`   | `str \| None` | Delivery characteristic            |
| `delivery_date`    | `datetime`    | Expected delivery date             |
| `mode_of_shipment` | `str \| None` | Shipping method                    |
| `is_service`       | `bool`        | Whether this is a service item     |

Shared fields (`short_text`, `long_text`, `qty`, `unit`, `classification`, `extractions`) work identically to procurement items.

## LLM Classification and Extraction

LLM features work on trade documents without code changes:

```python
from pygaeb import LLMClassifier, StructuredExtractor

classifier = LLMClassifier(model="openai/gpt-4o")
await classifier.enrich(doc)  # classifies OrderItem instances

extractor = StructuredExtractor(model="openai/gpt-4o")
results = await extractor.extract(doc, schema=MySchema, element_type="Pipe")
```

## Writing Trade Documents

```python
from pygaeb import GAEBWriter, ExchangePhase

# Write to file
GAEBWriter.write(doc, "output.X96", phase=ExchangePhase.X96)

# Serialize to bytes
xml_bytes, warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X96)
```

## DocumentAPI

The `DocumentAPI` wrapper is trade-aware:

```python
from pygaeb import DocumentAPI

api = DocumentAPI(doc)
print(api.document_kind)         # DocumentKind.TRADE
print(api.order.supplier_info)   # SupplierInfo(...)

item = api.get_order_item("PIPE-DN100")
summary = api.summary()
```
