# Guides

In-depth guides for every pyGAEB capability.

- **[Parsing](parsing.md)** — version detection, encoding repair, error recovery
- **[Trade Phases](trade-phases.md)** — working with X93–X97 trade orders (supplier/contractor workflows)
- **[Cost & Calculation Phases](cost-phases.md)** — working with X50–X52 cost estimation, elemental costing, BIM integration
- **[Quantity Determination](quantity-phases.md)** — working with X31 quantity take-off data, REB 23.003 measurements, catalog assignments
- **[Validation](validation.md)** — lenient vs strict mode, phase rules, cross-phase checks
- **[LLM Classification](classification.md)** — taxonomy, confidence flags, cost estimation, caching
- **[Structured Extraction](extraction.md)** — custom Pydantic schemas, built-in specs, batch extraction
- **[Version Conversion](conversion.md)** — convert between DA XML 2.0–3.3, upgrade/downgrade, reports
- **[Custom & Vendor Tags](custom-tags.md)** — raw XML access, XPath queries, vendor extensions
- **[Writing & Export](writing.md)** — round-trip editing, phase override, JSON/CSV export
- **[Caching](caching.md)** — in-memory, SQLite, and custom cache backends
- **[Tree Navigation](tree-navigation.md)** — BoQTree adapter with parent references, sibling navigation, depth tracking, and subtree queries
- **[Document Diff](document-diff.md)** — compare two GAEB documents with significance-classified field changes, structural diff, and financial impact
- **[BoQ Builder](builder.md)** — programmatic document construction with auto OZ, Decimal convenience, phase rules, and version checks
