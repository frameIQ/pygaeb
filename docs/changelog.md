# Changelog

All notable changes to pyGAEB are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-03-15

### Added

- **Procurement Totals + VAT** — `Totals` and `VATPart` models for authoritative financial summaries from `<Totals>` elements
- `totals` field on `BoQInfo`, `BoQCtgy`, and `Lot` — parsed from and written back to XML
- Full `<Totals>` schema coverage: `Total`, `DiscountPcnt`/`DiscountAmt`/`TotAfterDisc`, `TotalLSUM`, `VAT`, `TotalNet`, `TotalNetUpComp` (UpComp1–6), `VATPart` (multiple VAT rates with per-rate breakdown), `VATAmount`, `TotalGross`
- **Item-level VAT** — `vat` field on `Item` for per-item VAT rate percentage
- **Complete PrjInfo** — `AwardInfo` now exposes all `<PrjInfo>` fields: `prj_id`, `lbl_prj`, `description`, `currency_label`, `bid_comm_perm`, `alter_bid_perm`, `up_frac_dig`, `ctlg_assigns`
- `<PrjInfo>` serialization in writer — round-trips project metadata correctly
- `UPFracDig` (unit price decimal places) — parsed and exposed on `AwardInfo.up_frac_dig`
- **Procurement Item Attachments** — URI references (`<attachment>`) and embedded base64 images (`<image>`) from `<DetailTxt>` are now parsed into `Item.attachments`
- `DocumentAPI.summary()` now includes `total_net`, `total_gross`, `vat_rate`, `vat_amount`, and `up_frac_dig` for procurement documents
- `Totals` and `VATPart` exported from top-level `pygaeb` module
- 40 new tests for totals parsing/writing, VATPart, item VAT, PrjInfo, and attachments

## [1.4.1] - 2026-03-15

### Added

- **Shared Catalog Module** — `CtlgAssign` and `Catalog` moved to `pygaeb.models.catalog` for cross-package reuse
- `ctlg_assigns` field on `Item`, `BoQCtgy`, `BoQInfo`, `CostElement`, and `ECCtgy`
- `CtlgAssign` parsing in procurement (`_parse_item`, `_parse_ctgy`, `_parse_boq_info`), cost (`CostElement`, `ECCtgy`), and trade (`TradeOrder`, `OrderInfo`, `OrderItem`)
- `CtlgAssign` serialization in procurement writer (items, categories, BoQInfo) and trade writer (Order, OrderInfo, OrderItem)
- `ctlg_assigns` field on `OrderItem`, `OrderInfo`, and `TradeOrder`
- **Phase-specific procurement namespace** — `procurement_namespace()` helper; writer output now uses `DA83/3.3` for X83, `DA84/3.3` for X84, etc. (was hardcoded `DA86`)
- DA XML 3.0 and earlier correctly falls back to the fixed `200407` namespace
- **MarkupItem support (X52)** — `<MarkupItem>` elements parsed as `Item` with `ItemType.MARKUP`
- `MarkupSubQty` model for markup sub-quantity references
- `markup_type` and `markup_sub_qtys` fields on `Item`
- `_add_markup_item()` writer function for round-trip `<MarkupItem>` serialization
- 33 new tests covering all findings (including trade CtlgAssign)
- `MarkupSubQty` added to top-level `__all__` exports

### Fixed

- Procurement writer namespace no longer hardcodes `DA86` — each exchange phase gets its correct namespace
- `CtlgAssign` and `Catalog` no longer tied to `pygaeb.models.quantity`; re-exported for backward compatibility

## [1.4.0] - 2026-03-15

### Added

- **GAEB Quantity Determination Phase Support (X31)** — first-class parsing, writing, and API support for quantity take-off data
- New `DocumentKind.QUANTITY` for X31 quantity determination documents
- `ExchangePhase.X31` `is_quantity` property and `_QUANTITY_PHASES` frozenset
- `QtyDetermination` root model with `QtyBoQ`, `QtyBoQCtgy`, `QtyItem` hierarchy
- `QtyItem` — thin BoQ position with OZ, measurement data, and catalog assignments (no text/prices)
- `QDetermItem` and `QTakeoffRow` for REB 23.003 measurement row data
- `Catalog` and `CtlgAssign` for DIN 276, BIM, locality, and other catalog systems
- `QtyAttachment` for base64-encoded attachments (photos, sketches, PDFs) at BoQ level
- `QtyDetermInfo` metadata (REB method, dates, creator/profiler addresses)
- `PrjInfoQD` for external project references
- `QtyParser` for `<QtyDeterm>/<BoQ>/<QtyItem>` XML structure
- `GAEBWriter` support for X31 document output with quantity-specific namespace (`DA31`)
- `DocumentAPI` quantity-aware: `is_quantity`, `qty_determination`, `get_qty_item()`, updated `summary()` and `iter_hierarchy()`
- `GAEBDocument.is_quantity`, `qty_determination` property, updated `iter_items()`, `grand_total`, `item_count`, `memory_estimate_mb`
- Cross-referencing capability between X31 quantity items and procurement BoQ via OZ matching
- Quantity determination documentation guide
- 71 new tests for quantity parsing, models, writer round-trip, API, and enums

## [1.3.0] - 2026-03-15

### Added

- **GAEB Cost & Calculation Phase Support (X50, X51, X52)** — first-class parsing, writing, and LLM support for cost estimation workflows
- New `DocumentKind.COST` for X50/X51 elemental costing documents
- `ExchangePhase.X50`, `X51`, `X52` enum values with `is_cost` property
- `ElementalCosting` root model with recursive `ECBody`/`ECCtgy`/`CostElement` hierarchy
- `CostElement` with LLM-compatible interface (`short_text`, `long_text`, `qty`, `unit`, `classification`, `extractions`)
- `CostProperty` for BIM integration (`cad_id`, `arithmetic_qty_approach`, `value_qty_approach`)
- `RefGroup` for cross-references between cost elements, BoQ items, and dimension elements
- `DimensionElement` and `CategoryElement` support
- `ECInfo` metadata (ec_type, ec_method, breakdowns, consortium members, totals)
- `CostParser` for `<ElementalCosting>/<ECBody>/<CostElement>` XML structure
- X52 extensions: `CostApproach`, `CostType`, `up_components` (UPComp1-6), `discount_pct` on `Item`
- `GAEBWriter` support for cost document output (X50/X51) and X52 fields
- `DocumentAPI` cost-aware: `is_cost`, `elemental_costing`, `get_cost_element()`, updated `summary()` and `iter_hierarchy()`
- `GAEBDocument.is_cost`, `elemental_costing` property, updated `iter_items()`, `grand_total`, `item_count`
- LLM classifier and extractor `_item_label` updated for `ele_no`
- Cost phases documentation guide
- 65 new tests for cost parsing, models, writer round-trip, and API

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

[1.5.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.5.0
[1.4.1]: https://github.com/frameiq/pygaeb/releases/tag/v1.4.1
[1.4.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.4.0
[1.3.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.3.0
[1.2.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.2.0
[1.0.1]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.1
[1.0.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.0
