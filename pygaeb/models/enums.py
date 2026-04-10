"""Enumerations for GAEB document model."""

from __future__ import annotations

from enum import Enum


class SourceVersion(str, Enum):
    """GAEB format version detected from source file."""

    DA_XML_20 = "2.0"
    DA_XML_21 = "2.1"
    DA_XML_30 = "3.0"
    DA_XML_31 = "3.1"
    DA_XML_32 = "3.2"
    DA_XML_33 = "3.3"
    GAEB_90 = "90"


class DocumentKind(str, Enum):
    """Discriminator for procurement, trade, cost, and quantity documents."""

    PROCUREMENT = "procurement"
    TRADE = "trade"
    COST = "cost"
    QUANTITY = "quantity"


class ExchangePhase(str, Enum):
    """GAEB exchange phase — procurement, trade, and cost workflows."""

    # Cost & Calculation phases (X50-X52)
    X50 = "X50"
    X51 = "X51"
    X52 = "X52"

    # Procurement phases (X80-X89)
    X80 = "X80"
    X81 = "X81"
    X82 = "X82"
    X83 = "X83"
    X84 = "X84"
    X85 = "X85"
    X86 = "X86"
    X88 = "X88"
    X89 = "X89"
    X89B = "X89B"
    X31 = "X31"
    X83Z = "X83Z"
    X84Z = "X84Z"
    X86ZR = "X86ZR"
    X86ZE = "X86ZE"

    # Trade phases (X93-X97)
    X93 = "X93"
    X94 = "X94"
    X96 = "X96"
    X97 = "X97"

    # DA XML 2.x D-prefixed aliases
    D80 = "D80"
    D81 = "D81"
    D82 = "D82"
    D83 = "D83"
    D84 = "D84"
    D85 = "D85"
    D86 = "D86"
    D88 = "D88"
    D89 = "D89"
    D31 = "D31"

    def normalized(self) -> ExchangePhase:
        """Return the X-prefixed canonical form (D83 -> X83, etc.)."""
        return _D_TO_X_PHASE.get(self, self)

    @property
    def is_cost(self) -> bool:
        """True for cost phases (X50, X51)."""
        return self in _COST_PHASES

    @property
    def is_trade(self) -> bool:
        """True for trade phases (X93, X94, X96, X97)."""
        return self in _TRADE_PHASES

    @property
    def is_quantity(self) -> bool:
        """True for quantity determination phases (X31)."""
        return self in _QUANTITY_PHASES


_D_TO_X_PHASE: dict[ExchangePhase, ExchangePhase] = {}

_COST_PHASES: frozenset[ExchangePhase] = frozenset()
_TRADE_PHASES: frozenset[ExchangePhase] = frozenset()
_QUANTITY_PHASES: frozenset[ExchangePhase] = frozenset()


def _init_phase_map() -> None:
    global _COST_PHASES
    global _TRADE_PHASES
    global _QUANTITY_PHASES
    _D_TO_X_PHASE.update({
        ExchangePhase.D80: ExchangePhase.X80,
        ExchangePhase.D81: ExchangePhase.X81,
        ExchangePhase.D82: ExchangePhase.X82,
        ExchangePhase.D83: ExchangePhase.X83,
        ExchangePhase.D84: ExchangePhase.X84,
        ExchangePhase.D85: ExchangePhase.X85,
        ExchangePhase.D86: ExchangePhase.X86,
        ExchangePhase.D88: ExchangePhase.X88,
        ExchangePhase.D89: ExchangePhase.X89,
        ExchangePhase.D31: ExchangePhase.X31,
    })
    _COST_PHASES = frozenset({ExchangePhase.X50, ExchangePhase.X51})
    _TRADE_PHASES = frozenset({
        ExchangePhase.X93,
        ExchangePhase.X94,
        ExchangePhase.X96,
        ExchangePhase.X97,
    })
    _QUANTITY_PHASES = frozenset({ExchangePhase.X31})


_init_phase_map()


class ItemType(str, Enum):
    """Item type classification within a BoQ."""

    NORMAL = "Normal"
    LUMP_SUM = "LumpSum"
    ALTERNATIVE = "Alternative"
    EVENTUAL = "Eventual"
    TEXT_ONLY = "TextOnly"
    BASE_SURCHARGE = "BaseSurcharge"
    INDEX = "Index"
    SUPPLEMENT = "Supplement"
    MARKUP = "Markup"

    @property
    def affects_total(self) -> bool:
        return self in (
            ItemType.NORMAL,
            ItemType.LUMP_SUM,
            ItemType.SUPPLEMENT,
        )


class BkdnType(str, Enum):
    """BoQ breakdown level type."""

    LOT = "Lot"
    BOQ_LEVEL = "BoQLevel"
    ITEM = "Item"
    INDEX = "Index"


class ValidationSeverity(str, Enum):
    """Severity level for validation results."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ValidationMode(str, Enum):
    """Validation strictness mode."""

    LENIENT = "lenient"
    STRICT = "strict"


class ClassificationFlag(str, Enum):
    """Classification confidence flags."""

    AUTO_CLASSIFIED = "auto-classified"
    NEEDS_SPOT_CHECK = "needs-spot-check"
    NEEDS_REVIEW = "needs-review"
    LLM_ERROR = "llm-error"
    MANUAL_OVERRIDE = "manual-override"
