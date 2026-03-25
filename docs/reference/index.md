# API Reference

Complete reference documentation for all public classes, functions, and enums in pyGAEB. Auto-generated from source code docstrings.

## Core

- **[GAEBParser](parser.md)** — parse GAEB files from disk, bytes, or strings
- **[Models](models.md)** — `GAEBDocument`, `Item`, `BoQ`, enums, and all data classes
- **[Writer & Export](writer.md)** — `GAEBWriter`, JSON export, CSV export

## LLM Features

- **[Classifier](classifier.md)** — `LLMClassifier`, taxonomy, confidence scoring
- **[Extractor](extractor.md)** — `StructuredExtractor`, built-in schemas, extraction utilities

## Infrastructure

- **[Cache](cache.md)** — `CacheBackend` protocol, `InMemoryCache`, `SQLiteCache`
- **[Validation](validation.md)** — `CrossPhaseValidator`, validation result types
- **[Configuration](config.md)** — `PyGAEBSettings`, `configure()`, `get_settings()`
- **[BoQ Tree](boq-tree.md)** — `BoQTree`, `BoQNode`, `NodeKind`
- **[Document Diff](document-diff.md)** — `BoQDiff`, `DiffResult`, `Significance`, `DiffMode`
- **[BoQ Builder](builder.md)** — `BoQBuilder`, `LotBuilder`, `CategoryBuilder`, `ItemHandle`
- **[Exceptions](exceptions.md)** — exception hierarchy
