"""BaseItem — shared fields for both procurement items and trade order items."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.item import ClassificationResult, ExtractionResult, RichText


class BaseItem(BaseModel):
    """Shared text, quantity, and LLM fields inherited by both Item and OrderItem.

    This base class carries everything needed for universal iteration,
    LLM classification, and structured extraction regardless of whether
    the document is a procurement BoQ or a trade order.
    """

    model_config = {"arbitrary_types_allowed": True}

    short_text: str = ""
    long_text: RichText | None = None
    qty: Decimal | None = None
    unit: str | None = None
    classification: ClassificationResult | None = None
    extractions: dict[str, ExtractionResult] = Field(default_factory=dict)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    @property
    def long_text_plain(self) -> str:
        if self.long_text:
            return self.long_text.plain_text
        return ""
