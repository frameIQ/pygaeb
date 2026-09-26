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

### Answering the Bidder's Fields

A bid carries, per position, the bidder's fields (`TextComplement Kind="Bidder"`)
and nothing else of the long text. Answer them before writing:

```python
from pygaeb import GAEBParser, GAEBWriter, PhaseTransition
from pygaeb.models.enums import ExchangePhase

bid = PhaseTransition.tender_to_bid(GAEBParser.parse("tender.X83"))
for item in bid.iter_items():
    if item.long_text:
        item.long_text.fill_bidder("32", "Beton C30/37")

GAEBWriter.write(bid, "bid.X84", phase=ExchangePhase.X84)
```

An answered field is written as `<ComplBody><span>…</span></ComplBody>` — one
span per line, `<br/>` between — with its number as `ComplBodyDec`/`ComplBodyInt`
`Value` when the field takes one and the answer is one. A field left open is
written with `Empty="Yes"`. The issuer's fields are not repeated: a bid answers
the tender, it does not restate it. `fill_bidder` returns how many fields took the
answer — `0` for an unknown mark or an issuer's field — and `TextComplement.fill`
raises on an issuer's field.

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

- Phase-specific GAEB DA XML 3.3 namespace (`DA83/3.3`, `DA84/3.3`, …)
- All BoQ structure (lots, categories, items) with the `xs:ID` attributes the schema requires
- Item attributes (quantities, prices, units, text) in schema order
- GAEBInfo metadata (`ProgSystem` names pyGAEB; see below)

### Schema conformance

Since 1.17.0 the 3.x procurement writer emits what the official GAEB DA XML 3.3
(2021-05) schemas accept, and this is verified against the BVBS certification
test files for X81, X82, X83, X84 and X86. Each exchange phase is a restriction
of the shared schema, so the writer applies a per-phase profile
(`pygaeb.writer.phase_profiles`):

| Phase | Not written (no place in the schema) | Required and synthesised when missing |
|-------|--------------------------------------|---------------------------------------|
| X81/X82 | — | `BoQInfo/Name`, `LblBoQ`, `OutlCompl`, `LblTx` |
| X83 (tender) | unit prices, item totals, `Totals`, contractor | `QU` on every item |
| X84 (bid) | category labels, catalog assignments, position-type markers, outline text, owner, the tender's prose and the issuer's own fields | `CTR` (empty-address placeholder), `Totals` per category |
| X86 (contract) | — | `OWN`, `CTR`, `Totals` per category |

Everything left out is reported once per element kind in the returned warnings
as `… not written … not part of X84 in DA XML 3.x`. The word `dropped` is
reserved for real data loss (a field the target *version* does not support),
which is what `ConversionReport.has_data_loss` looks for.

Two pyGAEB-only serialisations remain by design: `<BidderUP>` (Preisspiegel
prices, written with a warning) and the legacy synthetic markers for
`ItemType.ALTERNATIVE` and friends.

`ProgSystem` must name the generating software for BVBS certification, so it is
stamped with `pyGAEB <version>`. Name your own application instead:

```python
GAEBWriter.write(doc, "out.X84", phase=ExchangePhase.X84,
                 prog_system="MyAVA 4.2", prog_name="MyAVA")
```

To check output against the schemas you hold locally (they are not bundled):

```python
result = GAEBWriter.validate_against_xsd(doc, phase=ExchangePhase.X84,
                                         xsd_dir="/opt/gaeb/2021-05")
if result is not None and not result.valid:
    for err in result.errors:
        print(err.line, err.message)
```

`GAEBWriter.validate_against_xsd` returns `None` when no schema is available.
See [Validation](validation.md#xsd-validation) for the schema folder layout.

**Trade documents:**

- Trade-specific namespace (e.g., `DA96/3.3`)
- Order structure (supplier/customer info, flat item list)
- Trade-specific fields (EAN, article number, delivery details)

**Cost documents (X50/X51):**

- Cost-specific namespace (e.g., `DA50/3.3`)
- ElementalCosting structure (categories, cost elements, properties)
- BIM-integrated properties (CAD_ID, arithmetic approaches)
- Cross-reference groups (RefGroup)
- Dimension and category elements

**Quantity determination documents (X31):**

- Quantity-specific namespace (e.g., `DA31/3.3`)
- QtyDetermination structure (QtyBoQ, QtyItem, QDetermItem)
- REB 23.003 QTakeoff measurement rows
- Catalog definitions and assignments
- Base64-encoded BoQ-level attachments

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
