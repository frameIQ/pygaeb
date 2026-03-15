# Cost & Calculation Phases

pyGAEB provides first-class support for GAEB Cost & Calculation phases:

- **X50** — Construction Cost Catalog (Baukostenkatalog)
- **X51** — Cost Determination (Kostenermittlung)
- **X52** — Calculation Approaches (Kalkulationsansätze)

X50 and X51 introduce a new document kind (`DocumentKind.COST`) with a recursive cost hierarchy. X52 extends the standard procurement structure with per-item calculation breakdowns.

## Quick Start

```python
from pygaeb import GAEBParser

# X50/X51 — Elemental Costing
doc = GAEBParser.parse("catalog.X50")
print(doc.document_kind)       # DocumentKind.COST
print(doc.is_cost)             # True

ec = doc.elemental_costing
print(ec.ec_info.name)         # "Project Alpha Cost Plan"
print(ec.ec_info.ec_method)    # "cost by elements"

# Flat iteration (LLM-ready)
for elem in doc.iter_items():
    print(elem.ele_no, elem.short_text, elem.qty, elem.unit_price)

# X52 — Calculation Approaches (still procurement)
doc = GAEBParser.parse("calc.X52")
print(doc.document_kind)       # DocumentKind.PROCUREMENT

for item in doc.award.boq.iter_items():
    print(item.oz, item.up_components)
    for ca in item.cost_approaches:
        print(f"  Cost: {ca.cost_type} = {ca.amount}")
```

## Document Kind: Cost

X50/X51 documents use `DocumentKind.COST`, distinct from procurement and trade:

```python
from pygaeb.models.enums import DocumentKind

doc = GAEBParser.parse("costs.X50")
assert doc.document_kind == DocumentKind.COST
assert doc.is_cost == True
assert doc.is_procurement == False
```

The `elemental_costing` field holds the parsed cost structure:

```python
ec = doc.elemental_costing         # ElementalCosting instance
ec.dp                              # "50.1" — data phase
ec.ec_info                         # ECInfo — metadata
ec.body                            # ECBody — cost hierarchy
```

## Elemental Costing Structure (X50/X51)

### ECInfo — Metadata

```python
info = ec.ec_info
info.name                          # Cost plan name
info.ec_type                       # "cost estimate", "cost determination"
info.ec_method                     # "cost by elements", "cost by area method"
info.currency                      # "EUR"
info.date_of_price                 # datetime — price basis date
info.breakdowns                    # list[ECBkdn] — hierarchy level definitions
info.consortium_members            # list[ConsortiumMember] — ARGE members
info.totals_net                    # Decimal — net total
info.totals_gross                  # Decimal — gross total
```

### ECBody and ECCtgy — Cost Hierarchy

The cost hierarchy uses recursive categories (`ECCtgy`) containing cost elements:

```python
for ctgy in ec.body.categories:
    print(ctgy.ele_no, ctgy.description)   # "300", "Building construction costs"
    print(ctgy.portion)                     # Decimal("0.70")

    if ctgy.body:
        for ce in ctgy.body.cost_elements:
            print(f"  {ce.ele_no}: {ce.short_text}")
```

### CostElement — The Cost Item

`CostElement` is the cost equivalent of `Item` (procurement) and `OrderItem` (trade). It carries the same interface for LLM compatibility:

```python
for ce in doc.iter_items():          # yields CostElement instances
    ce.ele_no                        # "310" — element number (DIN 276 code)
    ce.short_text                    # description
    ce.long_text_plain               # full text for LLM
    ce.qty                           # Decimal
    ce.unit                          # "m3"
    ce.unit_price                    # Decimal
    ce.item_total                    # Decimal
    ce.markup                        # Decimal multiplier
    ce.is_bill_element               # True for leaf items
    ce.properties                    # list[CostProperty] — BIM data
    ce.ref_groups                    # list[RefGroup] — cross-references
    ce.children                      # list[CostElement] — nested elements
```

Cost elements can be nested recursively:

```python
ce310 = ...  # a top-level cost element
for child in ce310.children:
    print(child.ele_no, child.item_total)
```

### Hierarchy Walking

Walk the full category tree:

```python
for depth, label, ctgy in ec.iter_hierarchy():
    print("  " * depth + label)
```

### BIM Integration — Properties

Cost elements can contain BIM-linked properties:

```python
for ce in doc.iter_items():
    for prop in ce.properties:
        if prop.cad_id:
            print(f"BIM: {prop.cad_id} -> {ce.ele_no}")
        if prop.arithmetic_qty_approach:
            print(f"Formula: {prop.arithmetic_qty_approach}")
        print(f"  Value: {prop.value_qty_approach} {prop.unit}")
```

### Cross-References — RefGroup

Cost elements can reference BoQ items, other cost elements, dimension elements, etc.:

```python
for ce in doc.iter_items():
    for rg in ce.ref_groups:
        print(f"Ref group: {rg.title}")
        for ref in rg.boq_item_refs:
            print(f"  -> BoQ Item {ref.id_ref} (portion: {ref.portion})")
```

### DimensionElement and CategoryElement

The cost body can also contain dimensional and categorical elements:

```python
for de in ec.body.dimension_elements:
    print(de.ele_no, de.description, de.qty, de.unit)

for cat in ec.body.category_elements:
    print(cat.ele_no, cat.description, cat.markup)
```

## X52 — Calculation Approaches

X52 uses the standard procurement structure (`DocumentKind.PROCUREMENT`) but adds per-item cost calculation data.

### CostApproach

Each item can have multiple cost approach entries:

```python
doc = GAEBParser.parse("calc.X52")

for item in doc.award.boq.iter_items():
    for ca in item.cost_approaches:
        print(ca.cost_type, ca.amount, ca.remark)
```

### UP Components

Unit price breakdown into up to 6 components:

```python
for item in doc.award.boq.iter_items():
    if item.up_components:
        print(f"Components: {item.up_components}")
        # e.g., [Decimal("45.00"), Decimal("30.00"), ...]
```

### Discount

```python
for item in doc.award.boq.iter_items():
    if item.discount_pct is not None:
        print(f"Discount: {item.discount_pct}%")
```

### CostType on BoQInfo

X52 documents can define cost type classifications at the BoQ level:

```python
info = doc.award.boq.boq_info
for ct in info.cost_types:
    print(ct.name, ct.label)   # "Material", "Mat."
```

## Universal Iteration

`doc.iter_items()` works across all document kinds:

```python
for item in doc.iter_items():
    # Item (procurement), OrderItem (trade), or CostElement (cost)
    print(item.short_text, item.qty, item.unit)
```

LLM classification and structured extraction also work universally — no code changes needed for cost documents.

## Writing Cost Documents

```python
from pygaeb import GAEBWriter, ExchangePhase

# Write X50/X51
GAEBWriter.write(doc, "output.X50", phase=ExchangePhase.X50)

# Write X52 (same as any procurement)
GAEBWriter.write(doc, "output.X52", phase=ExchangePhase.X52)
```

Round-trip editing preserves all cost-specific fields.

## DocumentAPI

The `DocumentAPI` wrapper supports cost documents:

```python
from pygaeb.api.document_api import DocumentAPI

api = DocumentAPI(doc)
api.is_cost                        # True
api.elemental_costing              # ElementalCosting | None
api.get_cost_element("310")        # CostElement | None
api.iter_hierarchy()               # walks cost categories

summary = api.summary()
summary["ec_type"]                 # "cost estimate"
summary["ec_method"]               # "cost by elements"
summary["has_bim_references"]      # True/False
```
