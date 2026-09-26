"""Item-level domain models: Item, QtySplit, RichText, Attachment, classification."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.enums import (
    ClassificationFlag,
    ComplementKind,
    ItemType,
    Provis,
    ValidationSeverity,
)


class QtySplit(BaseModel):
    """Partial quantity breakdown (e.g., by building section, floor, or time period)."""

    label: str
    qty: Decimal
    unit: str | None = None


_QUOTES = "'\"‚‘’„“”"  # noqa: RUF001 — the German quote marks are the point
_NUMBER_RE = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_PUNCTUATION_AFTER = ",.;:!?)"


def join_inline(left: str, right: str) -> str:
    """Two pieces of one sentence, with the space a reader would expect between them.

    No space when either side already brings its own, or when the right side opens
    with punctuation that belongs to the left.
    """
    if not left or not right:
        return left + right
    if left[-1].isspace() or right[0].isspace() or right[0] in _PUNCTUATION_AFTER:
        return left + right
    return f"{left} {right}"


class TextComplement(BaseModel):
    """A field inside a long text — ``<TextComplement>``.

    Standard texts leave gaps in the prose. The issuer fills its own
    (``Stoff 'Beton C25/30'``) and the bidder answers in paired ones
    (``Stoff '....'``), typically naming the product it offers in place of a lead
    product. ``body`` is kept as written, quote marks included, because they are
    part of the text; :attr:`value` is the entry without them.
    """

    kind: ComplementKind
    mark: str = ""
    """``MarkLbl`` — the field's number within its text, which is how a bid refers to it."""
    caption: str = ""
    body: str = ""
    """As written, e.g. ``'Beton C25/30'``. Empty when nothing has been filled in."""
    tail: str = ""
    empty: bool = False
    number: Decimal | None = None
    """``ComplBodyDec``/``ComplBodyInt`` ``Value`` — for a field that takes a number."""
    number_kind: Literal["dec", "int"] | None = None
    id: str | None = None
    art_chr_ident: str | None = None
    context: str = ""
    """The words just before the field — ``Angebotenes Fabrikat`` in
    ``Angebotenes Fabrikat: '....'`` — which is what labels a field that has no
    caption of its own. Read from the prose, not stored in the file."""

    @property
    def label(self) -> str:
        """The caption, or the words before the field when it has none."""
        return self.caption or self.context

    @property
    def value(self) -> str:
        """The entry without its enclosing quote marks; empty for an empty field."""
        if self.empty:
            return ""
        text = self.body.strip()
        if len(text) >= 2 and text[0] in _QUOTES and text[-1] in _QUOTES:
            text = text[1:-1].strip()
        return text

    @property
    def inline(self) -> str:
        """How the field reads inside the prose. An empty one reads ``'…'``."""
        body = "'…'" if self.empty or not self.body else self.body
        return join_inline(join_inline(self.caption, body), self.tail)

    def fill(self, text: str) -> None:
        """Answer a bidder field. An issuer's field is not the bidder's to fill."""
        if self.kind != ComplementKind.BIDDER:
            raise ValueError(f"Field {self.mark} is the issuer's, not the bidder's.")
        entry = text.strip()
        self.body = entry
        self.empty = not entry
        self.number = _as_number(entry, self.number_kind) if entry else None


def _as_number(text: str, kind: str | None) -> Decimal | None:
    """The entry as a number, when the field takes one and the entry is one.

    Deliberately strict — ``80`` or ``0,5`` — because a grouping separator is
    ambiguous between German and English and a wrong ``Value`` is worse than none.
    """
    if kind is None or not _NUMBER_RE.fullmatch(text):
        return None
    try:
        number = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None
    if kind == "int" and number != number.to_integral_value():
        return None
    return number


