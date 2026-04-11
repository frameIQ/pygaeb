"""Quantity determination models for GAEB X31 (Mengenermittlung)."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from pygaeb.models.boq import BoQBkdn
from pygaeb.models.catalog import Catalog, CtlgAssign
from pygaeb.models.order import Address


class QtyAttachment(BaseModel):
    """Catalog attachment from X31 quantity determination (photos, sketches, PDFs).

    Referenced from QTakeoff rows via ``#Bild <name>`` syntax.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str = ""
    text: str = ""
    description: str = ""
    file_type: str = ""
    data: bytes = b""
    size_bytes: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.size_bytes == 0 and self.data:
            object.__setattr__(self, "size_bytes", len(self.data))

    @property
    def mime_type(self) -> str:
        """Derive MIME type from file_type."""
        _map = {
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "pdf": "application/pdf",
        }
        return _map.get(self.file_type.lower(), "application/octet-stream")

    @property
    def data_base64(self) -> str:
        """Return base64-encoded data string."""
        return base64.b64encode(self.data).decode("ascii") if self.data else ""


class ParsedTakeoff(BaseModel):
    """Structured result of parsing a REB 23.003 takeoff row.

    Extracted from the raw fixed-width string via
    :meth:`QTakeoffRow.parse`.
    """

    description: str = ""
    dimensions: list[Decimal] = Field(default_factory=list)
    operator: str = ""
    computed_qty: Decimal | None = None
    unit: str = ""
    formula: str = ""


class QTakeoffRow(BaseModel):
    """Single quantity take-off row (REB 23.003 format).

    The ``raw`` field stores the full fixed-width formatted string
    (typically 80 characters) as specified by the REB 23.003 standard.

    Call :meth:`parse` to extract structured dimensions and computed
    quantity from the raw string.
    """

    model_config = {"arbitrary_types_allowed": True}

    raw: str = ""
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)
    parsed: ParsedTakeoff | None = Field(default=None, exclude=True)

    def parse(self) -> ParsedTakeoff:
        """Parse the raw REB 23.003 string into structured fields.

        Extracts description, dimensions, formula, and computed quantity
        from common REB row formats::

            "Fundament A  5,00 * 3,20 * 0,75 = 12,000 m3"
            "Wand Nord   12,50 * 3,00 = 37,500 m2"

        Returns:
            A :class:`ParsedTakeoff` with extracted fields.
        """
        from pygaeb.parser.reb_parser import parse_reb_row
        self.parsed = parse_reb_row(self.raw)
        return self.parsed


class QDetermItem(BaseModel):
    """A single quantity determination entry with a take-off row."""

    model_config = {"arbitrary_types_allowed": True}

    takeoff_row: QTakeoffRow = Field(default_factory=QTakeoffRow)
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)


class QtyItem(BaseModel):
    """A quantity-determination item — thin BoQ position with measurement data.

    Unlike procurement ``Item``, this model carries no descriptions or prices.
    The ``oz`` field enables cross-referencing with procurement BoQ items.
    """

    model_config = {"arbitrary_types_allowed": True}

    oz: str = ""
    rno_part: str = ""
    rno_index: str = ""
    qty: Decimal | None = None
    determ_items: list[QDetermItem] = Field(default_factory=list)
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def __repr__(self) -> str:
        parts = [f"oz={self.oz!r}"]
        if self.qty is not None:
            parts.append(f"qty={self.qty}")
        parts.append(f"rows={len(self.determ_items)}")
        return f"QtyItem({', '.join(parts)})"


class QtyBoQCtgy(BaseModel):
    """Category in a quantity determination BoQ."""

    model_config = {"arbitrary_types_allowed": True}

    rno: str = ""
    items: list[QtyItem] = Field(default_factory=list)
    subcategories: list[QtyBoQCtgy] = Field(default_factory=list)
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def iter_items(self) -> Iterator[QtyItem]:
        """Iterate all items in this category and its subcategories."""
        stack: list[QtyBoQCtgy] = [self]
        while stack:
            current = stack.pop()
            yield from current.items
            stack.extend(reversed(current.subcategories))


class QtyBoQBody(BaseModel):
    """Top-level body of a quantity determination BoQ."""

    categories: list[QtyBoQCtgy] = Field(default_factory=list)

    def iter_items(self) -> Iterator[QtyItem]:
        for ctgy in self.categories:
            yield from ctgy.iter_items()


class QtyBoQ(BaseModel):
    """Quantity determination BoQ — simplified BoQ referencing an external procurement BoQ."""

    model_config = {"arbitrary_types_allowed": True}

    ref_boq_name: str = ""
    ref_boq_id: str = ""
    bkdn: list[BoQBkdn] = Field(default_factory=list)
    catalogs: list[Catalog] = Field(default_factory=list)
    body: QtyBoQBody = Field(default_factory=QtyBoQBody)
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)
    attachments: list[QtyAttachment] = Field(default_factory=list)
    source_element: Any = Field(default=None, exclude=True, repr=False)

    def iter_items(self) -> Iterator[QtyItem]:
        return self.body.iter_items()

    def get_item(self, oz: str) -> QtyItem | None:
        """Find a quantity item by its OZ (ordinal number)."""
        for item in self.iter_items():
            if item.oz == oz:
                return item
        return None

    def iter_hierarchy(self) -> Iterator[tuple[int, str, QtyBoQCtgy | None]]:
        """Walk the category hierarchy tree."""
        for ctgy in self.body.categories:
            yield from _walk_qty_ctgy(ctgy, 0)


class PrjInfoQD(BaseModel):
    """Project reference info for quantity determination."""

    ref_prj_name: str = ""
    ref_prj_id: str = ""


class QtyDetermInfo(BaseModel):
    """Metadata for the quantity determination."""

    method: str = ""
    order_descr: str = ""
    project_descr: str = ""
    service_start: datetime | None = None
    service_end: datetime | None = None
    creator: Address | None = None
    profiler: Address | None = None
    ctlg_assigns: list[CtlgAssign] = Field(default_factory=list)


class QtyDetermination(BaseModel):
    """Root model for X31 Quantity Determination documents."""

    model_config = {"arbitrary_types_allowed": True}

    dp: str = ""
    prj_info: PrjInfoQD | None = None
    info: QtyDetermInfo = Field(default_factory=QtyDetermInfo)
    owner: Address | None = None
    contractor: Address | None = None
    boq: QtyBoQ = Field(default_factory=QtyBoQ)

    def iter_items(self) -> Iterator[QtyItem]:
        """Iterate all quantity items."""
        return self.boq.iter_items()

    @property
    def item_count(self) -> int:
        return sum(1 for _ in self.iter_items())

    @property
    def grand_total(self) -> Decimal:
        """Always zero — quantity determination documents have no prices."""
        return Decimal("0")

    def iter_hierarchy(self) -> Iterator[tuple[int, str, Any]]:
        """Walk the BoQ hierarchy tree."""
        return self.boq.iter_hierarchy()


_MAX_HIERARCHY_DEPTH = 50


def _walk_qty_ctgy(
    ctgy: QtyBoQCtgy, depth: int,
) -> Iterator[tuple[int, str, QtyBoQCtgy | None]]:
    if depth > _MAX_HIERARCHY_DEPTH:
        return
    yield (depth, ctgy.rno, ctgy)
    for sub in ctgy.subcategories:
        yield from _walk_qty_ctgy(sub, depth + 1)
