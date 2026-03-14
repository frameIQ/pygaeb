"""Root document models: GAEBDocument, GAEBInfo, AwardInfo."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.boq import BoQ
from pygaeb.models.enums import ExchangePhase, SourceVersion, ValidationSeverity
from pygaeb.models.item import ValidationResult


class GAEBInfo(BaseModel):
    """Metadata about the software that generated the GAEB file."""

    model_config = {"arbitrary_types_allowed": True}

    version: str | None = None
    prog_system: str | None = None
    prog_system_version: str | None = None
    date: datetime | None = None
    source_element: Any = Field(default=None, exclude=True, repr=False)


class AwardInfo(BaseModel):
    """Project-level award information."""

    model_config = {"arbitrary_types_allowed": True}

    project_no: str | None = None
    project_name: str | None = None
    client: str | None = None
    currency: str = "EUR"
    currency_short: str | None = None
    procurement_type: str | None = None
    date: datetime | None = None
    place: str | None = None
    boq: BoQ = Field(default_factory=BoQ)
    source_element: Any = Field(default=None, exclude=True, repr=False)


class GAEBDocument(BaseModel):
    """Root model produced by all parser tracks — the unified output contract."""

    model_config = {"arbitrary_types_allowed": True}

    source_version: SourceVersion = SourceVersion.DA_XML_33
    exchange_phase: ExchangePhase = ExchangePhase.X83
    gaeb_info: GAEBInfo = Field(default_factory=GAEBInfo)
    award: AwardInfo = Field(default_factory=AwardInfo)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    source_file: str | None = None
    raw_namespace: str | None = None
    xml_root: Any = Field(default=None, exclude=True, repr=False)

    def __repr__(self) -> str:
        return (
            f"GAEBDocument(version={self.source_version.value}, "
            f"phase={self.exchange_phase.value}, items={self.item_count})"
        )

    @property
    def grand_total(self) -> Decimal:
        """Sum of all item.total_price where item_type.affects_total is True."""
        return _sum_prices(self.award.boq.iter_items())

    @property
    def computed_grand_total(self) -> Decimal:
        """Sum of all item.computed_total (qty x unit_price)."""
        return _sum_computed(self.award.boq.iter_items())

    @property
    def item_count(self) -> int:
        return sum(1 for _ in self.award.boq.iter_items())

    @property
    def memory_estimate_mb(self) -> float:
        """Approximate memory usage in MB (~1 KB per item + attachment sizes)."""
        item_count = 0
        attach_bytes = 0
        for item in self.award.boq.iter_items():
            item_count += 1
            for a in item.attachments:
                attach_bytes += a.size_bytes
        return item_count / 1024 + attach_bytes / (1024 * 1024)

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
