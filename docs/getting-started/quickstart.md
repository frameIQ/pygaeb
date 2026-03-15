# Quick Start

This guide walks you through the core pyGAEB workflow: parse, iterate, validate, write, and export.

## Parse Any GAEB File

pyGAEB auto-detects the version and format — one method handles everything:

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("tender.X83")    # DA XML 3.x
doc = GAEBParser.parse("old.D83")       # DA XML 2.x — same call

print(doc.source_version)               # SourceVersion.DA_XML_33
print(doc.exchange_phase)               # ExchangePhase.X83
print(doc.grand_total)                  # Decimal("1234567.89")
```

You can also parse from bytes or strings (useful for web uploads, S3, etc.):

```python
doc = GAEBParser.parse_bytes(raw_bytes, filename="tender.X83")
doc = GAEBParser.parse_string(xml_text, filename="tender.X83")
```

The `filename` hint is used for version/phase detection from the extension.

## Iterate Items

Every parsed document exposes a unified structure — regardless of the source version:

```python
for item in doc.award.boq.iter_items():
    print(item.oz)              # "01.02.0030"
    print(item.short_text)      # "Mauerwerk der Innenwand…"
    print(item.qty)             # Decimal("1170.000")
    print(item.unit)            # "m2"
    print(item.unit_price)      # Decimal("45.50")
    print(item.total_price)     # Decimal("53235.00")
    print(item.item_type)       # ItemType.NORMAL
```

For code that should work on **both** procurement and trade documents, use universal iteration:

```python
for item in doc.iter_items():
    print(item.short_text, item.qty, item.unit)
```

Look up a specific item by its OZ (ordinal number):

```python
item = doc.award.boq.get_item("01.02.0030")
```

## Financial Summaries & Project Info

Procurement documents (X84 bids, X86 awards, X89 invoices) carry authoritative totals, VAT breakdowns, and discount data at the BoQ and category level:

```python
# BoQ-level totals (from the <Totals> element, not recomputed)
totals = doc.award.boq.boq_info.totals
if totals:
    print(totals.total_net)      # Decimal("95000.00")
    print(totals.total_gross)    # Decimal("113050.00")
    print(totals.vat)            # Decimal("19.00")  — VAT rate %
    print(totals.vat_amount)     # Decimal("18050.00")
    print(totals.discount_pcnt)  # Decimal("5.000000") or None

    # Multiple VAT rates (e.g., 19% + 7%)
    for vp in totals.vat_parts:
        print(f"{vp.vat_pcnt}%: net={vp.total_net_part}, vat={vp.vat_amount}")

# Category-level subtotals
for lot in doc.award.boq.lots:
    for ctgy in lot.body.categories:
        if ctgy.totals:
            print(f"{ctgy.label}: net={ctgy.totals.total_net}")

# Item-level VAT
for item in doc.award.boq.iter_items():
    if item.vat is not None:
        print(f"{item.oz}: VAT {item.vat}%")
```

Project metadata from `<PrjInfo>` is merged into `AwardInfo`:

```python
print(doc.award.project_name)     # "Neubau Schule"
print(doc.award.prj_id)           # project GUID
print(doc.award.lbl_prj)          # project label
print(doc.award.description)      # project description
print(doc.award.currency_label)   # "Euro"
print(doc.award.up_frac_dig)      # 2 or 3 — unit price decimal places
print(doc.award.bid_comm_perm)    # True/False
print(doc.award.alter_bid_perm)   # True/False
```

## Document Navigation

For advanced querying, use `DocumentAPI`:

```python
from pygaeb import DocumentAPI

api = DocumentAPI(doc)

# Filter items
expensive = api.filter_items(min_total=Decimal("10000"))
normals = api.filter_items(item_type=ItemType.NORMAL)
custom = api.filter_items(predicate=lambda i: "Fenster" in i.short_text)

# Walk the BoQ hierarchy
for depth, label, category in api.iter_hierarchy():
    print("  " * depth + label)

# Summary
print(api.summary())
```

## Validation

pyGAEB validates structural integrity, numeric accuracy, and phase-specific rules:

```python
from pygaeb import GAEBParser, ValidationMode

