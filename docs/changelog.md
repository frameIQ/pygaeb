# Changelog

All notable changes to pyGAEB are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.11.0] - 2026-03-24

### Added

- **Excel Export** — `to_excel()` exports any GAEB document to structured Excel workbooks with hierarchy-aware layout and phase-specific columns.
- Two export modes: `structured` (single sheet) and `full` (BoQ + Items + Summary + Info sheets).
- All document kinds supported with phase-appropriate columns.
- Optional columns via `include_long_text`, `include_classification`, `include_bim_guid`.
- 34 new tests.

## [1.10.0] - 2026-03-24

### Added

- **BoQ Builder API** — `BoQBuilder` provides programmatic construction of GAEB documents from scratch with a fluent, explicit-object API.
- **Auto OZ generation** — Ordinal numbers auto-generated from category `rno` + sequence when `oz` is omitted.
- **Decimal convenience** — `int`/`float`/`str` auto-converted to `Decimal`; auto-computes `total_price` when missing.
- **Field name validation** — Unknown kwargs raise `ValueError` with typo suggestions.
- **Phase-aware rules** — Warns or errors when items violate exchange phase semantics.
- **Version compatibility checks** — Detects fields incompatible with the target DA XML version.
- **Duplicate OZ detection**, **auto totals & BoQBkdn**, **implicit lot shortcut**, **ItemHandle** for long text/attachments.
- Optional XSD validation via `build(xsd_dir=...)`.
- 46 new tests.

## [1.9.0] - 2026-03-24

### Added

- **Document Diff Engine** — `BoQDiff.compare(doc_a, doc_b)` performs a deterministic, field-by-field comparison of two GAEB procurement documents with structured results.
- **OZ-based item matching** — Lot-aware matching by OZ (ordinal number) with global fallback for items that moved between lots.
- **Field-level change detection** — Each changed field carries a `Significance` level (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) based on construction context impact.
- **Structural diff** — Detects added, removed, and renamed sections (categories), as well as items that moved between categories or lots.
- **`DiffMode`** enum — `DEFAULT` (warnings for mismatched projects), `STRICT` (raises `ValueError`), `FORCE` (suppresses warnings).
- **`DiffResult`** Pydantic model — Complete comparison output with `summary`, `items`, `structure`, `metadata`, and `warnings` sections. Fully serializable to JSON.
- **Financial impact** — Automatic computation of net financial impact (`grand_total_b - grand_total_a`).
- **Match ratio & compatibility warnings** — Low match ratio detection, different project warnings, currency mismatch alerts, version difference notices.
- **Result filtering** — `ItemModified.filter_changes(min_significance)` and `ItemDiffSummary.filter_modified(min_significance)` for targeted reporting.
- New exports: `BoQDiff`, `DiffMode`, `DiffResult`, `DiffSummary`, `DiffDocInfo`, `Significance`, `FieldChange`, `ItemAdded`, `ItemRemoved`, `ItemModified`, `ItemMoved`, `ItemDiffSummary`, `MetadataChange`, `SectionChange`, `SectionRenamed`, `StructureDiffSummary`.
- 53 new tests covering item matching, field comparison, structural diff, integration, models, lazy imports, and edge cases.

## [1.8.0] - 2026-03-24

### Added

- **Read-only BoQ Tree API** — `BoQTree` adapter wraps an existing `BoQ` and builds a navigable node graph with parent references, depth tracking, and indexed lookups. The underlying Pydantic models are not modified.
- **`BoQNode`** — Lightweight tree node with O(1) `parent`, `children`, `depth`, `index`, `siblings`, `ancestors`, `path`, `next_sibling`, `prev_sibling`, `is_leaf`, `is_root` properties.
- **Type-safe model accessors** — `node.boq`, `node.lot`, `node.category`, `node.item` raise `TypeError` if accessed on the wrong node kind.
- **Unified convenience properties** — `node.label`, `node.rno`, `node.label_path` work across all node kinds (root, lot, category, item).
- **Subtree queries** — `node.iter_descendants()`, `node.iter_items()`, `node.iter_categories()`, `node.find(predicate)`, `node.find_all(predicate)`.
- **`BoQTree` lookups** — `tree.find_item(oz)` (O(1) via index), `tree.find_category(rno)`, `tree.find_all_categories(rno)`.
- **Tree traversal** — `tree.walk()` (depth-first) and `tree.walk_bfs()` (breadth-first) over all nodes.
- **`NodeKind`** enum — `ROOT`, `LOT`, `CATEGORY`, `ITEM` discriminator for node types.
- New exports: `BoQTree`, `BoQNode`, `NodeKind`.
- New guide: [Tree Navigation](guides/tree-navigation.md).
- 87 new tests covering root, lots, categories, items, children ordering, parent chains, ancestors, siblings, lookups, iteration, predicate search, DFS/BFS traversal, counts, multi-lot, type-safe accessors, empty categories, model identity, and repr.

## [1.7.1] - 2026-03-15

### Fixed

- **Procurement long text parsing** — Items in DA XML 3.x procurement files (X80–X89) now correctly extract long text from the `<Description>/<CompleteText>/<DetailTxt>` structure, matching the behavior already present in trade and cost parsers.
- **OWN (owner/client) parsed from wrong element** — `<OWN>` is now correctly located as a child of `<Award>` instead of `<AwardInfo>`, producing a full `Address` with all `tgAddress` fields instead of a bare string.

