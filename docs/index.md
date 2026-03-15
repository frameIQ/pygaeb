# pyGAEB

**Python parser for GAEB DA XML construction data exchange files, with LLM-powered item classification.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Docs](https://readthedocs.org/projects/pygaeb/badge/?version=latest)](https://pygaeb.readthedocs.io)

---

pyGAEB parses, validates, classifies, and writes GAEB DA XML files (versions 2.0 through 3.3), producing a **unified Pydantic v2 domain model** from all inputs. An optional LLM classification layer enriches each item with a semantic construction element type via [LiteLLM](https://github.com/BerriAI/litellm) (100+ providers).

## Key Features

- **Multi-version parsing** — DA XML 2.0 through 3.3, all producing the same `GAEBDocument` model
- **Procurement + Trade phases** — full support for X80–X89 (procurement) and X93–X97 (trade) workflows
- **Cost & Calculation phases** — X50/X51 elemental costing with BIM integration, X52 calculation approaches
- **Quantity determination** — X31 quantity take-off data with REB 23.003 measurement rows, catalogs, and attachments
- **Tolerant by default** — malformed real-world files are common; warnings not exceptions
- **Version conversion** — convert between DA XML 2.0–3.3 with data-loss reports
- **Full round-trip** — parse, modify, write back to valid GAEB DA XML
- **LLM classification** — enrich items with semantic types (Door, Wall, Window...) via any LLM provider
- **Structured extraction** — pull typed attributes into your own Pydantic schemas using LLMs
- **Custom & vendor tag access** — opt-in raw XML retention, XPath queries, vendor extension extraction
- **Pluggable caching** — in-memory default, opt-in SQLite persistence, or bring your own backend
- **Export** — JSON (nested BoQ tree) and CSV (flat item table)
- **Cross-phase validation** — compare tender vs. bid documents for compliance
- **Fully typed** — PEP 561 compliant with `py.typed` marker

## At a Glance

```python
from pygaeb import GAEBParser

# Procurement (X80-X89) — same as always
doc = GAEBParser.parse("tender.X83")
for item in doc.award.boq.iter_items():
    print(item.oz, item.short_text, item.total_price)

# Trade (X93-X97) — auto-detected, same entry point
doc = GAEBParser.parse("order.X96")
for item in doc.order.items:
    print(item.art_no, item.short_text, item.net_price)

# Cost estimation (X50/X51) — recursive hierarchy, BIM refs
doc = GAEBParser.parse("catalog.X50")
for elem in doc.iter_items():
    print(elem.ele_no, elem.short_text, elem.item_total)

# Quantity determination (X31) — measurement data
doc = GAEBParser.parse("measurements.X31")
for item in doc.iter_items():
    print(item.oz, item.qty, len(item.determ_items), "rows")

# Universal iteration — works for all document kinds
for item in doc.iter_items():
    print(item)
```

## Supported Versions & Phases

| Version | Parser Track | Status |
|---------|-------------|--------|
| DA XML 2.0 | Track A (German elements) | v1.0 |
| DA XML 2.1 | Track A (German elements) | v1.0 |
| DA XML 3.0 | Track B (English elements) | v1.0 |
| DA XML 3.1 | Track B (English elements) | v1.0 |
| DA XML 3.2 | Track B (English elements) | v1.0 |
| DA XML 3.3 | Track B (English elements) | v1.0 |
| GAEB 90 | Track C (fixed-width) | Planned |

| Phase Group | Phases | Status |
|-------------|--------|--------|
| Procurement | X80–X89 (tender, bid, award, invoice…) | v1.0 |
| Trade | X93, X94, X96, X97 (price inquiry, offer, order, confirmation) | v1.2 |
| Cost & Calculation | X50, X51 (elemental costing), X52 (calculation approaches) | v1.3 |
| Quantity Determination | X31 (quantity take-off, REB 23.003 measurements) | v1.4 |

## Next Steps

- [Installation](getting-started/installation.md) — get pyGAEB installed
- [Quick Start](getting-started/quickstart.md) — parse your first file in 5 minutes
- [Trade Phases](guides/trade-phases.md) — working with X93–X97 trade orders
- [Cost & Calculation Phases](guides/cost-phases.md) — working with X50–X52 cost estimation and calculation
- [Quantity Determination](guides/quantity-phases.md) — working with X31 quantity take-off data
- [API Reference](reference/index.md) — complete class and function documentation
