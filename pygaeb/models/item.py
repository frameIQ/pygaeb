"""Item-level domain models: Item, QtySplit, RichText, Attachment, classification."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.enums import ClassificationFlag, ItemType, ValidationSeverity


class QtySplit(BaseModel):
    """Partial quantity breakdown (e.g., by building section, floor, or time period)."""

    label: str
    qty: Decimal
    unit: str | None = None


class RichText(BaseModel):
    """Parsed long text with structural elements."""

    paragraphs: list[str] = Field(default_factory=list)
    tables: list[list[list[str]]] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    raw_html: str | None = None
    plain_text: str = ""

    @classmethod
    def from_plain(cls, text: str) -> RichText:
        return cls(paragraphs=[text] if text else [], plain_text=text)


class Attachment(BaseModel):
    """Base64-decoded binary content from X31 (DA XML 3.3)."""

    model_config = {"arbitrary_types_allowed": True}

    filename: str
    mime_type: str
    data: bytes
    size_bytes: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.size_bytes == 0:
            object.__setattr__(self, "size_bytes", len(self.data))


class ClassificationResult(BaseModel):
    """Semantic construction element classification result."""

    trade: str = ""
    element_type: str = ""
    sub_type: str = ""
    confidence: float = 0.0
    flag: ClassificationFlag = ClassificationFlag.AUTO_CLASSIFIED
    ifc_type: str | None = None
    din276_code: str | None = None
    cached: bool = False
    prompt_version: str = "v1"

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class CostEstimate(BaseModel):
    """Estimated cost for LLM classification of a document."""

    total_items: int = 0
    cached_items: int = 0
    duplicate_items: int = 0
    items_to_classify: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    estimated_duration_s: float = 0.0
    model: str = ""


class ValidationResult(BaseModel):
    """A single validation issue found during parsing or validation."""

    severity: ValidationSeverity
    message: str
    xpath_location: str | None = None
    version_specific: bool = False


class ExtractionResult(BaseModel):
    """Result of structured extraction for a single item."""

    schema_name: str = ""
    schema_hash: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    completeness: float = 0.0
    cached: bool = False

    @field_validator("completeness")
    @classmethod
    def clamp_completeness(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class MarkupSubQty(BaseModel):
    """Reference to an item being marked up (X52 ``<MarkupSubQty>``)."""

    ref_rno: str = ""
    sub_qty: Decimal | None = None


class CostApproach(BaseModel):
    """Per-item calculation approach (X52 Kalkulationsansätze)."""

    cost_type: str = ""
    amount: Decimal | None = None
    remark: str = ""
    source_element: Any = Field(default=None, exclude=True, repr=False)


class BidderPrice(BaseModel):
    """A single bidder's price for an item in a Preisspiegel (X82).

    GAEB X82 carries multiple bidder prices per item for tender comparison.
    Each ``BidderPrice`` represents one bidder's submitted price.

    The optional ``rank`` field is populated by ``BidAnalysis`` after
    sorting bidders by total price (1 = lowest).
    """

    bidder_name: str = ""
    bidder_id: str | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    rank: int | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)


class Item(BaseModel):
    """A single item (position) in a procurement Bill of Quantities (X80-X89).

    Inherits text, quantity, and LLM fields; adds procurement-specific
    pricing, hierarchy, and attachment support.
    """

    model_config = {"arbitrary_types_allowed": True}

    def __repr__(self) -> str:
        parts = [f"oz={self.oz!r}"]
        if self.short_text:
            text = self.short_text[:40] + ("..." if len(self.short_text) > 40 else "")
            parts.append(f"text={text!r}")
        if self.total_price is not None:
            parts.append(f"total={self.total_price}")
        return f"Item({', '.join(parts)})"

    oz: str = ""
    short_text: str = ""
    long_text: RichText | None = None
    qty: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    item_type: ItemType = ItemType.NORMAL
    qty_splits: list[QtySplit] = Field(default_factory=list)
    hierarchy_path: list[str] = Field(default_factory=list)
    lot_label: str | None = None
    classification: ClassificationResult | None = None
    extractions: dict[str, ExtractionResult] = Field(default_factory=dict)
    attachments: list[Attachment] = Field(default_factory=list)
    bim_guid: str | None = None
    change_order_number: str | None = None
    cost_approaches: list[CostApproach] = Field(default_factory=list)
    up_components: list[Decimal] = Field(default_factory=list)
    discount_pct: Decimal | None = None
    vat: Decimal | None = None
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    markup_type: str | None = None
    markup_sub_qtys: list[MarkupSubQty] = Field(default_factory=list)
    bidder_prices: list[BidderPrice] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)
    raw_data: dict[str, Any] | None = Field(default=None, exclude=True)

    @property
    def computed_total(self) -> Decimal | None:
        """qty x unit_price, rounded to 2 decimal places (ROUND_HALF_UP)."""
        if self.qty is not None and self.unit_price is not None:
            return (self.qty * self.unit_price).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return None

    @property
    def has_rounding_discrepancy(self) -> bool:
        if self.total_price is not None and self.computed_total is not None:
            return abs(self.total_price - self.computed_total) > Decimal("0.01")
        return False

    @property
    def has_attachments(self) -> bool:
        return len(self.attachments) > 0

    @property
    def long_text_plain(self) -> str:
        if self.long_text:
            return self.long_text.plain_text
        return ""

    @property
    def hierarchy_path_str(self) -> str:
        return " > ".join(self.hierarchy_path)
