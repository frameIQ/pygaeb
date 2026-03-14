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

__version__ = "1.0.0"

from pygaeb.exceptions import (
    ClassificationBackendError,
    GAEBParseError,
    GAEBValidationError,
    PyGAEBError,
)
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import (
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
    "Attachment",
    # Models (lazy — available but not prominent)
    "AwardInfo",
    # Enums (lazy)
    "BkdnType",
    "BoQ",
    "BoQBkdn",
    "BoQBody",
    "BoQCtgy",
    "BoQInfo",
    # Cache (lazy)
    "CacheBackend",
    # Exceptions
    "ClassificationBackendError",
    "ClassificationFlag",
    "ClassificationResult",
    "CostEstimate",
    # Validation (lazy)
    "CrossPhaseValidator",
    # Navigation (lazy)
    "DocumentAPI",
    "ExchangePhase",
    "ExtractionResult",
    "GAEBDocument",
    "GAEBInfo",
    "GAEBParseError",
    "GAEBParser",
    "GAEBValidationError",
    "GAEBWriter",
    "InMemoryCache",
    "Item",
    "ItemType",
    # LLM (lazy)
    "LLMClassifier",
    "Lot",
    "PyGAEBError",
    # Config (lazy)
    "PyGAEBSettings",
    "QtySplit",
    "RichText",
    "SQLiteCache",
    "SourceVersion",
    "StructuredExtractor",
    "ValidationMode",
    "ValidationResult",
    "ValidationSeverity",
    # Core — the 80% API
    "__version__",
    "configure",
    "get_settings",
]
