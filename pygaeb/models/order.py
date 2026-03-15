"""Trade order models for GAEB trade phases (X93-X97).

These phases use a flat ``<Order> / <OrderItem>`` structure instead of the
hierarchical ``<Award> / <BoQ> / <Item>`` used by procurement phases (X80-X89).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.item import (
    ClassificationResult,
    ExtractionResult,
    RichText,
)


class OrderItem(BaseModel):
    """A single item in a GAEB trade order (X93-X97).

    Carries the same text and LLM fields as a procurement ``Item`` so that
    ``LLMClassifier`` and ``StructuredExtractor`` work unchanged.  Adds
    trade-specific identification, pricing, and logistics fields.
    """

    model_config = {"arbitrary_types_allowed": True}

    # --- shared text / LLM fields (same interface as Item) ---
    short_text: str = ""
    long_text: RichText | None = None
    qty: Decimal | None = None
    unit: str | None = None
    classification: ClassificationResult | None = None
    extractions: dict[str, ExtractionResult] = Field(default_factory=dict)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    # --- trade-specific identification ---
    item_id: str = ""
    ean: str | None = None
    art_no: str | None = None
    art_no_id: str | None = None
    supplier_art_no: str | None = None
    supplier_art_no_id: str | None = None
    customer_art_no: str | None = None
    catalog_art_no: str | None = None
    catalog_no: str | None = None

    # --- trade-specific pricing ---
    offer_price: Decimal | None = None
    net_price: Decimal | None = None
    price_basis: Decimal | None = None
    aqu: str | None = None

    # --- trade-specific flags ---
    item_chara: str | None = None
    item_type_tag: str | None = None
    delivery_chara: str | None = None
    is_service: bool = False

    # --- logistics ---
    delivery_date: datetime | None = None
    mode_of_shipment: str | None = None

    @property
    def long_text_plain(self) -> str:
        if self.long_text:
            return self.long_text.plain_text
        return ""

    @property
    def display_price(self) -> Decimal | None:
        """Return the most relevant price: net_price if available, else offer_price."""
        return self.net_price if self.net_price is not None else self.offer_price

    def __repr__(self) -> str:
        parts: list[str] = []
        if self.art_no:
            parts.append(f"art_no={self.art_no!r}")
        if self.short_text:
            text = self.short_text[:40] + ("..." if len(self.short_text) > 40 else "")
            parts.append(f"text={text!r}")
        if self.net_price is not None:
            parts.append(f"net={self.net_price}")
        return f"OrderItem({', '.join(parts)})"


# ---------------------------------------------------------------------------
# Supporting info models
# ---------------------------------------------------------------------------

class Address(BaseModel):
    """Postal address (shared across supplier / customer / delivery place)."""

    name: str | None = None
    name2: str | None = None
    street: str | None = None
    pcode: str | None = None
    city: str | None = None
    country: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None


class OrderInfo(BaseModel):
    """Metadata on a trade order (order number, dates, references)."""

    order_no: str | None = None
    order_date: datetime | None = None
    delivery_date: datetime | None = None
    reference: str | None = None
    currency: str = "EUR"


class SupplierInfo(BaseModel):
    """Supplier (vendor) details."""

    address: Address = Field(default_factory=Address)


class CustomerInfo(BaseModel):
    """Customer (buyer) details."""

    address: Address = Field(default_factory=Address)


class DeliveryPlaceInfo(BaseModel):
    """Delivery location details."""

    address: Address = Field(default_factory=Address)


class PlannerInfo(BaseModel):
    """Planner / architect details."""

    address: Address = Field(default_factory=Address)


class InvoiceInfo(BaseModel):
    """Invoice recipient details."""

    address: Address = Field(default_factory=Address)


class TradeOrder(BaseModel):
    """Container for a GAEB trade order (X93-X97).

    Parallel to ``AwardInfo`` for procurement phases.  Contains flat order
    items instead of a hierarchical Bill of Quantities.
    """

    model_config = {"arbitrary_types_allowed": True}

    dp: str = ""
    order_info: OrderInfo | None = None
    supplier_info: SupplierInfo | None = None
    customer_info: CustomerInfo | None = None
    delivery_place_info: DeliveryPlaceInfo | None = None
    planner_info: PlannerInfo | None = None
    invoice_info: InvoiceInfo | None = None
    items: list[OrderItem] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def iter_items(self) -> Iterator[OrderItem]:
        yield from self.items

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def grand_total(self) -> Decimal:
        """Sum of net_price (or offer_price) across all items."""
        total = Decimal("0")
        for item in self.items:
            price = item.display_price
            if price is not None:
                if item.qty is not None:
                    total += price * item.qty
                else:
                    total += price
        return total

    def __repr__(self) -> str:
        return f"TradeOrder(dp={self.dp!r}, items={self.item_count})"
