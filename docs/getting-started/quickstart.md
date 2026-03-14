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

Look up a specific item by its OZ (ordinal number):

```python
item = doc.award.boq.get_item("01.02.0030")
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

for item in doc.award.boq.iter_items():
    if item.classification:
        print(item.oz, item.classification.element_type, item.classification.confidence)
```

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
for item in doc.award.boq.iter_items():
    el = item.source_element  # original lxml element
```

See the [Custom & Vendor Tags Guide](../guides/custom-tags.md) for full details.

## Next Steps

- [Parsing Guide](../guides/parsing.md) — version detection, encoding repair, error recovery
- [Version Conversion](../guides/conversion.md) — convert between DA XML 2.0–3.3, upgrade, downgrade
- [Custom & Vendor Tags](../guides/custom-tags.md) — raw XML access, XPath queries, vendor extensions
- [Classification Guide](../guides/classification.md) — LLM setup, taxonomy, confidence flags
- [Extraction Guide](../guides/extraction.md) — custom Pydantic schemas for structured output
- [API Reference](../reference/index.md) — full class and function documentation
