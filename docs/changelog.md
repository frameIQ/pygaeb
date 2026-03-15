# Changelog

All notable changes to pyGAEB are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-03-15

### Added

- **GAEB Trade Phase Support (X93-X97)** — first-class parsing, writing, and LLM support for trade workflows
- New models: `TradeOrder`, `OrderItem`, `OrderInfo`, `SupplierInfo`, `CustomerInfo`, `DeliveryPlaceInfo`, `PlannerInfo`, `InvoiceInfo`, `Address`
- `DocumentKind` enum (`PROCUREMENT` / `TRADE`) and `ExchangePhase.X93/X94/X96/X97`
- `GAEBDocument.is_trade`, `is_procurement`, `document_kind` properties for explicit discrimination
- `GAEBDocument.iter_items()` universal iteration across both document kinds
- `TradeParser` for `<Order>/<OrderItem>` XML structure
- `GAEBWriter` support for trade document output with phase-specific namespaces
- `DocumentAPI` trade-aware methods: `order`, `get_order_item()`, updated `summary()`
- `LLMClassifier` and `StructuredExtractor` now work with both procurement and trade documents
- Trade phases guide in documentation
- 38 new tests for trade parsing, models, writer round-trip, and API

## [1.0.1] - 2026-03-14

### Added

- **Version Conversion** — `GAEBConverter` for converting between DA XML 2.0–3.3 with `ConversionReport`
- `GAEBWriter.write()` now accepts `target_version` parameter for multi-version output (2.0–3.3)
- `GAEBWriter.to_bytes()` for in-memory serialization to any version
- Version-aware field dropping with warnings (e.g., `bim_guid` dropped in pre-3.3 output)
- DA XML 2.x output with automatic English-to-German element translation
- **Custom & Vendor Tag Access** — opt-in raw XML retention via `keep_xml=True`
- `source_element` field on `Item`, `BoQCtgy`, `AwardInfo`, `GAEBInfo` for raw lxml element access
- `GAEBDocument.xpath()` for XPath queries against the full XML tree with auto-mapped namespace prefix
- `DocumentAPI.xpath()` and `DocumentAPI.custom_tag()` convenience helpers

### Improved

- GAEB v3.2 parsing: text extraction from `<span>` wrappers, `<PrjInfo>` fallback, dual-format `BoQBkdn` support
- Test suite expanded to 248 tests

## [1.0.0] - 2026-03-14

### Added

- Multi-version GAEB DA XML parser (versions 2.0 through 3.3)
- Unified Pydantic v2 domain model (`GAEBDocument`, `Item`, `BoQ`, etc.)
- Automatic version/format/encoding detection
- XML recovery mode for malformed real-world files
- `GAEBParser.parse()`, `parse_bytes()`, `parse_string()` entry points
- Lenient and strict validation modes
- Structural, numeric, item, and phase-specific validation
- Cross-phase validation (`CrossPhaseValidator`)
- `GAEBWriter` for round-trip GAEB DA XML output
- JSON and CSV export (`to_json`, `to_csv`, `to_json_string`)
- LLM-powered item classification via LiteLLM (100+ providers)
- Three-level taxonomy (Trade > Element Type > Sub-Type)
- Confidence flags and manual overrides
- Structured extraction into user-defined Pydantic schemas
- Built-in schemas: `DoorSpec`, `WindowSpec`, `WallSpec`, `PipeSpec`
- Pluggable cache architecture: `InMemoryCache` (default), `SQLiteCache` (opt-in)
- `DocumentAPI` for advanced filtering and navigation
- `py.typed` marker for PEP 561 compliance
- Comprehensive test suite (193 tests)

[1.2.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.2.0
[1.0.1]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.1
[1.0.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.0
