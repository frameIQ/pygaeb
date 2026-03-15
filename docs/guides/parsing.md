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

GAEB defines workflows through exchange phases. **Procurement phases** cover the tendering process, **trade phases** cover material ordering between contractors and suppliers, and **cost phases** cover construction cost estimation and calculation.

### Procurement Phases (X80–X89)

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

### Trade Phases (X93–X97)

| Phase | Purpose | Typical Extension |
|-------|---------|-------------------|
| X93 | Trade Price Inquiry | `.X93` |
| X94 | Trade Price Offer | `.X94` |
| X96 | Trade Order | `.X96` |
| X97 | Trade Order Confirmation | `.X97` |

Trade phases use a different XML structure (`<Order>/<OrderItem>` instead of `<Award>/<BoQ>/<Item>`), but pyGAEB handles this transparently. See the [Trade Phases Guide](trade-phases.md) for details.

### Cost & Calculation Phases (X50–X52)

| Phase | Purpose | Typical Extension |
|-------|---------|-------------------|
| X50 | Construction Cost Catalog | `.X50` |
| X51 | Cost Determination | `.X51` |
| X52 | Calculation Approaches | `.X52` |

X50 and X51 use a different XML structure (`<ElementalCosting>/<ECBody>/<CostElement>` instead of `<Award>/<BoQ>/<Item>`), introducing `DocumentKind.COST`. X52 extends the standard procurement structure with per-item calculation data. See the [Cost & Calculation Phases Guide](cost-phases.md) for details.

### Quantity Determination Phase (X31)

| Phase | Purpose | Typical Extension |
|-------|---------|-------------------|
| X31 | Quantity Take-Off / Measurements | `.X31` |

X31 uses a different XML structure (`<QtyDeterm>/<BoQ>/<QtyItem>` with REB 23.003 measurement rows instead of procurement items), introducing `DocumentKind.QUANTITY`. Items carry no descriptions or prices — only OZ numbers and measurement data. See the [Quantity Determination Guide](quantity-phases.md) for details.

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
for item in doc.iter_items():
    el = item.source_element  # lxml _Element or None
```

See the [Custom & Vendor Tags Guide](custom-tags.md) for full details.

## Unified Document Model

Regardless of input version, you always get the same `GAEBDocument`. The document discriminates between **procurement**, **trade**, **cost**, and **quantity** workflows:

```python
doc.source_version       # SourceVersion enum
doc.exchange_phase       # ExchangePhase enum
doc.document_kind        # DocumentKind.PROCUREMENT, TRADE, COST, or QUANTITY
doc.gaeb_info            # GAEBInfo (software metadata)
doc.validation_results   # list[ValidationResult]
doc.grand_total          # Decimal (sum of affecting items)
doc.item_count           # int
```

### Procurement documents (X80–X89)

```python
doc.award                # AwardInfo (project info + BoQ)
doc.award.boq            # BoQ (lots > categories > items)
```

**Project metadata** from `<PrjInfo>` is merged into `AwardInfo`:

```python
doc.award.project_name   # str — project name
doc.award.prj_id         # str — project GUID
doc.award.lbl_prj        # str — project label
doc.award.description    # str — project description
doc.award.currency_label # str — e.g., "Euro"
doc.award.up_frac_dig    # int (2 or 3) — unit price decimal places
doc.award.bid_comm_perm  # bool — bidder comments permitted
doc.award.alter_bid_perm # bool — alternative bids permitted
```

**Financial summaries** are parsed from `<Totals>` elements on BoQInfo, categories, and lots. These carry the authoritative net/gross totals, VAT rates, VAT breakdowns, and discount data — present in X84 (bid), X86 (award), and X89 (invoice) files:

```python
totals = doc.award.boq.boq_info.totals
if totals:
    totals.total           # Decimal — sum before discounts
    totals.total_net       # Decimal — net after discounts
    totals.total_gross     # Decimal — gross (net + VAT)
    totals.vat             # Decimal — VAT rate %
    totals.vat_amount      # Decimal — total VAT amount
    totals.discount_pcnt   # Decimal — discount percentage
    totals.vat_parts       # list[VATPart] — per-rate breakdown
```

**Item-level VAT** — each item can carry its own VAT rate:

```python
for item in doc.award.boq.iter_items():
    if item.vat is not None:
        print(f"{item.oz}: {item.vat}%")
```

### Trade documents (X93–X97)

```python
doc.order                # TradeOrder (supplier/customer info + flat item list)
doc.order.items          # list[OrderItem]
```

### Cost documents (X50, X51)

```python
doc.elemental_costing    # ElementalCosting (cost hierarchy + BIM properties)
doc.elemental_costing.body.iter_cost_elements()  # recursive element iteration
```

### Quantity determination documents (X31)

```python
doc.qty_determination    # QtyDetermination (measurement data + catalogs)
doc.qty_determination.boq.ref_boq_name  # referenced procurement BoQ
```

### Universal iteration

Works for all document kinds:

```python
for item in doc.iter_items():
    print(item.short_text, item.qty, item.unit)
```

See the [Models Reference](../reference/models.md) for full details on every field.

## Advanced Parsing Options

### Post-parse hook

Use `post_parse_hook` to inspect or mutate each item right after parsing:

```python
def extract_vendor_codes(item, el):
    if el is None:
        return
    ns = {"g": "http://www.gaeb.de/GAEB_DA_XML/DA86/3.3"}
    codes = el.findall(".//g:VendorCostCode", ns)
    if codes:
        item.raw_data = item.raw_data or {}
        item.raw_data["vendor_codes"] = [c.text for c in codes]

doc = GAEBParser.parse("file.X83", post_parse_hook=extract_vendor_codes)
```

### Collecting unknown XML elements

Set `collect_raw_data=True` to automatically populate `item.raw_data` with child elements not consumed by the built-in parser:

```python
doc = GAEBParser.parse("file.X83", collect_raw_data=True)
for item in doc.iter_items():
    if item.raw_data:
        print(f"{item.oz}: {item.raw_data}")
```

See the [Extensibility Guide](extensibility.md) for more extension points.
