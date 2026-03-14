# Parsing

pyGAEB auto-detects the version, format, and encoding of any GAEB file, producing a unified `GAEBDocument` regardless of the input version.

## Basic Parsing

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("tender.X83")
```

This single call handles:

1. **Format detection** — determines if the file is DA XML (2.x or 3.x) or GAEB 90
2. **Version detection** — reads the XML namespace and `<Version>` element
3. **Encoding repair** — fixes BOM, Windows-1252 masquerading as UTF-8, mojibake
4. **XML recovery** — handles bare ampersands, unclosed tags, and other real-world damage
5. **Structural parsing** — builds the full BoQ hierarchy
6. **Validation** — runs numeric, item, and phase validation

## Parse from Memory

For web uploads, S3 objects, or database blobs:

```python
doc = GAEBParser.parse_bytes(raw_bytes, filename="tender.X83")
doc = GAEBParser.parse_string(xml_text, filename="input.X84")
```

The `filename` parameter provides the extension hint used for phase detection (`.X83` = tender, `.X84` = bid, etc.).

## Version Detection

pyGAEB detects the version from multiple signals in priority order:

1. **XML namespace** — most reliable (e.g., `http://www.gaeb.de/GAEB_DA_XML/DA86/3.3`)
2. **`<Version>` element** — explicit version tag in `<GAEBInfo>`
3. **File extension** — fallback for phase detection (`.X83`, `.D83`, etc.)

```python
doc = GAEBParser.parse("tender.X83")
print(doc.source_version)    # SourceVersion.DA_XML_33
print(doc.exchange_phase)    # ExchangePhase.X83
```

### Parser Tracks

| Track | Versions | Element Language |
|-------|----------|-----------------|
| Track A | DA XML 2.0, 2.1 | German (`Leistungsverzeichnis`, `Position`, `Menge`...) |
| Track B | DA XML 3.0–3.3 | English (`BoQ`, `Item`, `Qty`...) |
| Track C | GAEB 90 | Fixed-width records (planned v1.1) |

All tracks produce the same `GAEBDocument` model.

## Encoding Repair

Real-world GAEB files frequently have encoding issues. pyGAEB handles them transparently:

- **BOM stripping** — removes UTF-8/UTF-16 byte order marks
- **Charset detection** — uses `charset-normalizer` to detect Windows-1252, Latin-1, etc.
- **Mojibake repair** — uses `ftfy` to fix double-encoded characters (common with German umlauts)

The encoding repair runs before XML parsing, so even files with corrupted encoding declarations are handled.

## XML Recovery

If standard `lxml` parsing fails, pyGAEB falls back to a recovery pipeline:

1. **BeautifulSoup** tolerant parser — handles bare `&`, unclosed tags, and malformed attributes
2. Warnings are added to `doc.validation_results` — nothing is silently lost

```python
doc = GAEBParser.parse("damaged.X83")
for issue in doc.validation_results:
    if "recovery" in issue.message.lower():
        print(f"Recovered: {issue.message}")
```

## Exchange Phases

GAEB defines a procurement workflow through exchange phases:

| Phase | Purpose | Typical Extension |
|-------|---------|-------------------|
| X80 | Request for proposal | `.X80` |
| X81 | Cost estimate | `.X81` |
| X82 | Specification | `.X82` |
| X83 | Tender / Bill of quantities | `.X83` |
| X84 | Bid / Offer | `.X84` |
| X85 | Award | `.X85` |
| X86 | Invoice | `.X86` |
| X89 | Cost planning | `.X89` |

DA XML 2.x uses `D`-prefixed phases (D83, D84, etc.) which are automatically normalized to `X`-prefixed canonical form:

```python
doc = GAEBParser.parse("old.D83")
print(doc.exchange_phase)              # ExchangePhase.D83
print(doc.exchange_phase.normalized()) # ExchangePhase.X83
```

## Retaining Raw XML

By default the lxml tree is discarded after parsing to conserve memory. Pass `keep_xml=True` to retain it, which enables **custom tag access** and **XPath queries**:

```python
doc = GAEBParser.parse("tender.X83", keep_xml=True)

# XPath against the full tree (namespace prefix "g:" is auto-mapped)
codes = doc.xpath("//g:VendorCostCode/text()")

# Access the raw lxml element on any item
for item in doc.award.boq.iter_items():
    el = item.source_element  # lxml _Element or None
```

See the [Custom & Vendor Tags Guide](custom-tags.md) for full details.

## Unified Document Model

Regardless of input version, you always get the same structure:

```python
doc.source_version       # SourceVersion enum
doc.exchange_phase       # ExchangePhase enum
doc.gaeb_info            # GAEBInfo (software metadata)
doc.award                # AwardInfo (project info + BoQ)
doc.award.boq            # BoQ (lots > categories > items)
doc.validation_results   # list[ValidationResult]
doc.grand_total          # Decimal (sum of affecting items)
doc.item_count           # int
```

See the [Models Reference](../reference/models.md) for full details on every field.