class RichText(BaseModel):
    """Parsed long text with structural elements."""

    paragraphs: list[str] = Field(default_factory=list)
    tables: list[list[list[str]]] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    raw_html: str | None = None
    plain_text: str = ""
    complements: list[TextComplement] = Field(default_factory=list)
    """The fields in the text, in document order. Rendered inline in ``paragraphs``
    and ``plain_text`` too, so the prose reads as the issuer wrote it."""

    @classmethod
    def from_plain(cls, text: str) -> RichText:
        return cls(paragraphs=[text] if text else [], plain_text=text)

    def fill_bidder(self, mark: str, text: str) -> int:
        """Answer the bidder field numbered *mark*; returns how many fields took it."""
        filled = 0
        for complement in self.complements:
            if complement.kind == ComplementKind.BIDDER and complement.mark == mark:
                complement.fill(text)
                filled += 1
        return filled


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
    """Reference to an item being marked up (``<MarkupSubQty>``)."""

    ref_rno: str = ""
    #: ``RefItem/@IDRef`` — the referenced item's ``@ID``; resolved from
    #: ``ref_rno`` on write when absent.
    ref_id: str | None = None
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
    sorting bidders by total price (1 = lowest). ``affects_total`` mirrors
    the item type: alternative and eventual positions are priced but do not
    count toward a bidder's grand total.
    """

    bidder_name: str = ""
    bidder_id: str | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    affects_total: bool = True
    rank: int | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)


class Item(BaseModel):
    """A single item (position) in a procurement Bill of Quantities (X80-X89).

    Inherits text, quantity, and LLM fields; adds procurement-specific
    pricing, hierarchy, and attachment support.
    """

    model_config = {"arbitrary_types_allowed": True}

    def __repr__(self) -> str:
        parts = [f"oz={self.full_oz!r}"]
        if self.short_text:
            text = self.short_text[:40] + ("..." if len(self.short_text) > 40 else "")
            parts.append(f"text={text!r}")
        if self.total_price is not None:
            parts.append(f"total={self.total_price}")
        return f"Item({', '.join(parts)})"

    #: Source ``@ID`` (xs:ID); the writer generates one when absent.
    id: str | None = None
    oz: str = ""
    #: ``@RNoIndex`` — index suffix (e.g. "A") distinguishing sibling items.
    rno_index: str | None = None
    oz_path: list[str] = Field(default_factory=list)
    short_text: str = ""
    long_text: RichText | None = None
    qty: Decimal | None = None
    # <QtyTBD>: quantity still to be determined, so a missing qty is deliberate.
    qty_tbd: bool = False
    unit: str | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    item_type: ItemType = ItemType.NORMAL
    #: ``<Provis>`` value for EVENTUAL items; None when the source left it unsaid.
    provis: Provis | None = None
    qty_splits: list[QtySplit] = Field(default_factory=list)
    hierarchy_path: list[str] = Field(default_factory=list)
    lot_label: str | None = None
    classification: ClassificationResult | None = None
    extractions: dict[str, ExtractionResult] = Field(default_factory=dict)
    attachments: list[Attachment] = Field(default_factory=list)
    bim_guid: str | None = None
    change_order_number: str | None = None
    #: ``<COStatus>`` — the schema only allows CONo together with it.
    co_status: str | None = None
    cost_approaches: list[CostApproach] = Field(default_factory=list)
    #: ``<UPBkdn>`` — the issuer requires this position's unit price broken down
    #: into its components. In German public procurement that is what feeds
    #: EFB 223 (Aufgliederung der Einheitspreise), so a bidder needs to know which
    #: positions carry it. Declared by the issuer in X81/X82/X83/X85/X86; X84 has
    #: no such element, because a bid does not restate the demand.
    up_breakdown_required: bool = False
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

    @property
    def full_oz(self) -> str:
        """The complete ordinal number (Ordnungszahl), e.g. ``"01.02.0004"``.

        Joins the ancestor category/lot ``RNoPart`` chain (``oz_path``) with
        this item's own leaf ``oz`` using ``.`` as the separator. Falls back to
        the bare ``oz`` when no ancestor chain is available (e.g. items built
        programmatically). Use :meth:`full_oz_with` for a custom separator.
        """
        return self.full_oz_with(".")

    def full_oz_with(self, separator: str = ".") -> str:
        """Like :attr:`full_oz` but with a caller-chosen *separator*."""
        if self.oz_path:
            return separator.join([*self.oz_path, self.oz])
        return self.oz
