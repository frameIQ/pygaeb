"""pyGAEB — Python parser for GAEB DA XML construction data exchange files.

Multi-version GAEB DA XML parser · LLM-powered item classification ·
Provider-agnostic · MIT licensed.

Quick start:
    >>> from pygaeb import GAEBParser
    >>> doc = GAEBParser.parse("tender.X83")
    >>> for item in doc.award.boq.iter_items():
    ...     print(item.oz, item.short_text)
"""

from __future__ import annotations

__version__ = "1.13.0"

from pygaeb.exceptions import (
    ClassificationBackendError,
    GAEBParseError,
    GAEBValidationError,
    PyGAEBError,
)
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import (
    DocumentKind,
    ExchangePhase,
    ItemType,
    SourceVersion,
    ValidationMode,
)
from pygaeb.models.item import Item
from pygaeb.parser import GAEBParser
from pygaeb.writer import GAEBWriter


def __getattr__(name: str) -> object:
    """Lazy imports for optional/advanced symbols — avoids loading LLM deps at import time."""
    _lazy_map = {
        # LLM (optional dep)
        "LLMClassifier": ("pygaeb.classifier", "LLMClassifier"),
        "StructuredExtractor": ("pygaeb.extractor", "StructuredExtractor"),
        # Converter
        "GAEBConverter": ("pygaeb.converter", "GAEBConverter"),
        "ConversionReport": ("pygaeb.converter", "ConversionReport"),
        # Cache (only needed for opt-in persistence)
        "CacheBackend": ("pygaeb.cache", "CacheBackend"),
        "InMemoryCache": ("pygaeb.cache", "InMemoryCache"),
        "SQLiteCache": ("pygaeb.cache", "SQLiteCache"),
        # Config (advanced)
        "PyGAEBSettings": ("pygaeb.config", "PyGAEBSettings"),
        "configure": ("pygaeb.config", "configure"),
        "get_settings": ("pygaeb.config", "get_settings"),
        "reset_settings": ("pygaeb.config", "reset_settings"),
        # Validation
        "CrossPhaseValidator": ("pygaeb.validation.cross_phase_validator", "CrossPhaseValidator"),
        "register_validator": ("pygaeb.validation", "register_validator"),
        "clear_validators": ("pygaeb.validation", "clear_validators"),
        # Prompt registration
        "register_prompt": ("pygaeb.classifier.prompt_templates", "register_prompt"),
        # Models (advanced — most users access via doc.award.boq, not direct import)
        "AwardInfo": ("pygaeb.models.document", "AwardInfo"),
        "GAEBInfo": ("pygaeb.models.document", "GAEBInfo"),
        "Attachment": ("pygaeb.models.item", "Attachment"),
        "ClassificationResult": ("pygaeb.models.item", "ClassificationResult"),
        "CostEstimate": ("pygaeb.models.item", "CostEstimate"),
        "ExtractionResult": ("pygaeb.models.item", "ExtractionResult"),
        "QtySplit": ("pygaeb.models.item", "QtySplit"),
        "RichText": ("pygaeb.models.item", "RichText"),
        "ValidationResult": ("pygaeb.models.item", "ValidationResult"),
        "BoQ": ("pygaeb.models.boq", "BoQ"),
        "BoQBkdn": ("pygaeb.models.boq", "BoQBkdn"),
        "BoQBody": ("pygaeb.models.boq", "BoQBody"),
        "BoQCtgy": ("pygaeb.models.boq", "BoQCtgy"),
        "BoQInfo": ("pygaeb.models.boq", "BoQInfo"),
        "Lot": ("pygaeb.models.boq", "Lot"),
        "Totals": ("pygaeb.models.boq", "Totals"),
        "VATPart": ("pygaeb.models.boq", "VATPart"),
        # Trade models
        "TradeOrder": ("pygaeb.models.order", "TradeOrder"),
        "OrderItem": ("pygaeb.models.order", "OrderItem"),
        "OrderInfo": ("pygaeb.models.order", "OrderInfo"),
        "SupplierInfo": ("pygaeb.models.order", "SupplierInfo"),
        "CustomerInfo": ("pygaeb.models.order", "CustomerInfo"),
        "DeliveryPlaceInfo": ("pygaeb.models.order", "DeliveryPlaceInfo"),
        "PlannerInfo": ("pygaeb.models.order", "PlannerInfo"),
        "InvoiceInfo": ("pygaeb.models.order", "InvoiceInfo"),
        "Address": ("pygaeb.models.order", "Address"),
        # Cost models (X50/X51)
        "ElementalCosting": ("pygaeb.models.cost", "ElementalCosting"),
        "ECInfo": ("pygaeb.models.cost", "ECInfo"),
        "ECBody": ("pygaeb.models.cost", "ECBody"),
        "ECCtgy": ("pygaeb.models.cost", "ECCtgy"),
        "ECBkdn": ("pygaeb.models.cost", "ECBkdn"),
        "CostElement": ("pygaeb.models.cost", "CostElement"),
        "CostProperty": ("pygaeb.models.cost", "CostProperty"),
        "RefGroup": ("pygaeb.models.cost", "RefGroup"),
        "BoQItemRef": ("pygaeb.models.cost", "BoQItemRef"),
        "BoQCtgyRef": ("pygaeb.models.cost", "BoQCtgyRef"),
        "CostElementRef": ("pygaeb.models.cost", "CostElementRef"),
        "DimensionElement": ("pygaeb.models.cost", "DimensionElement"),
        "DimensionElementRef": ("pygaeb.models.cost", "DimensionElementRef"),
        "CategoryElement": ("pygaeb.models.cost", "CategoryElement"),
        "CategoryElementRef": ("pygaeb.models.cost", "CategoryElementRef"),
        "ConsortiumMember": ("pygaeb.models.cost", "ConsortiumMember"),
        "ConsortiumMemberRef": ("pygaeb.models.cost", "ConsortiumMemberRef"),
        # X52 cost approach / markup
        "CostApproach": ("pygaeb.models.item", "CostApproach"),
        "MarkupSubQty": ("pygaeb.models.item", "MarkupSubQty"),
        "CostType": ("pygaeb.models.boq", "CostType"),
        # X82 Preisspiegel — bidder prices and analysis
        "BidderPrice": ("pygaeb.models.item", "BidderPrice"),
        "BidAnalysis": ("pygaeb.bid_analysis", "BidAnalysis"),
        # Quality scoring
        "QualityScore": ("pygaeb.quality", "QualityScore"),
        "quality_score": ("pygaeb.quality", "quality_score"),
        # Unit normalization
        "normalize_unit": ("pygaeb.units", "normalize_unit"),
        "normalize_units_in_doc": ("pygaeb.units", "normalize_units_in_doc"),
        # Async API
        "aparse": ("pygaeb.async_api", "aparse"),
        "aparse_bytes": ("pygaeb.async_api", "aparse_bytes"),
        "awrite": ("pygaeb.async_api", "awrite"),
        # Events
        "EventType": ("pygaeb.events", "EventType"),
        "on_event": ("pygaeb.events", "on_event"),
        "off_event": ("pygaeb.events", "off_event"),
        "clear_subscribers": ("pygaeb.events", "clear_subscribers"),
        # Diff exports
        "diff_to_html": ("pygaeb.diff.exports", "diff_to_html"),
        "diff_to_excel": ("pygaeb.diff.exports", "diff_to_excel"),
        # Other exports
        "to_pdf": ("pygaeb.convert.to_pdf", "to_pdf"),
        "to_database": ("pygaeb.convert.to_database", "to_database"),
        "to_xrechnung": ("pygaeb.convert.to_xrechnung", "to_xrechnung"),
        # Quantity determination models (X31)
        "QtyDetermination": ("pygaeb.models.quantity", "QtyDetermination"),
        "QtyDetermInfo": ("pygaeb.models.quantity", "QtyDetermInfo"),
        "QtyBoQ": ("pygaeb.models.quantity", "QtyBoQ"),
        "QtyBoQBody": ("pygaeb.models.quantity", "QtyBoQBody"),
        "QtyBoQCtgy": ("pygaeb.models.quantity", "QtyBoQCtgy"),
        "QtyItem": ("pygaeb.models.quantity", "QtyItem"),
        "QDetermItem": ("pygaeb.models.quantity", "QDetermItem"),
        "QTakeoffRow": ("pygaeb.models.quantity", "QTakeoffRow"),
        "ParsedTakeoff": ("pygaeb.models.quantity", "ParsedTakeoff"),
        "QtyAttachment": ("pygaeb.models.quantity", "QtyAttachment"),
        "Catalog": ("pygaeb.models.catalog", "Catalog"),
        "CtlgAssign": ("pygaeb.models.catalog", "CtlgAssign"),
        "PrjInfoQD": ("pygaeb.models.quantity", "PrjInfoQD"),
        # Enums (advanced)
        "BkdnType": ("pygaeb.models.enums", "BkdnType"),
        "ClassificationFlag": ("pygaeb.models.enums", "ClassificationFlag"),
        "ValidationSeverity": ("pygaeb.models.enums", "ValidationSeverity"),
        # Document navigation
        "DocumentAPI": ("pygaeb.api.document_api", "DocumentAPI"),
        # Tree API
        "BoQTree": ("pygaeb.api.boq_tree", "BoQTree"),
        "BoQNode": ("pygaeb.api.boq_tree", "BoQNode"),
        "NodeKind": ("pygaeb.api.boq_tree", "NodeKind"),
        # Builder
        "BoQBuilder": ("pygaeb.builder", "BoQBuilder"),
        # Phase transitions
        "PhaseTransition": ("pygaeb.transition", "PhaseTransition"),
        # Convert
        "to_excel": ("pygaeb.convert.to_excel", "to_excel"),
        # Diff engine
        "BoQDiff": ("pygaeb.diff.boq_diff", "BoQDiff"),
        "DiffMode": ("pygaeb.diff.models", "DiffMode"),
        "DiffResult": ("pygaeb.diff.models", "DiffResult"),
        "DiffSummary": ("pygaeb.diff.models", "DiffSummary"),
        "DiffDocInfo": ("pygaeb.diff.models", "DiffDocInfo"),
        "FieldChange": ("pygaeb.diff.models", "FieldChange"),
        "ItemAdded": ("pygaeb.diff.models", "ItemAdded"),
        "ItemDiffSummary": ("pygaeb.diff.models", "ItemDiffSummary"),
        "ItemModified": ("pygaeb.diff.models", "ItemModified"),
        "ItemMoved": ("pygaeb.diff.models", "ItemMoved"),
        "ItemRemoved": ("pygaeb.diff.models", "ItemRemoved"),
        "MetadataChange": ("pygaeb.diff.models", "MetadataChange"),
        "SectionChange": ("pygaeb.diff.models", "SectionChange"),
        "SectionRenamed": ("pygaeb.diff.models", "SectionRenamed"),
        "Significance": ("pygaeb.diff.models", "Significance"),
        "StructureDiffSummary": ("pygaeb.diff.models", "StructureDiffSummary"),
    }

    if name in _lazy_map:
        module_path, attr = _lazy_map[name]
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)

    raise AttributeError(f"module 'pygaeb' has no attribute {name!r}")


