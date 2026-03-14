# pyGAEB

**Python parser for GAEB DA XML construction data exchange files, with LLM-powered item classification.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Docs](https://readthedocs.org/projects/pygaeb/badge/?version=latest)](https://pygaeb.readthedocs.io)

---

pyGAEB parses, validates, classifies, and writes GAEB DA XML files (versions 2.0 through 3.3), producing a **unified Pydantic v2 domain model** from all inputs. An optional LLM classification layer enriches each item with a semantic construction element type via [LiteLLM](https://github.com/BerriAI/litellm) (100+ providers).

## Key Features

- **Multi-version parsing** — DA XML 2.0 through 3.3, all producing the same `GAEBDocument` model
- **Tolerant by default** — malformed real-world files are common; warnings not exceptions
- **Full round-trip** — parse, modify, write back to valid GAEB DA XML
- **LLM classification** — enrich items with semantic types (Door, Wall, Window...) via any LLM provider
- **Structured extraction** — pull typed attributes into your own Pydantic schemas using LLMs
- **Pluggable caching** — in-memory default, opt-in SQLite persistence, or bring your own backend
- **Export** — JSON (nested BoQ tree) and CSV (flat item table)
- **Cross-phase validation** — compare tender vs. bid documents for compliance
- **Fully typed** — PEP 561 compliant with `py.typed` marker

## At a Glance

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("tender.X83")

for item in doc.award.boq.iter_items():
    print(item.oz, item.short_text, item.total_price)
```

## Supported Versions

| Version | Parser Track | Status |
|---------|-------------|--------|
| DA XML 2.0 | Track A (German elements) | v1.0 |
| DA XML 2.1 | Track A (German elements) | v1.0 |
| DA XML 3.0 | Track B (English elements) | v1.0 |
| DA XML 3.1 | Track B (English elements) | v1.0 |
| DA XML 3.2 | Track B (English elements) | v1.0 |
| DA XML 3.3 | Track B (English elements) | v1.0 |
| GAEB 90 | Track C (fixed-width) | Planned v1.1 |

## Next Steps

- [Installation](getting-started/installation.md) — get pyGAEB installed
- [Quick Start](getting-started/quickstart.md) — parse your first file in 5 minutes
- [API Reference](reference/index.md) — complete class and function documentation
