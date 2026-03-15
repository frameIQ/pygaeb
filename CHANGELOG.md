# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
