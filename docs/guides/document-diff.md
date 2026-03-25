# Document Diff

Compare two GAEB procurement documents to identify item-level, structural, and metadata changes with significance-classified results.

## Quick Start

```python
from pygaeb import GAEBParser, BoQDiff

doc_a = GAEBParser.parse("tender_v1.X83")
doc_b = GAEBParser.parse("tender_v2.X83")

result = BoQDiff.compare(doc_a, doc_b)

print(result.summary.total_changes)     # 12
print(result.summary.financial_impact)  # Decimal("45230.00")
print(result.summary.max_significance)  # Significance.CRITICAL
```

## How Matching Works

Items are matched by **OZ (ordinal number) within each lot**. This is the standard identity key in GAEB files.

1. For each lot in both documents, items are indexed by `(lot_rno, oz)`.
2. Items sharing the same key are considered the same position.
3. Unmatched items fall back to a **global OZ match** — this catches items that moved between lots.
4. Items still unmatched after both passes are reported as added or removed.

The `match_ratio` (0.0–1.0) in the summary tells you how many items were successfully paired.

## Significance Levels

Every field change is classified by its impact in a construction context:

| Level | Fields | Meaning |
|---|---|---|
| **CRITICAL** | `unit_price`, `total_price`, `qty` | Directly affects contract value |
| **HIGH** | `unit`, `item_type`, `discount_pct` | Changes the nature of the position |
| **MEDIUM** | `short_text`, `vat`, `markup_type` | Descriptive or tax-related |
| **LOW** | `bim_guid`, `change_order_number` | Reference/metadata only |

## Item-Level Changes

```python
# Items added in doc_b
for item in result.items.added:
    print(f"+ {item.oz}: {item.short_text} ({item.total_price})")

# Items removed from doc_a
for item in result.items.removed:
    print(f"- {item.oz}: {item.short_text} ({item.total_price})")

# Items modified (present in both, with field changes)
for mod in result.items.modified:
    print(f"~ {mod.oz}: {mod.max_significance.value}")
    for change in mod.changes:
        print(f"    {change.field}: {change.old_value} → {change.new_value}")
        if change.is_numeric:
            print(f"    delta: {change.absolute_delta} ({change.percent_delta:.1f}%)")
```

## Filtering by Significance

Focus on what matters most:

```python
from pygaeb import Significance

# Only items with at least one CRITICAL change
critical = result.items.filter_modified(Significance.CRITICAL)

# Per-item filtering
for mod in result.items.modified:
    high_plus = mod.filter_changes(Significance.HIGH)
    if high_plus:
        print(f"{mod.oz}: {len(high_plus)} important changes")
```

## Structural Changes

Detects changes to the category/section hierarchy:

```python
# New sections
for sec in result.structure.sections_added:
    print(f"New: {sec.label} ({sec.item_count} items)")

# Removed sections
for sec in result.structure.sections_removed:
    print(f"Removed: {sec.label} ({sec.item_count} items)")

# Renamed sections
for sec in result.structure.sections_renamed:
    print(f"Renamed: {sec.old_label} → {sec.new_label}")

# Items that moved to a different category
for moved in result.structure.items_moved:
    print(f"Moved: {moved.oz} from {moved.old_category_rno} to {moved.new_category_rno}")
```

## Metadata Changes

Document-level changes (currency, project info, exchange phase):

```python
for meta in result.metadata:
    print(f"{meta.field}: {meta.old_value} → {meta.new_value}")
```

## Diff Modes

Control how strictly the engine validates document compatibility:

```python
from pygaeb import DiffMode

# DEFAULT: adds warnings for mismatched projects (recommended)
result = BoQDiff.compare(doc_a, doc_b)

# STRICT: raises ValueError if documents are from different projects
result = BoQDiff.compare(doc_a, doc_b, mode=DiffMode.STRICT)

# FORCE: suppresses all compatibility warnings
result = BoQDiff.compare(doc_a, doc_b, mode=DiffMode.FORCE)
```

## Warnings

The engine generates human-readable warnings for potentially misleading comparisons:

```python
for warning in result.warnings:
    print(f"⚠ {warning}")
```

Possible warnings:

- Documents may be from different projects
- Currency changed (financial comparisons may be misleading)
- Low match ratio (documents may be unrelated)
- GAEB versions differ

## Summary Properties

```python
s = result.summary

s.has_changes          # bool — any changes at all?
s.total_changes        # int — added + removed + modified
s.items_added          # int
s.items_removed        # int
s.items_modified       # int
s.items_unchanged      # int
s.match_ratio          # float (0.0–1.0)
s.is_likely_same_project  # bool
s.financial_impact     # Decimal or None
s.max_significance     # Significance enum
```

## Serialization

`DiffResult` is a Pydantic model — serialize to JSON for storage or API responses:

```python
json_str = result.model_dump_json(indent=2)
restored = DiffResult.model_validate_json(json_str)
```

## Limitations

- Only **procurement documents** (X80–X89) are supported. Trade, cost, and quantity documents raise `TypeError`.
- Matching is OZ-based. If items are renumbered between revisions without any shared OZ, they will appear as added/removed rather than modified.
- The diff engine is deterministic — no LLM is used. Semantic matching of renumbered items is planned as an optional enrichment layer.
