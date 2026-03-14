# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
