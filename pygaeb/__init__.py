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

__version__ = "1.5.0"

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
        # Validation
        "CrossPhaseValidator": ("pygaeb.validation.cross_phase_validator", "CrossPhaseValidator"),
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
        # Quantity determination models (X31)
        "QtyDetermination": ("pygaeb.models.quantity", "QtyDetermination"),
        "QtyDetermInfo": ("pygaeb.models.quantity", "QtyDetermInfo"),
        "QtyBoQ": ("pygaeb.models.quantity", "QtyBoQ"),
        "QtyBoQBody": ("pygaeb.models.quantity", "QtyBoQBody"),
        "QtyBoQCtgy": ("pygaeb.models.quantity", "QtyBoQCtgy"),
        "QtyItem": ("pygaeb.models.quantity", "QtyItem"),
        "QDetermItem": ("pygaeb.models.quantity", "QDetermItem"),
        "QTakeoffRow": ("pygaeb.models.quantity", "QTakeoffRow"),
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
    "BkdnType",
    "BoQ",
    "BoQBkdn",
    "BoQBody",
    "BoQCtgy",
    "BoQCtgyRef",
    "BoQInfo",
    "BoQItemRef",
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
    "DimensionElement",
    "DimensionElementRef",
    "DocumentAPI",
    "DocumentKind",
    "ECBkdn",
    "ECBody",
    "ECCtgy",
    "ECInfo",
    "ElementalCosting",
    "ExchangePhase",
    "ExtractionResult",
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
    "ItemType",
    "LLMClassifier",
    "Lot",
    "MarkupSubQty",
    "OrderInfo",
    "OrderItem",
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
    "RefGroup",
    "RichText",
    "SQLiteCache",
    "SourceVersion",
    "StructuredExtractor",
    "SupplierInfo",
    "Totals",
    "TradeOrder",
    "VATPart",
    "ValidationMode",
    "ValidationResult",
    "ValidationSeverity",
    "__version__",
    "configure",
    "get_settings",
]
