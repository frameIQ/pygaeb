# Changelog

All notable changes to pyGAEB are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.0]: https://github.com/frameiq/pygaeb/releases/tag/v1.0.0
