"""Bill of Quantities structure models: BoQInfo, BoQBkdn, BoQBody, BoQCtgy, Lot."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.enums import BkdnType
from pygaeb.models.item import Item


def _items_subtotal(items: Iterator[Item]) -> Decimal:
    """Sum total_price for items where item_type.affects_total."""
    total = Decimal("0")
    for i in items:
        if i.total_price is not None and i.item_type.affects_total:
            total += i.total_price
    return total


class BoQBkdn(BaseModel):
    """Single level in the BoQ breakdown structure."""

    bkdn_type: BkdnType
    length: int
    key: str = ""


class CostType(BaseModel):
    """Cost type classification on BoQInfo (X52 Kalkulationsansätze)."""

    name: str = ""
    label: str = ""


class VATPart(BaseModel):
    """A single VAT rate partition within a ``Totals`` block.

    GAEB files can have multiple VAT rates (e.g. 19% and 7%) applied to
    different subsets of items.  Each ``VATPart`` carries the net amount
    subject to that rate and the resulting VAT amount.
    """

    vat_pcnt: Decimal = Decimal("0")
    total_net_part: Decimal | None = None
    vat_amount: Decimal | None = None


class Totals(BaseModel):
    """Authoritative financial summary (``<Totals>``) on BoQInfo, BoQCtgy, or Lot.

    Fields mirror the ``tgTotals`` schema type.  All monetary values use
    ``Decimal`` for precision.
    """

    total: Decimal | None = None
    discount_pcnt: Decimal | None = None
    discount_amt: Decimal | None = None
    tot_after_disc: Decimal | None = None
    total_lsum: Decimal | None = None
    vat: Decimal | None = None
    total_net: Decimal | None = None
    total_net_up_comp: list[Decimal] = Field(default_factory=list)
    vat_parts: list[VATPart] = Field(default_factory=list)
    vat_amount: Decimal | None = None
    total_gross: Decimal | None = None


class BoQInfo(BaseModel):
    """BoQ-level metadata including breakdown definitions."""

    name: str | None = None
    lbl_boq: str | None = None
    bkdn: list[BoQBkdn] = Field(default_factory=list)
    outline_complete: bool = False
    cost_types: list[CostType] = Field(default_factory=list)
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    totals: Totals | None = None


class BoQCtgy(BaseModel):
    """A category (section) in the BoQ hierarchy, containing items and/or sub-categories."""

    model_config = {"arbitrary_types_allowed": True}

    rno: str = ""
    label: str = ""
    items: list[Item] = Field(default_factory=list)
    subcategories: list[BoQCtgy] = Field(default_factory=list)
    lbl_tx: str | None = None
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    totals: Totals | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def iter_items(self) -> Iterator[Item]:
        """Iterate all items in this category and its subcategories."""
        stack: list[BoQCtgy] = [self]
        while stack:
            current = stack.pop()
            yield from current.items
            stack.extend(reversed(current.subcategories))

    @property
    def subtotal(self) -> Decimal:
        return _items_subtotal(self.iter_items())

    def add_item(self, **kwargs: Any) -> Item:
        """Add a new item to this category.

        Returns:
            The newly created Item.
        """
        item = Item(**kwargs)
        self.items.append(item)
        return item

    def remove_item(self, oz: str) -> Item | None:
        """Remove an item by OZ from this category (non-recursive).

        Returns:
            The removed Item, or None if not found.
        """
        for i, item in enumerate(self.items):
            if item.oz == oz:
                return self.items.pop(i)
        return None


class BoQBody(BaseModel):
    """Top-level BoQ body containing categories."""

    categories: list[BoQCtgy] = Field(default_factory=list)

    def iter_items(self) -> Iterator[Item]:
        for ctgy in self.categories:
            yield from ctgy.iter_items()


class Lot(BaseModel):
    """A single lot within a multi-lot document."""

    rno: str = ""
    label: str = ""
    boq_info: BoQInfo | None = None
    body: BoQBody = Field(default_factory=BoQBody)
    totals: Totals | None = None

    def __repr__(self) -> str:
        count = sum(1 for _ in self.iter_items())
        return f"Lot(rno={self.rno!r}, label={self.label!r}, items={count})"

    def iter_items(self) -> Iterator[Item]:
        return self.body.iter_items()

    @property
    def subtotal(self) -> Decimal:
        return _items_subtotal(self.iter_items())


class BoQ(BaseModel):
    """Complete BoQ structure supporting single and multi-lot documents."""

    boq_info: BoQInfo | None = None
    lots: list[Lot] = Field(default_factory=list)

    def __repr__(self) -> str:
        count = sum(1 for _ in self.iter_items())
        return f"BoQ(lots={len(self.lots)}, items={count})"

    @property
    def is_multi_lot(self) -> bool:
        return len(self.lots) > 1

    def iter_items(self) -> Iterator[Item]:
        """Iterate all items across all lots."""
        for lot in self.lots:
            yield from lot.iter_items()

    def get_item(self, oz: str) -> Item | None:
        """Find an item by its OZ (ordinal number)."""
        for item in self.iter_items():
            if item.oz == oz:
                return item
        return None

    def add_item(self, oz: str, category_rno: str, **kwargs: Any) -> Item:
        """Add a new item to the category matching *category_rno*.

        Searches across all lots. Raises ``ValueError`` if the category
        is not found.

        Args:
            oz: Ordinal number for the new item.
            category_rno: Target category ``rno``.
            **kwargs: Additional Item fields (short_text, qty, unit, etc.).

        Returns:
            The newly created Item.
        """
        ctgy = self._find_category(category_rno)
        if ctgy is None:
            raise ValueError(
                f"Category with rno={category_rno!r} not found in BoQ"
            )
        return ctgy.add_item(oz=oz, **kwargs)

    def remove_item(self, oz: str) -> Item | None:
        """Remove an item by OZ from any category across all lots.

        Returns:
            The removed Item, or None if not found.
        """
        for lot in self.lots:
            for ctgy in lot.body.categories:
                result = _remove_from_ctgy(ctgy, oz)
                if result is not None:
                    return result
        return None

    def move_item(self, oz: str, target_category_rno: str) -> Item:
        """Move an item from its current category to another.

        Args:
            oz: OZ of the item to move.
            target_category_rno: Destination category ``rno``.

        Returns:
            The moved Item.

        Raises:
            ValueError: If item or target category not found.
        """
        item = self.remove_item(oz)
        if item is None:
            raise ValueError(f"Item with oz={oz!r} not found in BoQ")
        target = self._find_category(target_category_rno)
        if target is None:
            raise ValueError(
                f"Target category with rno={target_category_rno!r} not found"
            )
        target.items.append(item)
        return item

    def recalculate_totals(self) -> None:
        """Recompute all Totals from items at category, lot, and BoQ levels."""
        for lot in self.lots:
            for ctgy in lot.body.categories:
                _recalc_ctgy_totals(ctgy)
            if lot.totals is not None:
                lot.totals.total = lot.subtotal
        if self.boq_info and self.boq_info.totals is not None:
            self.boq_info.totals.total = sum(
                (lot.subtotal for lot in self.lots), Decimal("0")
            )

    def _find_category(self, rno: str) -> BoQCtgy | None:
        """Find a category by rno across all lots (depth-first)."""
        for lot in self.lots:
            for ctgy in lot.body.categories:
                found = _find_ctgy(ctgy, rno)
                if found is not None:
                    return found
        return None

    def iter_hierarchy(self) -> Iterator[tuple[int, str, BoQCtgy | None]]:
        """Walk the hierarchy tree yielding (depth, label, category_or_none)."""
        for lot in self.lots:
            yield (0, lot.label, None)
            for ctgy in lot.body.categories:
                yield from _walk_ctgy(ctgy, 1)


_MAX_HIERARCHY_DEPTH = 50


def _walk_ctgy(ctgy: BoQCtgy, depth: int) -> Iterator[tuple[int, str, BoQCtgy | None]]:
    if depth > _MAX_HIERARCHY_DEPTH:
        return
    yield (depth, ctgy.label, ctgy)
    for sub in ctgy.subcategories:
        yield from _walk_ctgy(sub, depth + 1)


def _remove_from_ctgy(ctgy: BoQCtgy, oz: str, depth: int = 0) -> Item | None:
    """Recursively search and remove an item by OZ."""
    if depth > _MAX_HIERARCHY_DEPTH:
        return None
    removed = ctgy.remove_item(oz)
    if removed is not None:
        return removed
    for sub in ctgy.subcategories:
        removed = _remove_from_ctgy(sub, oz, depth + 1)
        if removed is not None:
            return removed
    return None


def _find_ctgy(ctgy: BoQCtgy, rno: str, depth: int = 0) -> BoQCtgy | None:
    """Recursively find a category by rno."""
    if depth > _MAX_HIERARCHY_DEPTH:
        return None
    if ctgy.rno == rno:
        return ctgy
    for sub in ctgy.subcategories:
        found = _find_ctgy(sub, rno, depth + 1)
        if found is not None:
            return found
    return None


def _recalc_ctgy_totals(ctgy: BoQCtgy, depth: int = 0) -> None:
    """Recursively recompute totals from items."""
    if depth > _MAX_HIERARCHY_DEPTH:
        return
    for sub in ctgy.subcategories:
        _recalc_ctgy_totals(sub, depth + 1)
    if ctgy.totals is not None:
        ctgy.totals.total = ctgy.subtotal
