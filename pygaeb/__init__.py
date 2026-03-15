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

__version__ = "1.2.0"

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
    "BoQInfo",
    "CacheBackend",
    "ClassificationBackendError",
    "ClassificationFlag",
    "ClassificationResult",
    "ConversionReport",
    "CostEstimate",
    "CrossPhaseValidator",
    "CustomerInfo",
    "DeliveryPlaceInfo",
    "DocumentAPI",
    "DocumentKind",
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
    "OrderInfo",
    "OrderItem",
    "PlannerInfo",
    "PyGAEBError",
    "PyGAEBSettings",
    "QtySplit",
    "RichText",
    "SQLiteCache",
    "SourceVersion",
    "StructuredExtractor",
    "SupplierInfo",
    "TradeOrder",
    "ValidationMode",
    "ValidationResult",
    "ValidationSeverity",
    "__version__",
    "configure",
    "get_settings",
]
