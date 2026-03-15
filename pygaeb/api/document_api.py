"""Developer-friendly document navigation: iter_items, iter_hierarchy, get_item, filter."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Callable

from pygaeb.models.boq import BoQ, Lot
from pygaeb.models.cost import CostElement, ElementalCosting
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import DocumentKind, ItemType
from pygaeb.models.item import Item
from pygaeb.models.order import OrderItem, TradeOrder
from pygaeb.models.quantity import QtyDetermination, QtyItem


class DocumentAPI:
    """Convenience wrapper for navigating a parsed GAEBDocument.

    Works with procurement, trade, and cost documents.  Use ``is_trade`` /
    ``is_procurement`` / ``is_cost`` to discriminate, and ``iter_items()``
    for universal iteration over any document kind.
    """

    def __init__(self, doc: GAEBDocument) -> None:
        self._doc = doc

    # ------------------------------------------------------------------
    # Document kind
    # ------------------------------------------------------------------

    @property
    def document_kind(self) -> DocumentKind:
        return self._doc.document_kind

    @property
    def is_trade(self) -> bool:
        return self._doc.is_trade

    @property
    def is_procurement(self) -> bool:
        return self._doc.is_procurement

    @property
    def is_cost(self) -> bool:
        return self._doc.is_cost

    @property
    def is_quantity(self) -> bool:
        return self._doc.is_quantity

    # ------------------------------------------------------------------
    # Procurement accessors
    # ------------------------------------------------------------------

    @property
    def boq(self) -> BoQ:
        return self._doc.award.boq

    @property
    def lots(self) -> list[Lot]:
        return self.boq.lots

    @property
    def is_multi_lot(self) -> bool:
        return self.boq.is_multi_lot

    # ------------------------------------------------------------------
    # Trade accessors
    # ------------------------------------------------------------------

    @property
    def order(self) -> TradeOrder | None:
        return self._doc.order

    # ------------------------------------------------------------------
    # Cost accessors
    # ------------------------------------------------------------------

    @property
    def elemental_costing(self) -> ElementalCosting | None:
        return self._doc.elemental_costing

    # ------------------------------------------------------------------
    # Quantity accessors
    # ------------------------------------------------------------------

    @property
    def qty_determination(self) -> QtyDetermination | None:
        return self._doc.qty_determination

    # ------------------------------------------------------------------
    # Universal iteration
    # ------------------------------------------------------------------

    def iter_items(self, lot_index: int | None = None) -> Iterator[Any]:
        """Iterate all items (universal — works for all document kinds).

        For procurement documents, optionally filter to a specific lot.
        """
        if self._doc.is_quantity:
            if self._doc.qty_determination is not None:
                yield from self._doc.qty_determination.iter_items()
            return

        if self._doc.is_cost:
            if self._doc.elemental_costing is not None:
                yield from self._doc.elemental_costing.iter_items()
            return

        if self._doc.is_trade:
            if self._doc.order is not None:
                yield from self._doc.order.iter_items()
            return

        if lot_index is not None:
            if 0 <= lot_index < len(self.lots):
                yield from self.lots[lot_index].iter_items()
        else:
            yield from self.boq.iter_items()

    def get_item(self, oz: str) -> Item | None:
        """Find a procurement item by its OZ (ordinal number)."""
        return self.boq.get_item(oz)

    def get_order_item(self, art_no: str) -> OrderItem | None:
        """Find a trade order item by article number."""
        if self._doc.order is None:
            return None
        for item in self._doc.order.items:
            if item.art_no == art_no:
                return item
        return None

    def get_cost_element(self, ele_no: str) -> CostElement | None:
        """Find a cost element by its element number."""
        if self._doc.elemental_costing is None:
            return None
        for ce in self._doc.elemental_costing.iter_items():
            if ce.ele_no == ele_no:
                return ce
        return None

    def get_qty_item(self, oz: str) -> QtyItem | None:
        """Find a quantity determination item by its OZ."""
        if self._doc.qty_determination is None:
            return None
        return self._doc.qty_determination.boq.get_item(oz)

    def iter_hierarchy(self) -> Iterator[tuple[int, str, Any]]:
        """Walk the hierarchy tree (procurement BoQ, cost, or quantity)."""
        if self._doc.is_quantity and self._doc.qty_determination is not None:
            return self._doc.qty_determination.iter_hierarchy()
        if self._doc.is_cost and self._doc.elemental_costing is not None:
            return self._doc.elemental_costing.iter_hierarchy()
        return self.boq.iter_hierarchy()

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def filter_items(
        self,
        predicate: Callable[[Any], bool] | None = None,
        item_type: ItemType | None = None,
        trade: str | None = None,
        min_total: Decimal | None = None,
        has_classification: bool | None = None,
    ) -> list[Any]:
        """Filter items by various criteria (works for all document kinds)."""
        items = list(self.iter_items())

        if item_type is not None:
            items = [
                i for i in items
                if isinstance(i, Item) and i.item_type == item_type
            ]

        if trade is not None:
            items = [
                i for i in items
                if i.classification and i.classification.trade == trade
            ]

        if min_total is not None:
            items = [
                i for i in items
                if (t := _item_total(i)) is not None and t >= min_total
            ]

        if has_classification is not None:
            items = [
                i for i in items
                if (i.classification is not None) == has_classification
            ]

        if predicate is not None:
            items = [i for i in items if predicate(i)]

        return items

    # ------------------------------------------------------------------
    # XPath / custom tags
    # ------------------------------------------------------------------

    def xpath(self, expression: str) -> list[Any]:
        """Run an XPath query against the raw XML tree.

        Requires ``keep_xml=True`` at parse time.
        """
        return self._doc.xpath(expression)

    def custom_tag(self, item: Any, tag: str) -> str | None:
        """Get text content of a custom/vendor tag from an item's source element.

        Works for ``Item``, ``OrderItem``, and ``CostElement``.
        Returns None if the tag is not found or ``keep_xml`` was not enabled.
        """
        source_el = getattr(item, "source_element", None)
        if source_el is None:
            return None
        el = source_el.find(tag)
        if el is not None and el.text:
            return str(el.text).strip()
        return None

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a summary of the document."""
        items = list(self.iter_items())
        classified = [
            i for i in items if getattr(i, "classification", None)
        ]

        trade_counts: dict[str, int] = {}
        for item in classified:
            if item.classification:
                t = item.classification.trade
                trade_counts[t] = trade_counts.get(t, 0) + 1

        result: dict[str, Any] = {
            "source_version": self._doc.source_version.value,
            "exchange_phase": self._doc.exchange_phase.value,
            "document_kind": self._doc.document_kind.value,
            "total_items": len(items),
            "classified_items": len(classified),
            "grand_total": str(self._doc.grand_total),
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

        if self._doc.is_quantity and self._doc.qty_determination is not None:
            qd = self._doc.qty_determination
            result["method"] = qd.info.method
            result["ref_boq_name"] = qd.boq.ref_boq_name
            result["catalogs"] = len(qd.boq.catalogs)
            result["attachments"] = len(qd.boq.attachments)
        elif self._doc.is_cost and self._doc.elemental_costing is not None:
            ec = self._doc.elemental_costing
            result["ec_type"] = ec.ec_info.ec_type
            result["ec_method"] = ec.ec_info.ec_method
            has_bim = any(
                prop.cad_id
                for ce in ec.iter_items()
                for prop in ce.properties
            )
            result["has_bim_references"] = has_bim
        elif self._doc.is_procurement:
            result["lots"] = len(self.lots)
            result["is_multi_lot"] = self.is_multi_lot
        else:
            result["has_supplier_info"] = (
                self._doc.order is not None
                and self._doc.order.supplier_info is not None
            )

        return result


def _item_total(item: Any) -> Decimal | None:
    """Get the relevant total for an item of any kind."""
    if isinstance(item, Item):
        return item.total_price
    if isinstance(item, OrderItem):
        return item.display_price
    if isinstance(item, CostElement):
        return item.display_price
    return None
