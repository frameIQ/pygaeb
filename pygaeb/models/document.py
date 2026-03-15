"""Root document models: GAEBDocument, GAEBInfo, AwardInfo."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.boq import BoQ
from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.cost import ElementalCosting
from pygaeb.models.enums import (
    DocumentKind,
    ExchangePhase,
    SourceVersion,
    ValidationSeverity,
)
from pygaeb.models.item import ValidationResult
from pygaeb.models.order import Address, TradeOrder
from pygaeb.models.quantity import QtyDetermination


class GAEBInfo(BaseModel):
    """Metadata about the software that generated the GAEB file."""

    model_config = {"arbitrary_types_allowed": True}

    version: str | None = None
    prog_system: str | None = None
    prog_system_version: str | None = None
    date: datetime | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)


class AwardInfo(BaseModel):
    """Project-level award information (procurement phases X80-X89).

    Fields from both ``<AwardInfo>`` and ``<PrjInfo>`` are merged here
    to give a single, developer-friendly project metadata object.
    """

    model_config = {"arbitrary_types_allowed": True}

    project_no: str | None = None
    project_name: str | None = None
    client: str | None = None
    currency: str = "EUR"
    currency_short: str | None = None
    procurement_type: str | None = None
    date: datetime | None = None
    place: str | None = None

    # --- AwardInfo XML fields ---
    category: str | None = None
    open_date: datetime | None = None
    open_time: str | None = None
    eval_end: datetime | None = None
    submit_location: str | None = None
    construction_start: datetime | None = None
    construction_end: datetime | None = None
    contract_no: str | None = None
    contract_date: datetime | None = None
    accept_type: str | None = None
    warranty_duration: int | None = None
    warranty_unit: str | None = None

    # --- OWN (owner/client) ---
    owner_address: Address | None = None
    award_no: str | None = None

    # --- PrjInfo fields ---
    prj_id: str | None = None
    lbl_prj: str | None = None
    description: str | None = None
    currency_label: str | None = None
    bid_comm_perm: bool = False
    alter_bid_perm: bool = False
    up_frac_dig: int | None = None
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)

    boq: BoQ = Field(default_factory=BoQ)
    source_element: Any = Field(default=None, exclude=True, repr=False)


class GAEBDocument(BaseModel):
    """Root model produced by all parser tracks — the unified output contract.

    Procurement documents populate ``award``; trade documents populate
    ``order``; cost documents populate ``elemental_costing``; quantity
    determination documents populate ``qty_determination``.
    Use ``document_kind``, ``is_trade``, ``is_procurement``, ``is_cost``,
    or ``is_quantity`` to discriminate, and ``iter_items()`` for universal
    iteration.
    """

    model_config = {"arbitrary_types_allowed": True}

    source_version: SourceVersion = SourceVersion.DA_XML_33
    exchange_phase: ExchangePhase = ExchangePhase.X83
    gaeb_info: GAEBInfo = Field(default_factory=GAEBInfo)
    award: AwardInfo = Field(default_factory=AwardInfo)
    order: TradeOrder | None = Field(default=None)
    elemental_costing: ElementalCosting | None = Field(default=None)
    qty_determination: QtyDetermination | None = Field(default=None)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    source_file: str | None = None
    raw_namespace: str | None = None
    xml_root: Any = Field(default=None, exclude=True, repr=False)

    def __repr__(self) -> str:
        return (
            f"GAEBDocument(version={self.source_version.value}, "
            f"phase={self.exchange_phase.value}, kind={self.document_kind.value}, "
            f"items={self.item_count})"
        )

    # ------------------------------------------------------------------
    # Document kind discriminators
    # ------------------------------------------------------------------

    @property
    def document_kind(self) -> DocumentKind:
        if self.qty_determination is not None:
            return DocumentKind.QUANTITY
        if self.elemental_costing is not None:
            return DocumentKind.COST
        if self.order is not None:
            return DocumentKind.TRADE
        return DocumentKind.PROCUREMENT

    @property
    def is_trade(self) -> bool:
        return self.order is not None

    @property
    def is_procurement(self) -> bool:
        return (
            self.order is None
            and self.elemental_costing is None
            and self.qty_determination is None
        )

    @property
    def is_cost(self) -> bool:
        return self.elemental_costing is not None

    @property
    def is_quantity(self) -> bool:
        return self.qty_determination is not None

    # ------------------------------------------------------------------
    # Universal iteration
    # ------------------------------------------------------------------

    def iter_items(self) -> Iterator[Any]:
        """Iterate all items regardless of document kind.

        Returns ``Item`` instances for procurement documents,
        ``OrderItem`` instances for trade documents,
        ``CostElement`` instances for cost documents, and
        ``QtyItem`` instances for quantity determination documents.
        """
        if self.qty_determination is not None:
            yield from self.qty_determination.iter_items()
        elif self.elemental_costing is not None:
            yield from self.elemental_costing.iter_items()
        elif self.order is not None:
            yield from self.order.iter_items()
        else:
            yield from self.award.boq.iter_items()

    # ------------------------------------------------------------------
    # Aggregate properties
    # ------------------------------------------------------------------

    @property
    def grand_total(self) -> Decimal:
        """Sum of all item totals across any document kind."""
        if self.qty_determination is not None:
            return self.qty_determination.grand_total
        if self.elemental_costing is not None:
            return self.elemental_costing.grand_total
        if self.order is not None:
            return self.order.grand_total
        return _sum_prices(self.award.boq.iter_items())

    @property
    def computed_grand_total(self) -> Decimal:
        """Sum of all item.computed_total (qty x unit_price). Procurement only."""
        if self.qty_determination is not None:
            return self.qty_determination.grand_total
        if self.elemental_costing is not None:
            return self.elemental_costing.grand_total
        if self.order is not None:
            return self.order.grand_total
        return _sum_computed(self.award.boq.iter_items())

    @property
    def item_count(self) -> int:
        if self.qty_determination is not None:
            return self.qty_determination.item_count
        if self.elemental_costing is not None:
            return self.elemental_costing.item_count
        if self.order is not None:
            return self.order.item_count
        return sum(1 for _ in self.award.boq.iter_items())

    @property
    def memory_estimate_mb(self) -> float:
        """Approximate memory usage in MB (~1 KB per item + attachment sizes)."""
        if self.qty_determination is not None:
            count = self.qty_determination.item_count
            attach_bytes = sum(
                a.size_bytes for a in self.qty_determination.boq.attachments
            )
            return count / 1024 + attach_bytes / (1024 * 1024)
        if self.elemental_costing is not None:
            return float(self.elemental_costing.item_count) / 1024
        if self.order is not None:
            return float(self.order.item_count) / 1024
        item_count = 0
        attach_bytes = 0
        for item in self.award.boq.iter_items():
            item_count += 1
            for a in item.attachments:
                attach_bytes += a.size_bytes
        return item_count / 1024 + attach_bytes / (1024 * 1024)

    # ------------------------------------------------------------------
    # Memory management
    # ------------------------------------------------------------------

    def discard_xml(self) -> None:
        """Release the retained lxml tree and all ``source_element`` references.

        Call this after you are done with :meth:`xpath` and
        ``source_element`` access to free the underlying C-level memory
        held by lxml.
        """
        self.xml_root = None
        self.gaeb_info.source_element = None
        self.award.source_element = None

        if self.order is not None:
            self.order.source_element = None
            for oi in self.order.items:
                oi.source_element = None

        if self.elemental_costing is not None:
            self.elemental_costing.source_element = None
            self._discard_ec_elements(self.elemental_costing.body)

        if self.qty_determination is not None:
            self._discard_qty_elements(self.qty_determination.boq)

        for lot in self.award.boq.lots:
            for ctgy in lot.body.categories:
                self._discard_boq_ctgy_elements(ctgy)

    @staticmethod
    def _discard_boq_ctgy_elements(ctgy: Any) -> None:
        stack = [ctgy]
        while stack:
            c = stack.pop()
            if hasattr(c, "source_element"):
                c.source_element = None
            for item in getattr(c, "items", []):
                if hasattr(item, "source_element"):
                    item.source_element = None
            stack.extend(getattr(c, "subcategories", []))

    @staticmethod
    def _discard_ec_elements(body: Any) -> None:
        for ce in getattr(body, "cost_elements", []):
            stack_ce: list[Any] = [ce]
            while stack_ce:
                el = stack_ce.pop()
                el.source_element = None
                stack_ce.extend(getattr(el, "children", []))
        for dim in getattr(body, "dimension_elements", []):
            if hasattr(dim, "source_element"):
                dim.source_element = None
        for cat in getattr(body, "category_elements", []):
            if hasattr(cat, "source_element"):
                cat.source_element = None
        for sub in getattr(body, "categories", []):
            if hasattr(sub, "source_element"):
                sub.source_element = None
            if sub.body is not None:
                GAEBDocument._discard_ec_elements(sub.body)

    @staticmethod
    def _discard_qty_elements(boq: Any) -> None:
        if hasattr(boq, "source_element"):
            boq.source_element = None
        body = getattr(boq, "body", None)
        stack = list(getattr(body, "categories", []) if body else [])
        while stack:
            c = stack.pop()
            if hasattr(c, "source_element"):
                c.source_element = None
            for qi in getattr(c, "items", []):
                if hasattr(qi, "source_element"):
                    qi.source_element = None
                for di in getattr(qi, "determ_items", []):
                    if hasattr(di, "source_element"):
                        di.source_element = None
                    tr = getattr(di, "takeoff_row", None)
                    if tr is not None and hasattr(tr, "source_element"):
                        tr.source_element = None
            stack.extend(getattr(c, "subcategories", []))

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def add_warning(self, message: str, xpath: str | None = None) -> None:
        self.validation_results.append(
            ValidationResult(severity=ValidationSeverity.WARNING, message=message,
                             xpath_location=xpath)
        )

    def add_error(self, message: str, xpath: str | None = None) -> None:
        self.validation_results.append(
            ValidationResult(severity=ValidationSeverity.ERROR, message=message,
                             xpath_location=xpath)
        )

    def add_info(self, message: str, xpath: str | None = None) -> None:
        self.validation_results.append(
            ValidationResult(severity=ValidationSeverity.INFO, message=message,
                             xpath_location=xpath)
        )

    def xpath(self, expression: str) -> list[Any]:
        """Run an XPath query against the raw XML tree.

        Requires ``keep_xml=True`` at parse time.  When the document has a
        namespace, it is available as the ``g`` prefix::

            doc.xpath("//g:Item[@RNoPart='001']")
        """
        if self.xml_root is None:
            raise RuntimeError(
                "Raw XML not available. Re-parse with keep_xml=True."
            )
        nsmap: dict[str, str] = {}
        if self.raw_namespace:
            nsmap["g"] = self.raw_namespace
        return self.xml_root.xpath(expression, namespaces=nsmap)  # type: ignore[no-any-return]


def _sum_prices(items: Iterator[Any]) -> Decimal:
    """Sum total_price for items where item_type.affects_total."""
    from pygaeb.models.item import Item
    total = Decimal("0")
    for i in items:
        if isinstance(i, Item) and i.total_price is not None and i.item_type.affects_total:
            total += i.total_price
    return total


def _sum_computed(items: Iterator[Any]) -> Decimal:
    """Sum computed_total for items where item_type.affects_total."""
    from pygaeb.models.item import Item
    total = Decimal("0")
    for i in items:
        if isinstance(i, Item) and i.computed_total is not None and i.item_type.affects_total:
            total += i.computed_total
    return total
