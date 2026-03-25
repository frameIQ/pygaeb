# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- 87 new tests covering tree navigation, lookups, iteration, and multi-lot documents.

## [1.7.1] - 2026-03-15

### Fixed

- **Procurement long text parsing** — Items in DA XML 3.x procurement files (X80–X89) now correctly extract long text from the `<Description>/<CompleteText>/<DetailTxt>` structure.
- **OWN (owner/client) parsed from wrong element** — `<OWN>` is now correctly located as a child of `<Award>` instead of `<AwardInfo>`, producing a full `Address` with all `tgAddress` fields.

### Added

- **AwardInfo metadata** — 13 new fields on `AwardInfo`: `category`, `open_date`, `open_time`, `eval_end`, `submit_location`, `construction_start`, `construction_end`, `contract_no`, `contract_date`, `accept_type`, `warranty_duration`, `warranty_unit`, and `award_no`.
- **`AwardInfo.owner_address`** — Full `Address` model for the `<OWN>/<Address>` structure.
- **`Address` model extended to match `tgAddress` XSD** — Added `name3`, `name4`, `contact`, `iln`, and `vat_id` fields.
- **`_parse_address` consolidated** — Moved into `BaseV3Parser` so all phases share XSD-complete address parsing.
- Writer, German element map, and 48 new tests updated accordingly.

## [1.0.0] - 2026-03-14

### Added

- Unified domain model (GAEBDocument, Item, BoQ, AwardInfo) with Pydantic v2
- Format & version detection for DA XML 2.0–3.3
- Pre-parse encoding repair via ftfy + charset-normalizer
- Malformed XML recovery with two-pass strategy
- DA XML 3.x parser (3.0, 3.1, 3.2, 3.3)
- DA XML 2.x parser (2.0, 2.1) via German element mapping
- OZ resolver with BoQBkdn hierarchy breakdown
- Rich text parser for tgBoQText long texts (BeautifulSoup4 + lxml)
- Structural, item, numeric, and phase validation
- Cross-phase validation (source ↔ response compatibility)
- LLM classification via LiteLLM (100+ providers) + instructor (structured output)
- Async batch classifier with SQLite cache, deduplication, cost preview
- Sync convenience wrapper for classification
- Model fallback chains
- Progress reporting callbacks
- Manual override support with cache persistence
- Prompt versioning (v1)
- GAEB XML writer with round-trip support
- JSON and CSV export
- Multi-lot document navigation
- Configuration via pydantic-settings (env vars / .env)
- Comprehensive validation with lenient (default) and strict modes