### Added

- **AwardInfo metadata** — 13 new fields on `AwardInfo`: `category`, `open_date`, `open_time`, `eval_end`, `submit_location`, `construction_start`, `construction_end`, `contract_no`, `contract_date`, `accept_type`, `warranty_duration`, `warranty_unit`, and `award_no`.
- **`AwardInfo.owner_address`** — Full `Address` model for the `<OWN>/<Address>` structure, including `award_no` from `<OWN>/<AwardNo>`.
- **`Address` model extended to match `tgAddress` XSD** — Added `name3`, `name4`, `contact`, `iln`, and `vat_id` fields. The `name` field now maps to `<Name1>` (with `<Name>` fallback for older files).
- **`_parse_address` consolidated** — Moved from `TradeParser` and `QtyParser` into `BaseV3Parser` so all phases (procurement, trade, cost, quantity) share the same XSD-complete address parsing logic.
- **Writer updated** — `_add_address` emits XSD-canonical `<Name1>` through `<Name4>`, `<Contact>`, `<ILN>`, and `<VATID>`. `_add_award` serializes all new AwardInfo fields and the proper `<OWN>/<Address>/<AwardNo>` structure.
- **German element map** — Added DA XML 2.x mappings for new AwardInfo tags (`Vergabekategorie`, `Eroeffnungsdatum`, `Baubeginn`, `Bauende`, `Vertragsnummer`, `Vertragsdatum`, `Gewaehrleistungsdauer`, etc.).
- 48 new tests covering long text fallback, AwardInfo metadata, OWN address with full `tgAddress` fields, model defaults, round-trip serialization, and integration against the `tender.X81` fixture.

## [1.7.0] - 2026-03-15

### Added

- **Custom validator registry** — `register_validator()` / `clear_validators()` for project-specific validation rules that run after the built-in pipeline. Per-call validators via `extra_validators=` on `GAEBParser.parse()`.
- **Post-parse hook** — `post_parse_hook=` callback on `GAEBParser.parse()` / `parse_bytes()` / `parse_string()` receives `(item, source_element)` for each parsed item. Auto-enables `keep_xml` and discards afterwards when needed.
- **`collect_raw_data`** — `GAEBParser.parse(..., collect_raw_data=True)` populates `item.raw_data` with XML child elements the parser did not consume.
- **Custom LLM taxonomy & prompt** — `LLMClassifier(taxonomy=..., prompt_template=...)` for per-instance overrides. `register_prompt()` for reusable prompt templates.
- **`log_level` applied** — The `log_level` setting is now applied to the `pygaeb` logger on `get_settings()` and `configure()`.
- New exports: `register_validator`, `clear_validators`, `reset_settings`, `register_prompt`.
- New guide: [Extensibility](guides/extensibility.md).

## [1.6.0] - 2026-03-15

### Security

- **XXE prevention** — All XML parsing now uses hardened `lxml.XMLParser` with `resolve_entities=False`, `no_network=True`, and `huge_tree=False`. External entity injection and Billion Laughs attacks are blocked.
- **File size guard** — New `max_file_size` parameter on `GAEBParser.parse()`, `parse_bytes()`, and `parse_string()`. Default limit: 100 MB (configurable via `max_file_size_mb` setting). Prevents memory exhaustion from oversized inputs.
- **ReDoS removal** — Removed unused `_UNCLOSED_TAG_RE` regex that had catastrophic backtracking potential.

### Fixed

- **Recursion depth limits** — Hierarchy walkers (`_walk_ctgy`, `_walk_ec_ctgy`, `_walk_qty_ctgy`) now cap at 50 levels to prevent stack overflow on malicious/deep structures. `BoQCtgy.iter_items()`, `QtyBoQCtgy.iter_items()`, and `CostElement.iter_cost_elements()` converted from recursive to iterative.
- **InMemoryCache bounded** — Now uses LRU eviction with a default `maxsize=10,000` entries to prevent unbounded growth in long-running processes.
- **SQLiteCache resource cleanup** — Added `__del__` fallback to close connections. Cursors are now explicitly closed after each query.
- **XSD validation memory** — Reuses the parsed XML tree (when `keep_xml=True`) instead of reparsing. XSD files opened with explicit file handles.

### Added

- `GAEBDocument.discard_xml()` — Releases the retained lxml tree and all `source_element` references to free memory after XPath/raw-element work is done.
- `pygaeb.parser._xml_safety` — Shared module with `SAFE_PARSER`, `SAFE_RECOVER_PARSER`, and `safe_iterparse()` constants.
- `max_file_size_mb` setting in `PyGAEBSettings` (default 100).

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

[1.8.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.8.0
[1.7.1]: https://github.com/frameiq/pygaeb/releases/tag/v1.7.1
[1.7.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.7.0
[1.6.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.6.0
[1.5.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.5.0
[1.4.1]: https://github.com/frameiq/pygaeb/releases/tag/v1.4.1
[1.4.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.4.0
[1.3.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.3.0
[1.2.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.2.0
[1.0.1]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.1
[1.0.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.0
