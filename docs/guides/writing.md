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

Export one row per item:

```python
from pygaeb import to_csv

to_csv(doc, "items.csv")
```

Each document kind gets its own columns:

| Document | Columns |
|---|---|
| Tender, bid, award and other BoQ documents | `oz`, `full_oz`, `short_text`, `qty`, `unit`, `unit_price`, `total_price`, `computed_total`, `item_type`, `lot_label`, `hierarchy_path`, `has_attachments`, `bim_guid`, the classification columns, `affects_total`, `provis`, `markup_base` |
| Trade orders (X93–X97) | `item_id`, `art_no`, `supplier_art_no`, `ean`, `short_text`, `qty`, `unit`, `offer_price`, `net_price`, `price_basis`, `line_total`, `is_service`, `delivery_date`, the classification columns |
| Cost estimates (X50, X51) | `ele_no`, `parent_ele_no`, `hierarchy_path`, `short_text`, `qty`, `unit`, `unit_price`, `item_total`, `markup`, `up_from`, `up_avg`, `up_to`, `is_bill_element`, `remark`, the classification columns |
| Quantity determinations (X31) | `oz`, `qty`, `takeoff_rows` (the number of measurement rows) |

The classification columns are `trade`, `element_type`, `sub_type`, `classification_confidence` and `classification_flag`. They are filled after running `LLMClassifier.enrich()`.

Text that a spreadsheet would run as a formula, because it starts with `=`, `+`, `-`, `@`, a tab or a carriage return, gets a leading `'`, so a short text like `=HYPERLINK(...)` from a GAEB file shows as text when the CSV is opened in Excel. Numbers are never changed. Pass `escape_formulas=False` to write the text exactly as the document has it, for instance when no spreadsheet will read the file.

Amounts are written exactly, as their decimal text; an empty cell means the value is absent. To rebuild a BoQ's sums, add up `total_price` over the rows whose `affects_total` is `True`: that leaves out alternatives, optional items without total and the other positions that do not count. In a cost estimate, `parent_ele_no` names the cost element a row sits under and `hierarchy_path` its categories.

!!! tip
    CSV export is useful for spreadsheet analysis, pivot tables, and feeding data into BI tools.

## Export to a pandas DataFrame

`to_dataframe` gives the same table as the CSV, one row per item with the columns of the document's kind, as a pandas DataFrame:

```python
from pygaeb import to_dataframe

df = to_dataframe(doc)
counted = df[df["affects_total"]]
counted["total_price"].sum()                            # the BoQ's sum
counted.groupby("hierarchy_path")["total_price"].sum()  # per category
```

Amounts are floats, so sums, `describe()` and plots work as usual; a sum can show a binary remainder such as `1755.0000000000002` until it is rounded. Pass `exact=True` to keep pyGAEB's `Decimal` values when results must be right to the cent:

```python
df = to_dataframe(doc, exact=True)
df.loc[df["affects_total"], "total_price"].sum()        # Decimal('1755.00')
```

Amount columns stay numeric and date columns stay dates even when no item has a value. pandas is optional: `pip install pyGAEB[pandas]`.