# Lenient (default) — collect warnings, keep parsing
doc = GAEBParser.parse("tender.X83")
for issue in doc.validation_results:
    print(issue.severity, issue.message)

# Strict — raise GAEBValidationError on first ERROR
doc = GAEBParser.parse("tender.X83", validation=ValidationMode.STRICT)
```

## Write / Round-Trip

Modify a document and write it back:

```python
from pygaeb import GAEBWriter, ExchangePhase
from decimal import Decimal

doc = GAEBParser.parse("tender.X83")
item = doc.award.boq.get_item("01.02.0030")
item.unit_price = Decimal("48.00")

GAEBWriter.write(doc, "bid.X84", phase=ExchangePhase.X84)
```

## Export

Export to JSON (full nested BoQ tree) or CSV (flat item table):

```python
from pygaeb.convert import to_json, to_csv

to_json(doc, "boq.json")
to_csv(doc, "items.csv")

# Or get a JSON string directly
from pygaeb.convert import to_json_string
json_str = to_json_string(doc)
```

## LLM Classification

Enrich items with semantic construction element types:

```python
from pygaeb import LLMClassifier

classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")

# Check cost before running
estimate = await classifier.estimate_cost(doc)
print(f"~${estimate.estimated_cost_usd:.2f} for {estimate.items_to_classify} items")

# Classify
await classifier.enrich(doc)

for item in doc.iter_items():
    if item.classification:
        print(item.short_text, item.classification.element_type, item.classification.confidence)
```

Classification works on both procurement and trade documents — `doc.iter_items()` handles both.

See the [Classification Guide](../guides/classification.md) for details on the taxonomy, confidence flags, and caching.

## Version Conversion

Convert GAEB files between any DA XML version:

```python
from pygaeb import GAEBConverter, SourceVersion

# Upgrade 2.x → 3.3
report = GAEBConverter.convert("old.D83", "modern.X83")

# Downgrade 3.3 → 3.2 for compatibility
report = GAEBConverter.convert(
    "tender.X83", "compat.X83",
    target_version=SourceVersion.DA_XML_32,
)
print(f"Converted {report.items_converted} items, data loss: {report.has_data_loss}")
```

See the [Version Conversion Guide](../guides/conversion.md) for full details.

## Custom & Vendor Tags

Access vendor-specific XML elements that pyGAEB doesn't map to a model field:

```python
doc = GAEBParser.parse("vendor_file.X83", keep_xml=True)

# XPath across the whole document
codes = doc.xpath("//g:VendorCostCode/text()")

# Per-item raw element access
for item in doc.iter_items():
    el = item.source_element  # original lxml element
```

See the [Custom & Vendor Tags Guide](../guides/custom-tags.md) for full details.

## Trade Phases (X93–X97)

Trade documents (material ordering between contractors and suppliers) are parsed with the same entry point:

```python
doc = GAEBParser.parse("order.X96")
print(doc.document_kind)    # DocumentKind.TRADE
print(doc.is_trade)         # True

# Trade-specific access
for item in doc.order.items:
    print(item.art_no, item.short_text, item.net_price)

print(doc.order.supplier_info.address.name)
```

LLM classification, structured extraction, and all other features work on trade documents without any code changes — just use `doc.iter_items()`.

See the [Trade Phases Guide](../guides/trade-phases.md) for full details.

## Next Steps

- [Parsing Guide](../guides/parsing.md) — version detection, encoding repair, error recovery
- [Trade Phases](../guides/trade-phases.md) — working with X93–X97 trade orders
- [Version Conversion](../guides/conversion.md) — convert between DA XML 2.0–3.3, upgrade, downgrade
- [Custom & Vendor Tags](../guides/custom-tags.md) — raw XML access, XPath queries, vendor extensions
- [Classification Guide](../guides/classification.md) — LLM setup, taxonomy, confidence flags
- [Extraction Guide](../guides/extraction.md) — custom Pydantic schemas for structured output
- [API Reference](../reference/index.md) — full class and function documentation
