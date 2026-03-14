# pyGAEB

**Python parser for GAEB DA XML construction data exchange files, with LLM-powered item classification.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

pyGAEB parses, validates, classifies, and writes GAEB DA XML files (versions 2.0 through 3.3), producing a unified Pydantic v2 domain model from all inputs. An optional LLM classification layer enriches each item with a semantic construction element type via [LiteLLM](https://github.com/BerriAI/litellm) (100+ providers).

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

```python
for item in doc.award.boq.iter_items():
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

### Write / Round-trip

```python
from pygaeb import GAEBWriter, ExchangePhase
from decimal import Decimal

doc = GAEBParser.parse("tender.X83")
item = doc.award.boq.get_item("01.02.0030")
item.unit_price = Decimal("48.00")

GAEBWriter.write(doc, "bid.X84", phase=ExchangePhase.X84)
```

### Export to JSON / CSV

```python
from pygaeb.convert import to_json, to_csv

to_json(doc, "boq.json")     # full nested BoQ tree
to_csv(doc, "items.csv")     # flat item table with classification columns
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
classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6", cache=SQLiteCache("~/.pygaeb/cache"))

# Check cost before running
estimate = await classifier.estimate_cost(doc)
print(f"Will classify {estimate.items_to_classify} items for ~${estimate.estimated_cost_usd:.2f}")

# Classify all items
await classifier.enrich(doc)

# Or synchronous
classifier.enrich_sync(doc)

for item in doc.award.boq.iter_items():
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

### Custom Cache Backend

```python
from pygaeb import CacheBackend, InMemoryCache, SQLiteCache

# Default: in-memory (no disk, session-scoped)
classifier = LLMClassifier()

# Persistent: SQLite
classifier = LLMClassifier(cache=SQLiteCache("~/.pygaeb/cache"))

# Share one backend between classifier and extractor
shared = SQLiteCache("/tmp/project-cache")
classifier = LLMClassifier(cache=shared)
extractor = StructuredExtractor(cache=shared)

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

## Supported Versions

| Version | Parser Track | Status |
|---------|-------------|--------|
| DA XML 2.0 | Track A (German elements) | ✅ v1.0 |
| DA XML 2.1 | Track A (German elements) | ✅ v1.0 |
| DA XML 3.0 | Track B (English elements) | ✅ v1.0 |
| DA XML 3.1 | Track B (English elements) | ✅ v1.0 |
| DA XML 3.2 | Track B (English elements) | ✅ v1.0 |
| DA XML 3.3 | Track B (English elements) | ✅ v1.0 |
| GAEB 90 | Track C (fixed-width) | 🔜 v1.1 |

## Configuration

```bash
# Environment variables
export PYGAEB_DEFAULT_MODEL=ollama/llama3
export PYGAEB_XSD_DIR=/opt/gaeb-schemas

# Or programmatic
from pygaeb import PyGAEBSettings
settings = PyGAEBSettings(default_model="gpt-4o", classifier_concurrency=10)
```

## License

MIT — see [LICENSE](LICENSE) for details.
