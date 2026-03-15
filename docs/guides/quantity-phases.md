# Quantity Determination Phases (X31)

GAEB X31 exchanges **quantity take-off data** (Mengenermittlung) — the actual measurements used to determine quantities for construction items. Unlike procurement phases, X31 documents do not contain item descriptions or prices; they reference an external BoQ and supplement it with measurement rows following the REB 23.003 standard.

## Quick Start

```python
from pygaeb import GAEBParser
from pygaeb.api.document_api import DocumentAPI

doc = GAEBParser.parse("measurements.X31")
api = DocumentAPI(doc)

assert api.is_quantity
qd = api.qty_determination

# Metadata
print(qd.info.method)        # "REB23003-2009"
print(qd.boq.ref_boq_name)   # reference to procurement BoQ

# Iterate items
for item in api.iter_items():
    print(f"OZ: {item.oz}, Qty: {item.qty}")
    for dm in item.determ_items:
        print(f"  Row: {dm.takeoff_row.raw}")
```

## Document Structure

X31 introduces `DocumentKind.QUANTITY` with its own root model:

```
GAEBDocument
├── gaeb_info: GAEBInfo
└── qty_determination: QtyDetermination
    ├── prj_info: PrjInfoQD (reference to project)
    ├── info: QtyDetermInfo (REB method, dates, creator/profiler)
    ├── owner: Address
    ├── contractor: Address
    └── boq: QtyBoQ
        ├── ref_boq_name / ref_boq_id (external BoQ reference)
        ├── bkdn: list[BoQBkdn]
        ├── catalogs: list[Catalog]
        ├── body: QtyBoQBody → QtyBoQCtgy → QtyItem
        ├── ctlg_assigns: list[CtlgAssign]
        └── attachments: list[QtyAttachment]
```

## Quantity Items

`QtyItem` is a thin BoQ position — it only carries an OZ number and measurement data, enabling cross-referencing with procurement items:

```python
for item in doc.iter_items():
    print(f"OZ: {item.oz}")
    print(f"  Determined qty: {item.qty}")
    print(f"  Measurement rows: {len(item.determ_items)}")
```

Each item may contain multiple `QDetermItem` entries, each with a `QTakeoffRow` — a measurement line following the REB 23.003 format:

```python
for dm in item.determ_items:
    print(dm.takeoff_row.raw)  # Fixed-width REB 23.003 row
```

## Cross-Referencing with Procurement

The primary use case for X31 is to supplement a procurement BoQ with verified measurements. Use `QtyItem.oz` to match items:

```python
proc_doc = GAEBParser.parse("tender.X83")
qty_doc = GAEBParser.parse("measurements.X31")

proc_api = DocumentAPI(proc_doc)
qty_api = DocumentAPI(qty_doc)

for qty_item in qty_api.iter_items():
    proc_item = proc_api.get_item(qty_item.oz)
    if proc_item:
        print(f"{proc_item.short_text}: measured = {qty_item.qty}")
```

The `ref_boq_name` and `ref_boq_id` fields on `QtyBoQ` identify which procurement BoQ the measurements belong to:

```python
qd = qty_api.qty_determination
print(qd.boq.ref_boq_name)  # "Tender BoQ 2024"
print(qd.boq.ref_boq_id)    # GUID reference
```

## Catalogs

X31 uses a catalog system for classification (DIN 276 cost groups, BIM references, locality, etc.):

```python
# Catalog definitions
for cat in qd.boq.catalogs:
    print(f"{cat.ctlg_name} ({cat.ctlg_type})")

# Catalog assignments on items
for item in api.iter_items():
    for ca in item.ctlg_assigns:
        print(f"  {ca.ctlg_id}: {ca.ctlg_code}")
```

Catalog assignments appear at multiple levels: BoQ, category, item, and even on individual measurement rows.

## Attachments

X31 supports base64-encoded attachments (photos, sketches, PDFs) at the BoQ level. These are referenced from QTakeoff rows using `#Bild <name>` syntax:

```python
for att in qd.boq.attachments:
    print(f"{att.name}: {att.mime_type}, {att.size_bytes} bytes")
    # att.data contains the decoded binary content
```

## Quantity Determination Info

`QtyDetermInfo` provides metadata about the measurement process:

```python
info = qd.info
print(info.method)         # "REB23003-1979" or "REB23003-2009"
print(info.order_descr)    # Contract description
print(info.project_descr)  # Project description
print(info.service_start)  # datetime
print(info.service_end)    # datetime

# Creator and profiler addresses
if info.creator:
    print(f"Creator: {info.creator.name}, {info.creator.city}")
if info.profiler:
    print(f"Profiler: {info.profiler.name}")
```

## Writing X31 Documents

Round-trip editing works the same as other document kinds:

```python
from pygaeb import GAEBWriter, ExchangePhase

doc = GAEBParser.parse("measurements.X31")
# ... modify quantities ...
GAEBWriter.write(doc, "updated.X31", phase=ExchangePhase.X31)
```

## Document API

The `DocumentAPI` provides quantity-specific accessors:

```python
api = DocumentAPI(doc)

api.is_quantity          # True
api.qty_determination    # QtyDetermination root model
api.get_qty_item("01.0010")  # Find by OZ

# Universal iteration works
for item in api.iter_items():
    print(item.oz, item.qty)

# Summary includes QD-specific fields
s = api.summary()
print(s["method"])        # REB method
print(s["ref_boq_name"])  # Referenced BoQ
print(s["catalogs"])      # Number of catalogs
print(s["attachments"])   # Number of attachments
```

## Note on LLM Classification

X31 items have no text content (no `short_text`/`long_text`), so LLM classification and structured extraction are not applicable to `QtyItem`. The classifier and extractor will naturally skip them. Use the procurement document for classification and cross-reference via OZ.
