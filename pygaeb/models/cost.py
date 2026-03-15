"""Elemental costing models for GAEB cost phases (X50, X51).

These phases use ``<ElementalCosting>`` with a recursive cost hierarchy
instead of the ``<Award>/<BoQ>/<Item>`` structure used by procurement.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.item import (
    ClassificationResult,
    ExtractionResult,
    RichText,
)


class CostProperty(BaseModel):
    """BIM-integrated property on a cost or dimension element."""

    name: str = ""
    label: str = ""
    arithmetic_qty_approach: str | None = None
    value_qty_approach: Decimal | None = None
    unit: str = ""
    prop_type: str | None = None
    cad_id: str | None = None


class BoQItemRef(BaseModel):
    """Reference from a cost element to a BoQ item."""

    id_ref: str = ""
    ref_type: str | None = None
    portion: Decimal | None = None


class BoQCtgyRef(BaseModel):
    """Reference from a cost element to a BoQ category."""

    id_ref: str = ""
    ref_type: str | None = None
    portion: Decimal | None = None


class CostElementRef(BaseModel):
    """Reference to another cost element."""

    id_ref: str = ""
    ref_type: str | None = None
    portion: Decimal | None = None


class DimensionElementRef(BaseModel):
    """Reference to a dimension element."""

    id_ref: str = ""
    ref_type: str | None = None
    portion: Decimal | None = None


class CategoryElementRef(BaseModel):
    """Reference to a category element."""

    id_ref: str = ""
    ref_type: str | None = None
    portion: Decimal | None = None


class ConsortiumMemberRef(BaseModel):
    """Reference to a consortium (ARGE) member."""

    id_ref: str = ""


class RefGroup(BaseModel):
    """Cross-reference group linking cost elements to BoQ items, categories, etc."""

    title: str = ""
    boq_item_refs: list[BoQItemRef] = Field(default_factory=list)
    boq_ctgy_refs: list[BoQCtgyRef] = Field(default_factory=list)
    cost_element_refs: list[CostElementRef] = Field(default_factory=list)
    dimension_element_refs: list[DimensionElementRef] = Field(default_factory=list)
    category_element_refs: list[CategoryElementRef] = Field(default_factory=list)
    consortium_member_refs: list[ConsortiumMemberRef] = Field(default_factory=list)


class DimensionElement(BaseModel):
    """Dimensional element (area, volume, length) in a cost hierarchy."""

    model_config = {"arbitrary_types_allowed": True}

    ele_no: str = ""
    description: str = ""
    cat_id: str | None = None
    remark: str = ""
    properties: list[CostProperty] = Field(default_factory=list)
    qty: Decimal | None = None
    unit: str = ""
    markup: Decimal | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)


class CategoryElement(BaseModel):
    """Category grouping element in a cost hierarchy."""

    model_config = {"arbitrary_types_allowed": True}

    ele_no: str = ""
    description: str = ""
    cat_id: str | None = None
    remark: str = ""
    properties: list[CostProperty] = Field(default_factory=list)
    markup: Decimal | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)


class CostElement(BaseModel):
    """Individual cost element — the 'item' of elemental costing documents.

    Carries the same text, quantity, and LLM fields as procurement ``Item``
    and trade ``OrderItem`` so that ``doc.iter_items()`` and LLM
    classification/extraction work universally.
    """

    model_config = {"arbitrary_types_allowed": True}

    short_text: str = ""
    long_text: RichText | None = None
    qty: Decimal | None = None
    unit: str | None = None
    classification: ClassificationResult | None = None
    extractions: dict[str, ExtractionResult] = Field(default_factory=dict)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    ele_no: str = ""
    cat_id: str | None = None
    remark: str = ""
    unit_price: Decimal | None = None
    item_total: Decimal | None = None
    markup: Decimal | None = None
    up_from: Decimal | None = None
    up_avg: Decimal | None = None
    up_to: Decimal | None = None
    is_bill_element: bool = False
    properties: list[CostProperty] = Field(default_factory=list)
    ref_groups: list[RefGroup] = Field(default_factory=list)
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    children: list[CostElement] = Field(default_factory=list)

    @property
    def long_text_plain(self) -> str:
        if self.long_text:
            return self.long_text.plain_text
        return ""

    def iter_cost_elements(self) -> Iterator[CostElement]:
        """Yield this element and all descendants (depth-first)."""
        yield self
        for child in self.children:
            yield from child.iter_cost_elements()

    @property
    def display_price(self) -> Decimal | None:
        """Best available total: explicit item_total, or qty * unit_price."""
        if self.item_total is not None:
            return self.item_total
        if self.qty is not None and self.unit_price is not None:
            return self.qty * self.unit_price
        return None

    def __repr__(self) -> str:
        parts = [f"ele_no={self.ele_no!r}"]
        if self.short_text:
            text = self.short_text[:40] + ("..." if len(self.short_text) > 40 else "")
            parts.append(f"text={text!r}")
        if self.item_total is not None:
            parts.append(f"total={self.item_total}")
        return f"CostElement({', '.join(parts)})"


class ECCtgy(BaseModel):
    """Cost estimation category (grouping level in the cost hierarchy)."""

    model_config = {"arbitrary_types_allowed": True}

    ele_no: str = ""
    description: str = ""
    portion: Decimal | None = None
    properties: list[CostProperty] = Field(default_factory=list)
    body: ECBody | None = None
    totals_net: Decimal | None = None
    totals_gross: Decimal | None = None
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def iter_cost_elements(self) -> Iterator[CostElement]:
        """Yield all CostElements in this category and its subcategories."""
        if self.body is not None:
            yield from self.body.iter_cost_elements()


class ECBody(BaseModel):
    """Body container for the cost hierarchy (categories + elements)."""

    categories: list[ECCtgy] = Field(default_factory=list)
    cost_elements: list[CostElement] = Field(default_factory=list)
    dimension_elements: list[DimensionElement] = Field(default_factory=list)
    category_elements: list[CategoryElement] = Field(default_factory=list)

    def iter_cost_elements(self) -> Iterator[CostElement]:
        """Yield all CostElements recursively (flat iteration)."""
        for ce in self.cost_elements:
            yield from ce.iter_cost_elements()
        for ctgy in self.categories:
            yield from ctgy.iter_cost_elements()


class ECBkdn(BaseModel):
    """Breakdown level definition for elemental costing."""

    bkdn_type: str = ""
    label: str = ""
    length: int = 0
    is_numeric: bool = False


class ConsortiumMember(BaseModel):
    """Consortium (ARGE) member with optional address."""

    description: str = ""
    name: str = ""
    street: str = ""
    pcode: str = ""
    city: str = ""
    country: str = ""


class ECInfo(BaseModel):
    """Metadata for elemental cost estimation."""

    name: str = ""
    label: str = ""
    ec_type: str | None = None
    ec_method: str | None = None
    date: datetime | None = None
    currency: str | None = None
    currency_label: str | None = None
    date_of_price: datetime | None = None
    date_of_information: datetime | None = None
    breakdowns: list[ECBkdn] = Field(default_factory=list)
    consortium_members: list[ConsortiumMember] = Field(default_factory=list)
    totals_net: Decimal | None = None
    totals_gross: Decimal | None = None


class ElementalCosting(BaseModel):
    """Root container for X50/X51 cost documents.

    Provides ``iter_items()`` yielding ``CostElement`` instances for
    universal iteration compatible with ``doc.iter_items()``.
    """

    model_config = {"arbitrary_types_allowed": True}

    dp: str = ""
    ec_info: ECInfo = Field(default_factory=ECInfo)
    body: ECBody = Field(default_factory=ECBody)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def iter_items(self) -> Iterator[CostElement]:
        """Yield all CostElements recursively (flat)."""
        yield from self.body.iter_cost_elements()

    def iter_hierarchy(self) -> Iterator[tuple[int, str, ECCtgy | None]]:
        """Walk the cost category tree yielding (depth, label, category)."""
        for ctgy in self.body.categories:
            yield from _walk_ec_ctgy(ctgy, 0)

    @property
    def item_count(self) -> int:
        return sum(1 for _ in self.iter_items())

    @property
    def grand_total(self) -> Decimal:
        total = Decimal("0")
        for ce in self.iter_items():
            if ce.item_total is not None:
                total += ce.item_total
            elif ce.is_bill_element and ce.qty is not None and ce.unit_price is not None:
                total += ce.qty * ce.unit_price
        return total

    def __repr__(self) -> str:
        count = self.item_count
        return f"ElementalCosting(dp={self.dp!r}, items={count})"


def _walk_ec_ctgy(
    ctgy: ECCtgy, depth: int,
) -> Iterator[tuple[int, str, ECCtgy | None]]:
    label = ctgy.description or ctgy.ele_no
    yield (depth, label, ctgy)
    if ctgy.body is not None:
        for sub in ctgy.body.categories:
            yield from _walk_ec_ctgy(sub, depth + 1)
