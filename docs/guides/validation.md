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

Verifies arithmetic consistency:

- `qty x unit_price` matches `total_price` (within 0.01 tolerance)
- Rounding discrepancies are flagged as warnings

```python
for item in doc.award.boq.iter_items():
    if item.has_rounding_discrepancy:
        print(f"Item {item.oz}: {item.total_price} != {item.computed_total}")
```

### Item Validation

Checks individual item rules:

- Supplement items (`ItemType.SUPPLEMENT`) should have a change order number
- Quantity split totals should match the item quantity
- Normal items should have a quantity defined

### Phase-Specific Validation

Rules that depend on the exchange phase:

- Tender phases (X83) should have quantities
- Bid phases (X84) should have unit prices
- Invoice phases (X86) should have complete pricing

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

Compare a tender document against a bid to check for compliance:

```python
from pygaeb import GAEBParser, CrossPhaseValidator

tender = GAEBParser.parse("tender.X83")
bid = GAEBParser.parse("bid.X84")

issues = CrossPhaseValidator.check(source=tender, response=bid)
for issue in issues:
    print(f"[{issue.severity.value}] {issue.message}")
```

Cross-phase validation detects:

- **Missing items** — items in the tender that are absent from the bid
- **New items** — items in the bid that were not in the tender
- **Quantity changes** — modified quantities between phases
- **Item type changes** — e.g., Normal changed to Alternative

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
