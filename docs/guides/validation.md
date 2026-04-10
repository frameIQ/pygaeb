# Validation

pyGAEB runs multiple validation layers automatically during parsing. You can also perform cross-phase validation between two documents.

## Validation Modes

### Lenient (Default)

Collects all issues as `ValidationResult` objects without raising exceptions:

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("tender.X83")

for issue in doc.validation_results:
    print(f"[{issue.severity.value}] {issue.message}")
```

### Strict

Raises `GAEBValidationError` on the first ERROR-severity result:

```python
from pygaeb import GAEBParser, ValidationMode
from pygaeb.exceptions import GAEBValidationError

try:
    doc = GAEBParser.parse("tender.X83", validation=ValidationMode.STRICT)
except GAEBValidationError as e:
    print(f"Validation failed: {e}")
```

## Validation Layers

### Structural Validation

Checks the overall document structure:

- Required elements present (BoQ, BoQBody, at least one lot)
- BoQ breakdown definition consistency
- Category/item nesting validity

### Numeric Validation

Verifies arithmetic consistency and GAEB precision limits:

- `qty x unit_price` matches `total_price` (within 0.01 tolerance)
- Rounding discrepancies are flagged as warnings
- **GAEB precision limits** (added in v1.12.0):
  - Unit price: max 10 pre-decimal digits
  - Total price: max 11 pre-decimal digits
  - Quantity: max 8 pre-decimal digits, max 3 decimal places
  - Unit price components: max 6 per item

```python
for item in doc.award.boq.iter_items():
    if item.has_rounding_discrepancy:
        print(f"Item {item.oz}: {item.total_price} != {item.computed_total}")
```

### Totals Validation

*Added in v1.12.0.*

Checks that XML-declared totals match the computed subtotals from items:

- **BoQ-level totals** — declared total vs sum of lot subtotals
- **Lot-level totals** — declared total vs sum of item totals
- **Category-level totals** — declared total vs sum of contained items
- **Alternative item exclusion** — warns if declared totals appear to include alternative/eventual items (VOB/A compliance)

```python
# Totals validation runs automatically during parsing.
# Check results:
totals_issues = [
    r for r in doc.validation_results
    if "total mismatch" in r.message or "alternative" in r.message.lower()
]
```

### Item Validation

Checks individual item rules:

- Supplement items (`ItemType.SUPPLEMENT`) should have a change order number
- Quantity split totals should match the item quantity
- Normal items should have a quantity defined

### Phase-Specific Validation

Rules that depend on the exchange phase:

- Tender phases (X83) should have quantities and descriptions
- Bid phases (X84) should have unit prices
- Award/Invoice phases (X86, X89) should have complete pricing
- Addendum phases (X88) should have quantities, prices, descriptions, and change order numbers (CONo)
- X80 (BoQ Catalogue) does **not** require quantities or prices

## Severity Levels

| Severity | Meaning |
|----------|---------|
| `ERROR` | Structural or data integrity problem — document may be incomplete |
| `WARNING` | Potential issue — document is usable but review recommended |
| `INFO` | Informational message (e.g., "XSD validation skipped") |

## Filtering Results

```python
from pygaeb.models.enums import ValidationSeverity

errors = [r for r in doc.validation_results if r.severity == ValidationSeverity.ERROR]
warnings = [r for r in doc.validation_results if r.severity == ValidationSeverity.WARNING]
```

## Cross-Phase Validation

Compare two documents across exchange phases. `CrossPhaseValidator.check()` auto-dispatches to the correct validation logic based on the detected phase pair.

### X83 → X84 (Tender → Bid)

```python
from pygaeb import GAEBParser, CrossPhaseValidator

tender = GAEBParser.parse("tender.X83")
bid = GAEBParser.parse("bid.X84")

issues = CrossPhaseValidator.check(source=tender, response=bid)
for issue in issues:
    print(f"[{issue.severity.value}] {issue.message}")
```

Detects:

- **Missing items** — items in the tender that are absent from the bid
- **New items** — items in the bid that were not in the tender
- **Quantity changes** — modified quantities between phases
- **Missing prices** — priced items without unit price in the bid

### X86 → X89 (Contract → Invoice)

*Added in v1.12.0.*

```python
contract = GAEBParser.parse("contract.X86")
invoice = GAEBParser.parse("invoice.X89")

issues = CrossPhaseValidator.check(source=contract, response=invoice)
```

Detects:

- **Unit price mismatches** — invoice prices that don't match the contract (ERROR severity)
- **Invented items** — invoice items not found in the contract
- **Missing executed quantities** — invoice items without quantity

### X86 → X88 (Contract → Addendum/Nachtrag)

*Added in v1.12.0.*

```python
contract = GAEBParser.parse("contract.X86")
addendum = GAEBParser.parse("nachtrag.X88")

issues = CrossPhaseValidator.check(source=contract, response=addendum)
```

Detects:

- **New items without CONo** — Nachtrag items lacking a change order number for traceability
- **Modified items without CONo** — existing contract items with changed price or quantity but no change order reference

### Explicit Method Calls

For direct invocation without auto-dispatch:

```python
issues = CrossPhaseValidator.check_tender_bid(tender, bid)
issues = CrossPhaseValidator.check_contract_invoice(contract, invoice)
issues = CrossPhaseValidator.check_contract_addendum(contract, addendum)
```

## XSD Validation

If you have the official GAEB XSD schemas, pyGAEB can validate against them:

```python
doc = GAEBParser.parse("tender.X83", xsd_dir="/opt/gaeb-schemas")
```

Or configure it globally:

```python
from pygaeb import configure
configure(xsd_dir="/opt/gaeb-schemas")
```

!!! note
    XSD schemas are not distributed with pyGAEB due to licensing. They can be obtained from the [GAEB organization](https://www.gaeb.de).