__all__ = [
    "Address",
    "Attachment",
    "AwardInfo",
    "BidAnalysis",
    "BidderPrice",
    "BkdnType",
    "BoQ",
    "BoQBkdn",
    "BoQBody",
    "BoQBuilder",
    "BoQCtgy",
    "BoQCtgyRef",
    "BoQDiff",
    "BoQInfo",
    "BoQItemRef",
    "BoQNode",
    "BoQTree",
    "CacheBackend",
    "Catalog",
    "CategoryElement",
    "CategoryElementRef",
    "ClassificationBackendError",
    "ClassificationFlag",
    "ClassificationResult",
    "ConsortiumMember",
    "ConsortiumMemberRef",
    "ConversionReport",
    "CostApproach",
    "CostElement",
    "CostElementRef",
    "CostEstimate",
    "CostProperty",
    "CostType",
    "CrossPhaseValidator",
    "CtlgAssign",
    "CustomerInfo",
    "DeliveryPlaceInfo",
    "DiffDocInfo",
    "DiffMode",
    "DiffResult",
    "DiffSummary",
    "DimensionElement",
    "DimensionElementRef",
    "DocumentAPI",
    "DocumentKind",
    "ECBkdn",
    "ECBody",
    "ECCtgy",
    "ECInfo",
    "ElementalCosting",
    "EventType",
    "ExchangePhase",
    "ExtractionResult",
    "FieldChange",
    "GAEBConverter",
    "GAEBDocument",
    "GAEBInfo",
    "GAEBParseError",
    "GAEBParser",
    "GAEBValidationError",
    "GAEBWriter",
    "InMemoryCache",
    "InvoiceInfo",
    "Item",
    "ItemAdded",
    "ItemDiffSummary",
    "ItemModified",
    "ItemMoved",
    "ItemRemoved",
    "ItemType",
    "LLMClassifier",
    "Lot",
    "MarkupSubQty",
    "MetadataChange",
    "NodeKind",
    "OrderInfo",
    "OrderItem",
    "ParsedTakeoff",
    "PhaseTransition",
    "PlannerInfo",
    "PrjInfoQD",
    "PyGAEBError",
    "PyGAEBSettings",
    "QDetermItem",
    "QTakeoffRow",
    "QtyAttachment",
    "QtyBoQ",
    "QtyBoQBody",
    "QtyBoQCtgy",
    "QtyDetermInfo",
    "QtyDetermination",
    "QtyItem",
    "QtySplit",
    "QualityScore",
    "RefGroup",
    "RichText",
    "SQLiteCache",
    "SectionChange",
    "SectionRenamed",
    "Significance",
    "SourceVersion",
    "StructureDiffSummary",
    "StructuredExtractor",
    "SupplierInfo",
    "Totals",
    "TradeOrder",
    "VATPart",
    "ValidationMode",
    "ValidationResult",
    "ValidationSeverity",
    "__version__",
    "aparse",
    "aparse_bytes",
    "awrite",
    "clear_subscribers",
    "clear_validators",
    "configure",
    "diff_to_excel",
    "diff_to_html",
    "get_settings",
    "normalize_unit",
    "normalize_units_in_doc",
    "off_event",
    "on_event",
    "quality_score",
    "register_prompt",
    "register_validator",
    "reset_settings",
    "to_database",
    "to_excel",
    "to_pdf",
    "to_xrechnung",
]
