# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.16.2] - 2026-08-13

Follow-up to 1.16.1: the same silent-data-loss shape, audited across the other
document kinds. Content held without its expected wrapper element, or split
across sibling wrappers, was being dropped.

### Fixed

- **Quantity determination (X31) dropped items split across sibling `Itemlist` elements.** `_parse_qty_body` and `_parse_qty_ctgy` located the item list with `_find`, which returns only the first match, so a body or category holding several `<Itemlist>` siblings kept the first and silently lost the rest — on the path that feeds billing. Both now use `_findall`. `CtlgAttachment` was reading only its first container for the same reason and is now read repeatably too.
- **Elemental costing (X50/X51) dropped cost elements held directly by a category.** `_parse_ec_ctgy` read its contents only through an `<ECBody>` wrapper, so a `<CostElement>` sitting directly under an `<ECCtgy>` was lost entirely — the exact shape of the BoQ defect in [#27](https://github.com/frameIQ/pygaeb/issues/27), one document kind over. The category now falls back to reading its own children, mirroring what the BoQ parser already did.
- **Only the first body element was read under a category, in both the BoQ and cost hierarchies.** 1.14.1 fixed the *writer*, which until then emitted one `BoQBody` per subcategory, but the reader was never fixed — so files written by pyGAEB ≤1.14.0 still loaded with everything after the first body missing. `BoQCtgy` and `ECCtgy` now read every sibling body and merge them in document order. A category with no content still parses to `body=None`, so the writer does not start emitting empty wrappers.
- Trade (X93–X97) was audited for the same pattern and has none — it reads a flat `<OrderItem>` list with no wrapper nesting. `BillElement` in the cost parser looks like the pattern but is a boolean flag, and is correctly read with `_find`.
- New tests in `tests/test_qty_sibling_itemlists.py` and `tests/test_body_wrapper_tolerance.py` cover both hierarchies across wrapper-less, single-wrapper, and multi-wrapper shapes.

## [1.16.1] - 2026-08-13

### Fixed

- **A BoQ whose items sit directly under `BoQBody` parsed to zero items** ([#27](https://github.com/frameIQ/pygaeb/issues/27)). The GAEB schema allows an `Itemlist` as a direct child of `BoQBody`, without a `BoQCtgy` wrapper, but `_parse_boq_body` only iterated `BoQCtgy` children — so those files parsed "successfully" into an empty BoQ and every item was silently dropped, taking totals, tree, Excel export, and the writer with them. Reported against a real tender corpus (1 of 3 sampled DA XML 3.2 files). The body now also reads loose `Itemlist`/`Item`/`MarkupItem` children, using the same logic `_parse_ctgy` already applied one level down. Loose items are wrapped in an anonymous `BoQCtgy` so consumers keep a single `body.categories` traversal, and the writer unwraps it again rather than inventing a category level the source never had — matching what `_add_qty_boq_body` already did on the quantity side.
- **A DA XML 3.2 breakdown declaring a single level was read as the 3.3 format.** `BoQInfo` chose the breakdown parser by *counting* `BoQBkdn` elements, so a lone 3.2 `<BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn>` fell through to the 3.3 branch, which read its `<Type>`/`<Length>` children as level definitions. The result was junk levels of length 0, no Item level, a spurious `expected exactly 1 Item level, found 0` warning, and — because `BoQBkdn` lengths drive OZ segmentation — wrong OZ resolution. Detection is now by shape: 3.2 spells a level as `Type`/`Length` children, 3.3 as `<Item Length="4"/>`. Breakdown shapes that already parsed correctly are unchanged.
- **Only the first `BoQBkdn` element was read in the 3.3 branch.** DA XML 2.x translates each `<LVGliederung>` into its own `<BoQBkdn>`, so a 2.x file that split its levels across sibling elements lost all but the first. All elements are now read. `V2Parser` inherits this path, so 2.0/2.1 files are affected alongside 3.x.
- New regression tests (`tests/test_bare_itemlist_issue27.py`) cover both defects, the reporter's verbatim file, the DA XML 2.x German equivalent, and writer round-trip shape — asserting that a bare `Itemlist` does not gain a category on write and that a real category still keeps one.

## [1.16.0] - 2026-07-22

### Fixed

- **Position type lost on write — a €50,000 bid could export as €121,000.** `_add_item` never serialized `Item.item_type`, so every Bedarfs-/Alternativ-/Zuschlags-/Textposition was written as a Normalposition and its price silently joined the sum on re-read. The writer now emits the position-type marker (real `<Provis>` for Bedarfsposition/Eventual, real `<LumpSumItem>` for Pauschalposition; other non-standard types via a pyGAEB-internal marker **with a warning** that it is not yet interoperable). Blast radius was every written phase — X84 bid export, X86 contract, X83 tender issue.
- **Parser read no real GAEB position-type markers.** `_detect_item_type` recognised only pyGAEB-internal names (`<AlternativeItem/>`, `<ContingencyItem/>`, `<ItemTag>…`) that no real exporter emits, so a genuine tender's `<Provis>` Bedarfspositionen were mis-read as Normal on import. It now reads the real `tgItem` markers (`<Provis>`, `<LumpSumItem>`, …) **in addition to** the legacy synthetic forms. Parser and writer now share one mapping table (`pygaeb/models/position_types.py`, documented in `docs/reference/position-types.md`) so they cannot drift again.
- **`qty_splits` never serialized** — the partial-quantity breakdown (`QtySplit`) parsed into `Item.qty_splits` was dropped on write. Now round-trips symmetrically.
- **Long text corrupted and compounded on round trip.** The parser stored the wrapping `<LongText>` tag inside `raw_html` and the writer re-wrapped it, nesting one layer deeper each round trip; plaintext long texts (no `raw_html`) were dropped entirely. The parser now stores inner content only, the writer wraps exactly once and falls back to `plain_text`/`paragraphs`, so long text is stable across repeated round trips.
- New field-level round-trip tests (`tests/test_position_type_roundtrip.py`) assert per-item `item_type`, sum inclusion, `qty_splits`, and long-text stability — the pre-existing round-trip test asserted only item *count* and passed while all four defects fired.

## [1.15.0] - 2026-07-17

### Added

- **MCP server** — `pip install pyGAEB[mcp]` and `pygaeb-mcp --root ~/tenders` exposes GAEB documents to any [Model Context Protocol](https://modelcontextprotocol.io) client (ChatGPT, Gemini, Claude, Copilot, Cursor, …). MCP is a vendor-neutral standard stewarded by the Agentic AI Foundation; the server calls no model itself and adds no provider dependency or API key. It runs as a local subprocess over stdio — there is nothing to host.
- **Nine read tools** — `open_document`, `list_structure`, `list_items`, `get_item`, `get_item_long_text`, `search_items`, `list_validation_issues`, `compare_documents`, `analyze_bids`. Two more (`export_document`, `convert_document`) are registered only under `--allow-write`, which also requires `--output-dir`.
- **Context-safety contract** — a GAEB tender serialized whole is megabytes, so the tool surface is query-oriented rather than dump-oriented. Attachment bytes, `raw_data`, and whole-document JSON are structurally unreachable; `short_text` (120 chars), `long_text_preview` (500), and validation messages (200) are clipped with their true lengths reported; every list is paginated with `total_matched` and `has_more`; and responses are capped at `PYGAEB_MCP_MAX_RESPONSE_CHARS` (default 20 000). `list_items(sort="total_desc", limit=20)` answers "where is the money?" on a 5 000-item tender in ~2 KB.
- **VOB/A-conform sums** — `list_items.sum_of_matched_totals` follows the library's `ItemType.affects_total` convention: alternative and eventual positions are excluded, matching `grand_total`, and each item row carries an `affects_total` field so a model can see which prices count toward the contract value.
- **Event-loop safety** — the heavy tools (`open_document`, `search_items`, `compare_documents`, `analyze_bids`, and both write tools) are async and run their expensive work in a worker thread via `asyncio.to_thread`, so parsing a 50 MB file cannot stall protocol heartbeats or, over HTTP, other sessions. Diff results are cached per document pair, so paging through `compare_documents` never re-runs the diff engine.
- **MCP tool annotations** — every tool declares `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`, so clients can skip confirmation prompts for the nine read-only tools and confirm only the write tools.
- **Document handles** — `open_document` parses once and returns a handle derived from path, mtime, size, and validation mode. Re-opening an unchanged file is free and returns the same handle; a changed file yields a new one, so stale reads are impossible. The LRU cache is bounded by both document count and total megabytes.
- **Filesystem safety** — `open_document` is the only path-taking read tool. Paths are resolved before the roots-containment check (so symlink escapes are caught), checked against a GAEB extension allowlist, and size-checked before any bytes are read. Writes are off by default.
- **Three MCP prompts** — `tender_review`, `compare_tenders`, `bid_evaluation`.
- New settings: `mcp_roots`, `mcp_allow_write`, `mcp_output_dir`, `mcp_max_open_documents`, `mcp_max_cache_mb`, `mcp_max_page_size`, `mcp_max_response_chars` (all `PYGAEB_MCP_*`).
- New export: `create_server` (top-level lazy import). Only `pygaeb.mcp.server` imports the MCP SDK, and that import is function-local — so `import pygaeb` never pulls it in, and the tool surface is unit-testable without it.
- 79 new tests covering path safety, handle derivation and eviction, every tool, cross-kind tolerance, VOB-conform summation, event-loop safety, tool annotations, write gating, the import guard, and the context-budget contract. Total test count: 1152.

### Changed

- **Dropped Python 3.9 support**; `requires-python` is now `>=3.10`. Python 3.9 reached end of life in October 2025, and the MCP SDK requires 3.10+. The `eval_type_backport` dependency (3.9-only) has been removed, and the CI matrix, ruff target, and mypy target now start at 3.10.
- **Modernised dependency floors** (`lxml>=5.0`, `pydantic-settings>=2.5`, `litellm>=1.61`, `click>=8.1`). These were stale enough that a fresh install pulled transitive dependencies flagged by security scanners. pyGAEB itself is not affected by the advisories against those older versions — see the new [SECURITY.md](SECURITY.md) for the per-CVE non-exposure rationale (lxml's XXE is in the default parser pyGAEB never uses; litellm's CVEs are all in its proxy server, which pyGAEB doesn't run).

### Security

- **Added [SECURITY.md](SECURITY.md)** — disclosure process, threat model, hardening summary, and a dependency non-exposure table for the notable litellm / lxml / pydantic-settings advisories.
- **MCP server input hardening** — `list_items` price filters now reject non-finite values (`NaN`/`±inf`) with a clear error instead of letting `NaN` poison downstream `Decimal` comparisons.
- **MCP HTTP transport warning** — the guide now states explicitly that `sse`/`streamable-http` carry no authentication and must not be exposed to untrusted networks.

### Fixed

- **`AwardInfo.description` type error under Python 3.10+** — `lxml`'s `itertext()` is typed `Iterator[str | bytes]`, so joining it directly failed strict type checking. Now uses the same `str(t)` coercion idiom as `_text` elsewhere in the parser.
- **Stale README badges** — the version badge still read 1.14.0 after the 1.14.1 release; both READMEs now track the current version and the 3.10+ floor.

## [1.14.1] - 2026-07-08

### Fixed

- **Writer emitted the default namespace twice** — the `<GAEB>` root element carried `xmlns` both via lxml `nsmap` and as a literal attribute, producing malformed XML (`Attribute xmlns redefined`). Strict parsers rejected written files outright; recover-mode parsers silently truncated them. The declaration is now written exactly once. Applies to all document kinds (procurement, trade, cost).
- **Writer nested one `BoQBody` per subcategory** — per the GAEB DA XML schema a `BoQCtgy` contains a single `BoQBody` holding all sub-`BoQCtgy` elements and the `Itemlist`. The writer previously created a separate `BoQBody` per subcategory (with `Itemlist` as a direct `BoQCtgy` child), so conforming parsers — including pyGAEB's own — read back only the first subcategory of every category. Deeply structured BoQs now round-trip completely (verified against the BVBS GAEB Muster file: 28/28 items, cross-phase validation clean).

## [1.14.0] - 2026-05-26

### Added

- **`Item.full_oz`** — New property returning the complete ordinal number (e.g. `"01.02.0004"`) by joining the ancestor category/lot chain with the item's leaf `RNoPart`. Use `Item.full_oz_with(separator)` for a custom separator. Backed by the new `Item.oz_path` field (the ancestor `RNoPart` chain, populated during parsing). For multi-lot documents the lot number prefixes the OZ; programmatically built items fall back to the bare `oz`.
- **`BoQTree.find_item()` accepts full OZ** — Lookups now resolve by either the leaf `RNoPart` (`"0004"`) or the full OZ (`"01.02.0004"`).
- **CSV export `full_oz` column** — `to_csv()` now includes a `full_oz` column alongside `oz`.

### Fixed

- **Crash parsing files with XML comments (iTWO / RIB Software)** — GAEB DA XML 3.3 exports that embed `<!-- ... -->` comments inside elements no longer raise `TypeError`. lxml reports comment and processing-instruction nodes during iteration with a callable `.tag`; the v3 parser now skips these non-element nodes in `_parse_item_attachments`, `_classify_item_type`, and `_parse_bkdn_v33` (the last of which also previously produced a spurious breakdown entry per comment). Covers DA XML 2.x as well, since the 2.x parser delegates to the same base.

## [1.12.0] - 2026-04-11

### Added

- **X88 (Nachtrag/Addendum) exchange phase** — Full support for claims and variations: enum values (`X88`, `D88`), file extension detection, parser recognition, phase-specific validation (quantity, price, description required; change order number recommended), and round-trip serialization.
- **Cross-phase validation: X86→X89 (contract→invoice)** — `CrossPhaseValidator.check()` now validates that invoice unit prices match the contract exactly, flags invented invoice items, and warns on missing executed quantities.
- **Cross-phase validation: X86→X88 (contract→addendum)** — Validates that new Nachtrag items have change order numbers (CONo) for traceability, and flags contract items modified without CONo.
- **Totals validation** — New `validate_totals()` checks XML-declared totals against computed subtotals at BoQ, lot, and category levels. Also detects when alternative/eventual items are incorrectly included in totals (VOB/A compliance).
- **GAEB precision limit validation** — `validate_numerics()` now enforces GAEB Fachdokumentation limits: unit price max 10 pre-decimal digits, total price max 11, quantity max 8 pre-decimal / 3 decimal places, and max 6 unit price components per item.
- **Writer `up_frac_dig` support** — `GAEBWriter` now formats unit prices to the correct number of decimal places when `UPFracDig` is set in the document's `PrjInfo` (e.g., 3 decimals when `UPFracDig=3`).
- **Explicit cross-phase methods** — `CrossPhaseValidator.check_tender_bid()`, `.check_contract_invoice()`, and `.check_contract_addendum()` for direct invocation without auto-dispatch.
- 92 new tests covering all gap fixes and coverage improvements across classifier, extractor, version compat, detector, and validation modules. Total test count: 927.

### Fixed

- **X80 phase validation false positives** — X80 (BoQ Catalogue) no longer incorrectly warns about missing quantities. X80 is a reusable item library without quantities or prices per the GAEB standard.
- **README version badge** — Updated from 1.7.0 to 1.11.0 (both English and German).

### Security

- **SQLiteCache file permissions** — Database files are now created with `0o600` permissions and cache directories with `0o700`, restricting access to the owning user. Classification results may contain business-sensitive construction data.

## [1.11.0] - 2026-03-24

### Added

- **Excel Export** — `to_excel()` exports any GAEB document to a structured Excel workbook (.xlsx) with hierarchy-aware layout and phase-specific columns.
- **Two export modes** — `mode="structured"` for a single hierarchy-aware sheet; `mode="full"` for a multi-sheet workbook (BoQ + Items + Summary + Info).
- **All document kinds** — Procurement (X80-X89), Trade (X93-X97), Cost (X50-X52), and Quantity Determination (X31) each get phase-appropriate columns.
- **Optional columns** — `include_long_text`, `include_classification`, and `include_bim_guid` flags add extra columns on demand.
- **Minimal formatting** — Bold headers, frozen panes, auto column widths, currency/quantity number formatting, bold subtotals.
- Optional dependency: `openpyxl` via `pip install pyGAEB[excel]`.
- New export: `to_excel` (top-level lazy import and via `pygaeb.convert`).
- 34 new tests covering all 4 phases, both modes, column flags, formatting, and edge cases.

## [1.10.0] - 2026-03-24

### Added

- **BoQ Builder API** — `BoQBuilder` provides programmatic construction of GAEB documents from scratch with a fluent, explicit-object API.
- **Auto OZ generation** — Ordinal numbers auto-generated from category `rno` + sequence (10, 20, 30...) when `oz` is omitted. Explicit OZ overrides supported.
- **Decimal convenience** — `int`, `float`, and `str` values auto-converted to `Decimal` for `qty`, `unit_price`, and `total_price`. Auto-computes `total_price` when missing.
- **Field name validation** — Unknown kwargs raise `ValueError` with `difflib` suggestions for likely typos (e.g., `'unit_prce'` → `Did you mean: 'unit_price'?`).
- **Phase-aware rules** — Warns or errors (strict mode) when items violate exchange phase semantics (e.g., prices in X80 blank BoQ, missing prices in X83 tender).
- **Version compatibility checks** — Detects fields incompatible with the target DA XML version (e.g., `bim_guid` in DA XML < 3.3) with warnings or strict errors.
- **Duplicate OZ detection** — Catches duplicate ordinal numbers within a lot at build time.
- **Auto totals & BoQBkdn** — Lot subtotals computed from item prices; breakdown structure inferred from hierarchy depth.
- **Implicit lot shortcut** — `builder.add_category()` creates a single implicit lot for simple documents.
- **ItemHandle** — Fluent post-construction for long text (`.set_long_text()`) and attachments (`.add_attachment()`).
- **Optional XSD validation** — `build(xsd_dir=...)` serializes to XML in memory and validates against official GAEB XSD schemas.
- **Full writer compatibility** — Built documents work directly with `GAEBWriter.write()` and `GAEBWriter.to_bytes()`.
- New export: `BoQBuilder` (top-level lazy import).
- 46 new tests covering basic construction, multi-lot, nested categories, auto OZ, Decimal conversion, field validation, typo detection, phase rules, version compatibility, strict mode, duplicate OZ, auto totals, round-trip serialization, and edge cases.

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
