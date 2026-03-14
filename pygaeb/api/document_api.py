"""Developer-friendly document navigation: iter_items, iter_hierarchy, get_item, filter."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Callable

from pygaeb.models.boq import BoQ, BoQCtgy, Lot
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ItemType
from pygaeb.models.item import Item


class DocumentAPI:
    """Convenience wrapper for navigating a parsed GAEBDocument.

    Most of these methods are also available directly on the model objects
    (GAEBDocument, BoQ, Lot). This class provides additional filtering
    and query capabilities.
    """

    def __init__(self, doc: GAEBDocument) -> None:
        self._doc = doc

    @property
    def boq(self) -> BoQ:
        return self._doc.award.boq

    @property
    def lots(self) -> list[Lot]:
        return self.boq.lots

    @property
    def is_multi_lot(self) -> bool:
        return self.boq.is_multi_lot

    def iter_items(self, lot_index: int | None = None) -> Iterator[Item]:
        """Iterate all items, optionally filtered to a specific lot."""
        if lot_index is not None:
            if 0 <= lot_index < len(self.lots):
                yield from self.lots[lot_index].iter_items()
        else:
            yield from self.boq.iter_items()

    def get_item(self, oz: str) -> Item | None:
        """Find an item by its OZ (ordinal number)."""
        return self.boq.get_item(oz)

    def iter_hierarchy(self) -> Iterator[tuple[int, str, BoQCtgy | None]]:
        """Walk the BoQ hierarchy tree yielding (depth, label, category_or_none)."""
        return self.boq.iter_hierarchy()

    def filter_items(
        self,
        predicate: Callable[[Item], bool] | None = None,
        item_type: ItemType | None = None,
        trade: str | None = None,
        min_total: Decimal | None = None,
        has_classification: bool | None = None,
    ) -> list[Item]:
        """Filter items by various criteria."""
        items = list(self.boq.iter_items())

        if item_type is not None:
            items = [i for i in items if i.item_type == item_type]

        if trade is not None:
            items = [
                i for i in items
                if i.classification and i.classification.trade == trade
            ]

        if min_total is not None:
            items = [
                i for i in items
                if i.total_price is not None and i.total_price >= min_total
            ]

        if has_classification is not None:
            items = [
                i for i in items
                if (i.classification is not None) == has_classification
            ]

        if predicate is not None:
            items = [i for i in items if predicate(i)]

        return items

    def summary(self) -> dict[str, Any]:
        """Return a summary of the document."""
        items = list(self.boq.iter_items())
        classified = [i for i in items if i.classification]

        trade_counts: dict[str, int] = {}
        for item in classified:
            if item.classification:
                trade = item.classification.trade
                trade_counts[trade] = trade_counts.get(trade, 0) + 1

        return {
            "source_version": self._doc.source_version.value,
            "exchange_phase": self._doc.exchange_phase.value,
            "total_items": len(items),
            "classified_items": len(classified),
            "grand_total": str(self._doc.grand_total),
            "lots": len(self.lots),
            "is_multi_lot": self.is_multi_lot,
            "validation_errors": sum(
                1 for r in self._doc.validation_results
                if r.severity.value == "ERROR"
            ),
            "validation_warnings": sum(
                1 for r in self._doc.validation_results
                if r.severity.value == "WARNING"
            ),
            "trades": trade_counts,
        }
