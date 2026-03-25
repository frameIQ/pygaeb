# pyGAEB

**Python parser for GAEB DA XML construction data exchange files, with LLM-powered item classification.**

[![CI](https://github.com/frameIQ/pygaeb/actions/workflows/test.yml/badge.svg)](https://github.com/frameIQ/pygaeb/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/frameIQ/pygaeb/branch/main/graph/badge.svg)](https://codecov.io/gh/frameIQ/pygaeb)
[![PyPI version](https://img.shields.io/badge/version-1.7.0-blue.svg)](https://pypi.org/project/pyGAEB/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

> **[Deutsche Version (README.de.md)](README.de.md)**

pyGAEB parses, validates, classifies, and writes GAEB DA XML files (versions 2.0 through 3.3), producing a unified Pydantic v2 domain model from all inputs. It supports the full GAEB exchange phase spectrum — procurement (X80–X89), trade (X93–X97), cost & calculation (X50–X52), and quantity determination (X31).

An optional LLM classification layer enriches each item with a semantic construction element type via [LiteLLM](https://github.com/BerriAI/litellm) (100+ providers), with pluggable caching and customisable taxonomy.

## Highlights

- **Multi-version** — DA XML 2.0, 2.1, 3.0, 3.1, 3.2, 3.3 auto-detected
- **All exchange phases** — Procurement, Trade, Cost & Calculation, Quantity Determination
- **Security-hardened** — XXE prevention, Billion Laughs protection, file size guards, recursion depth limits
- **Extensible** — Custom validators, post-parse hooks, raw XML data collection, custom LLM taxonomy
- **LLM classification** — 100+ provider support via LiteLLM with cost estimation and persistent caching
- **Document diff** — Compare two BoQs with significance-classified field changes, structural diff, and financial impact
- **Round-trip** — Parse → modify → write back to any DA XML version
- **Version conversion** — Upgrade/downgrade between DA XML 2.0–3.3

## Installation

```bash
# Core parser + writer + export (zero LLM dependencies)
pip install pyGAEB

# With LLM classification (supports 100+ providers via LiteLLM)
pip install pyGAEB[llm]
```

## Quick Start

### Parse any GAEB file

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("tender.X83")    # DA XML 3.x
doc = GAEBParser.parse("old.D83")       # DA XML 2.x — same call

print(doc.source_version)               # SourceVersion.DA_XML_33
print(doc.exchange_phase)               # ExchangePhase.X83
print(doc.grand_total)                  # Decimal("1234567.89")
```

### Iterate items

Works for all document kinds — procurement, trade, cost, and quantity:

```python
for item in doc.iter_items():
    print(item.oz)              # "01.02.0030"
    print(item.short_text)      # "Mauerwerk der Innenwand…"
    print(item.qty)             # Decimal("1170.000")
    print(item.unit)            # "m2"
    print(item.unit_price)      # Decimal("45.50")
    print(item.total_price)     # Decimal("53235.00")
    print(item.item_type)       # ItemType.NORMAL
```

### Validation

```python
from pygaeb import GAEBParser, ValidationMode

# Lenient (default) — collect warnings, keep parsing
doc = GAEBParser.parse("tender.X83")
for issue in doc.validation_results:
    print(issue.severity, issue.message)

# Strict — raise on first ERROR
doc = GAEBParser.parse("tender.X83", validation=ValidationMode.STRICT)
```

### Custom Validators

Register project-specific validation rules:

```python
from pygaeb import register_validator, clear_validators
from pygaeb.models.item import ValidationResult
from pygaeb.models.enums import ValidationSeverity

def require_unit(doc):
    issues = []
    for item in doc.iter_items():
        if not item.unit:
            issues.append(
                ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=f"{item.oz}: missing unit",
                )
            )
    return issues

register_validator(require_unit)
doc = GAEBParser.parse("tender.X83")
# require_unit results are now in doc.validation_results

# Or per-call (not added to the global registry):
doc = GAEBParser.parse("tender.X83", extra_validators=[require_unit])
```

### Write / Round-trip

```python
from pygaeb import GAEBWriter, ExchangePhase
from decimal import Decimal

doc = GAEBParser.parse("tender.X83")
item = doc.award.boq.get_item("01.02.0030")
item.unit_price = Decimal("48.00")

GAEBWriter.write(doc, "bid.X84", phase=ExchangePhase.X84)
```

### Version Conversion

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

### Export to JSON / CSV

```python
from pygaeb.convert import to_json, to_csv

to_json(doc, "boq.json")     # full nested BoQ tree
to_csv(doc, "items.csv")     # flat item table with classification columns
```

### Trade Phases (X93–X97)

```python
doc = GAEBParser.parse("order.X96")
print(doc.document_kind)    # DocumentKind.TRADE
print(doc.is_trade)         # True

for item in doc.order.items:
    print(item.art_no, item.short_text, item.net_price)

print(doc.order.supplier_info.address.name)
```

### Cost & Calculation Phases (X50–X52)

```python
doc = GAEBParser.parse("costing.X50")
print(doc.document_kind)    # DocumentKind.COST

for elem in doc.elemental_costing.body.iter_cost_elements():
    print(elem.ele_no, elem.short_text, elem.total_cost)
```

### Quantity Determination (X31)

```python
doc = GAEBParser.parse("measurements.X31")
print(doc.document_kind)    # DocumentKind.QUANTITY

for item in doc.qty_determination.boq.iter_items():
    print(item.oz, item.qty_determ_items)
```

### Financial Summaries & Project Info

```python
doc = GAEBParser.parse("tender.X86")

# BoQ-level totals
totals = doc.award.boq.info.totals
print(totals.total_net, totals.total_gross, totals.vat_amount)

# Per-VAT-rate breakdown
for vp in totals.vat_parts:
    print(f"{vp.vat_pcnt}%: net {vp.net_amount} → gross {vp.gross_amount}")

# Project metadata
print(doc.award.prj_id, doc.award.description, doc.award.currency_label)
```

### Tree Navigation (BoQ Hierarchy)

Navigate the BoQ with parent references, depth tracking, and indexed lookups:

```python
from pygaeb import BoQTree, NodeKind

tree = BoQTree(doc.award.boq)

# Find an item and navigate up
node = tree.find_item("01.01.0010")
print(node.parent.label)       # "Mauerwerk"
print(node.depth)              # level in tree
print(node.label_path)         # ["BoQ", "Default", "Rohbau", "Mauerwerk", "..."]
print(node.siblings)           # sibling nodes

# Walk the hierarchy
for node in tree.walk():
    indent = "  " * node.depth
    print(f"{indent}{node.kind.value}: {node.label}")

# Subtree queries
expensive = tree.root.find_all(
    lambda n: n.kind == NodeKind.ITEM
    and n.item.total_price
    and n.item.total_price > 50000
)
```

### Document Diff (Compare Two BoQs)

Compare two GAEB documents and get structured, significance-classified changes:

```python
from pygaeb import GAEBParser, BoQDiff, DiffMode, Significance

doc_a = GAEBParser.parse("tender_v1.X83")
doc_b = GAEBParser.parse("tender_v2.X83")

result = BoQDiff.compare(doc_a, doc_b)

# Top-level summary
print(result.summary.total_changes)      # 12
print(result.summary.financial_impact)   # Decimal("45230.00")
print(result.summary.max_significance)   # Significance.CRITICAL

# Items added / removed / modified
for item in result.items.added:
    print(f"+ {item.oz}: {item.short_text}")

for item in result.items.removed:
    print(f"- {item.oz}: {item.short_text}")

# Field-level changes with significance
for mod in result.items.modified:
    for change in mod.changes:
        print(f"  {mod.oz} {change.field}: {change.old_value} → {change.new_value}"
              f" [{change.significance.value}]")

# Filter by significance
critical_only = result.items.filter_modified(Significance.CRITICAL)

# Structural changes (sections added/removed/renamed)
for sec in result.structure.sections_added:
    print(f"New section: {sec.label}")

# Strict mode: raises ValueError if documents are from different projects
result = BoQDiff.compare(doc_a, doc_b, mode=DiffMode.STRICT)
```

### LLM Classification

```python
from pygaeb import LLMClassifier

# Default: in-memory cache (no disk I/O, session-scoped)
classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")
# classifier = LLMClassifier(model="gpt-4o")
# classifier = LLMClassifier(model="ollama/llama3")  # local, free, private

# Opt-in: persistent SQLite cache (survives across runs)
from pygaeb import SQLiteCache
classifier = LLMClassifier(cache=SQLiteCache("~/.pygaeb/cache"))

# Custom taxonomy and prompt
classifier = LLMClassifier(
    model="openai/gpt-4o",
    taxonomy={"Electrical": {"Cable": ["Ladder", "Perforated"]}},
    prompt_template="You are a specialist classifying MEP items...",
)

# Check cost before running
estimate = await classifier.estimate_cost(doc)
print(f"Will classify {estimate.items_to_classify} items for ~${estimate.estimated_cost_usd:.2f}")

# Classify all items
await classifier.enrich(doc)

# Or synchronous
classifier.enrich_sync(doc)

for item in doc.iter_items():
    if item.classification:
        print(item.oz, item.classification.element_type, item.classification.confidence)
```

### Structured Extraction — Custom Schemas

After classification, extract typed attributes into your own Pydantic schema:

```python
from pydantic import BaseModel, Field
from typing import Optional
from pygaeb import StructuredExtractor

class DoorSpec(BaseModel):
    door_type: str = Field("", description="single, double, sliding")
    width_mm: Optional[int] = Field(None, description="Width in mm")
    fire_rating: Optional[str] = Field(None, description="T30, T60, T90")
    glazing: bool = Field(False, description="Has glass panels")
    material: str = Field("", description="wood, steel, aluminium")

extractor = StructuredExtractor(model="anthropic/claude-sonnet-4-6")

# Extract from all items classified as "Door"
doors = await extractor.extract(doc, schema=DoorSpec, element_type="Door")
for item, spec in doors:
    print(item.oz, spec.door_type, spec.fire_rating, spec.width_mm)

# Filter by trade (broad) or sub_type (narrow)
pipes = await extractor.extract(doc, schema=PipeSpec, trade="MEP-Plumbing")
fire_doors = await extractor.extract(doc, schema=DoorSpec, sub_type="Fire Door")

# Or synchronous
doors = extractor.extract_sync(doc, schema=DoorSpec, element_type="Door")
```

Built-in starter schemas: `DoorSpec`, `WindowSpec`, `WallSpec`, `PipeSpec` — or define your own.

### Post-Parse Hook & Raw Data Collection

Extract vendor-specific XML elements during parsing:

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

Or automatically collect all unknown XML elements:

```python
doc = GAEBParser.parse("file.X83", collect_raw_data=True)
for item in doc.iter_items():
    if item.raw_data:
        print(f"{item.oz}: extra fields = {item.raw_data}")
```

### Custom & Vendor Tags (XPath)

```python
doc = GAEBParser.parse("vendor_file.X83", keep_xml=True)

# XPath across the whole document
codes = doc.xpath("//g:VendorCostCode/text()")

# Per-item raw element access
for item in doc.iter_items():
    el = item.source_element  # original lxml element

# Free memory when done
doc.discard_xml()
```

### Custom Cache Backend

```python
from pygaeb import CacheBackend, InMemoryCache, SQLiteCache

# Default: in-memory (LRU-bounded, session-scoped)
classifier = LLMClassifier()

# Persistent: SQLite
classifier = LLMClassifier(cache=SQLiteCache("~/.pygaeb/cache"))

# Bring your own: implement CacheBackend protocol
class RedisCache:
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def keys(self) -> list[str]: ...
    def clear(self) -> None: ...
    def close(self) -> None: ...

classifier = LLMClassifier(cache=RedisCache())
```

### Cross-Phase Validation

```python
from pygaeb import GAEBParser, CrossPhaseValidator

tender = GAEBParser.parse("tender.X83")
bid = GAEBParser.parse("bid.X84")

issues = CrossPhaseValidator.check(source=tender, response=bid)
for issue in issues:
    print(issue.severity, issue.message)
```

## Supported Versions & Exchange Phases

| Version | Parser Track | Status |
|---------|-------------|--------|
| DA XML 2.0 | Track A (German elements) | v1.0 |
| DA XML 2.1 | Track A (German elements) | v1.0 |
| DA XML 3.0 | Track B (English elements) | v1.0 |
| DA XML 3.1 | Track B (English elements) | v1.0 |
| DA XML 3.2 | Track B (English elements) | v1.0 |
| DA XML 3.3 | Track B (English elements) | v1.0 |
| GAEB 90 | Track C (fixed-width) | Planned |

| Phase | Description | Since |
|-------|-------------|-------|
| X31 | Quantity Determination | v1.4.0 |
| X50, X51, X52 | Cost & Calculation | v1.3.0 |
| X80–X89 | Procurement (tender, bid, award, invoice) | v1.0.0 |
| X93, X94, X96, X97 | Trade (material ordering) | v1.2.0 |

## Configuration

```python
from pygaeb import configure

configure(
    default_model="ollama/llama3",        # LLM model for classification
    classifier_concurrency=10,            # parallel LLM calls
    xsd_dir="/opt/gaeb-schemas",          # optional XSD validation
    log_level="DEBUG",                    # applied to pygaeb.* loggers
    max_file_size_mb=200,                 # input file size limit
)
```

Or via environment variables:

```bash
export PYGAEB_DEFAULT_MODEL=ollama/llama3
export PYGAEB_XSD_DIR=/opt/gaeb-schemas
export PYGAEB_LOG_LEVEL=DEBUG
export PYGAEB_MAX_FILE_SIZE_MB=200
```

## Security

pyGAEB includes security hardening since v1.6.0:

- **XXE prevention** — All XML parsing uses hardened parsers with `resolve_entities=False` and `no_network=True`
- **Billion Laughs protection** — Entity expansion bombs are blocked
- **File size guard** — Configurable limit (default 100 MB) prevents memory exhaustion
- **Recursion depth limits** — Hierarchy walkers cap at 50 levels to prevent stack overflow
- **Bounded caching** — `InMemoryCache` uses LRU eviction (default 10,000 entries)

## Documentation

Full documentation is available at [Read the Docs](https://pygaeb.readthedocs.io/).

- [Quick Start](https://pygaeb.readthedocs.io/getting-started/quickstart/)
- [Parsing Guide](https://pygaeb.readthedocs.io/guides/parsing/)
- [Trade Phases](https://pygaeb.readthedocs.io/guides/trade-phases/)
- [Cost & Calculation](https://pygaeb.readthedocs.io/guides/cost-phases/)
- [Quantity Determination](https://pygaeb.readthedocs.io/guides/quantity-phases/)
- [Tree Navigation](https://pygaeb.readthedocs.io/guides/tree-navigation/)
- [Document Diff](https://pygaeb.readthedocs.io/guides/document-diff/)
- [Extensibility](https://pygaeb.readthedocs.io/guides/extensibility/)
- [Classification](https://pygaeb.readthedocs.io/guides/classification/)
- [Version Conversion](https://pygaeb.readthedocs.io/guides/conversion/)
- [API Reference](https://pygaeb.readthedocs.io/reference/)

## License

MIT — see [LICENSE](LICENSE) for details.
