"""PDF export: a GAEB document printed the way AVA programs print an LV.

Procurement documents print their hierarchy, full short and long texts, item-type
markers, subtotals and carry-forward lines; other document kinds print a flat item
list. Every string drawn can be reported to a callback with its page, position and
source, so a printed page can be traced back to the document.

Requires reportlab: ``pip install pyGAEB[pdf]``.

Usage::

    from pygaeb import GAEBParser
    from pygaeb.convert.to_pdf import PdfStyle, to_pdf

    doc = GAEBParser.parse("tender.X83")
    to_pdf(doc, "tender.pdf")                                  # German labels and numbers
    to_pdf(doc, "tender-en.pdf", style=PdfStyle(locale="en"))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from pygaeb.convert._lv import LABELS, Block, Heading, Total, build_lv, check_locale, number
from pygaeb.models.boq import BoQCtgy, Lot
from pygaeb.models.document import GAEBDocument

_PAD = 2.0


class PdfTextRole(str, Enum):
    """What a string drawn by :func:`to_pdf` is."""

    TITLE = "title"
    META = "meta"
    HEADER = "header"
    PAGE_NUMBER = "page_number"
    COLUMN_HEADER = "column_header"
    LOT_NUMBER = "lot_number"
    LOT_LABEL = "lot_label"
    CATEGORY_NUMBER = "category_number"
    CATEGORY_LABEL = "category_label"
    ITEM_NUMBER = "item_number"
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    ITEM_TYPE = "item_type"
    QTY = "qty"
    UNIT = "unit"
    UNIT_PRICE = "unit_price"
    TOTAL_PRICE = "total_price"
    UNIT_PRICE_ONLY = "unit_price_only"
    MARKUP_RATE = "markup_rate"
    SUBTOTAL_LABEL = "subtotal_label"
    SUBTOTAL = "subtotal"
    CARRY_FORWARD_LABEL = "carry_forward_label"
    CARRY_FORWARD = "carry_forward"
    GRAND_TOTAL_LABEL = "grand_total_label"
    GRAND_TOTAL = "grand_total"


@dataclass(frozen=True)
class PdfTextRun:
    """One string drawn on a page, and where it came from.

    Coordinates are PDF points from the bottom-left corner of the page; ``y`` is
    the baseline. ``line`` counts the lines of a wrapped text, starting at 0.
    """

    text: str
    role: PdfTextRole
    page: int
    x: float
    y: float
    width: float
    font: str
    size: float
    item: BaseModel | None = None
    category: BoQCtgy | None = None
    lot: Lot | None = None
    line: int = 0


@dataclass(frozen=True)
class PdfStyle:
    """Layout settings for :func:`to_pdf`. Lengths are PDF points (1 cm ≈ 28.35 pt).

    The default fonts are the PDF standard fonts, which cover Western European
    text; register a TrueType font with reportlab and name it here for other scripts.
    """

    locale: Literal["de", "en"] = "de"
    page_size: tuple[float, float] = (595.28, 841.89)  # A4 portrait
    margin: float = 42.52  # 1.5 cm
    font: str = "Helvetica"
    font_bold: str = "Helvetica-Bold"
    font_italic: str = "Helvetica-Oblique"
    font_size: float = 8.0
    title_size: float = 14.0
    leading: float = 1.3
    long_text: bool = True
    carry_forward: bool = True
    #: Relative widths of the OZ, text, quantity, unit, unit price and total columns.
    columns: tuple[float, float, float, float, float, float] = (2.6, 8.8, 2.0, 1.2, 1.8, 2.2)

    def __post_init__(self) -> None:
        check_locale(self.locale)
        if sum(self.columns) <= 0:
            raise ValueError("PdfStyle.columns must have a positive total width.")


@dataclass(frozen=True)
class _Source:
    item: BaseModel | None = None
    category: BoQCtgy | None = None
    lot: Lot | None = None


_NO_SOURCE = _Source()


@dataclass
class _Cell:
    column: int
    text: str
    role: PdfTextRole
    align: Literal["left", "right"] = "left"
    weight: Literal["regular", "bold", "italic"] = "regular"
    line: int = 0
    adds: Decimal | None = None  # joins the running total once drawn


class _Printer:
    """Places text line by line, breaks pages, and reports every string it draws."""

    def __init__(
        self,
        canvas: Any,
        style: PdfStyle,
        string_width: Callable[[str, str, float], float],
        on_text: Callable[[PdfTextRun], None] | None,
        header: tuple[str, str],
        *,
        priced: bool,
    ) -> None:
        self.style = style
        self.labels = LABELS[style.locale]
        self.priced = priced
        self._canvas = canvas
        self._string_width = string_width
        self._on_text = on_text
        self._header = header
        self._carry_forward = priced and style.carry_forward
        self._line = style.font_size * style.leading
        page_width, self._page_height = style.page_size
        scale = (page_width - 2 * style.margin) / sum(style.columns)
        self._edges = [style.margin]
        for width in style.columns:
            self._edges.append(self._edges[-1] + width * scale)
        # Room at the foot of each page for the carry-forward line.
        self._bottom = style.margin + (1.8 * self._line if self._carry_forward else 0.0)
        self._fonts = {
            "regular": style.font,
            "bold": style.font_bold,
            "italic": style.font_italic,
        }
        self.page = 0
        self.y = 0.0
        self.running = Decimal("0")

    def money(self, value: Decimal) -> str:
        return number(value, 2, self.style.locale)

    def wrap(self, text: str, weight: Literal["regular", "bold", "italic"]) -> list[str]:
        """Lines of ``text`` that fit the description column."""
        return self._wrap(
            text, self._fonts[weight], self.style.font_size, self._width_of_column(1)
        )

    def first_page(self, title: str, meta: list[str]) -> None:
        style = self.style
        self._new_page()
        usable = self._edges[-1] - style.margin
        for line, text in enumerate(self._wrap(title, style.font_bold, style.title_size, usable)):
            self._draw(text, style.margin, self.y, PdfTextRole.TITLE, style.font_bold,
                       style.title_size, line=line)
            self.y -= style.title_size * 1.3
        for line, text in enumerate(meta):
            self._draw(text, style.margin, self.y, PdfTextRole.META, style.font,
                       style.font_size, line=line)
            self.y -= self._line
        self.y -= 0.6 * self._line
        self._column_headers()

    def heading(
        self, number: str, label: str, roles: tuple[PdfTextRole, PdfTextRole], source: _Source
    ) -> None:
        self.y -= 0.4 * self._line
        lines = self.wrap(label, "bold") or [""]
        self._keep(len(lines) + 2)  # never strand a heading at the foot of a page
        for line, text in enumerate(lines):
            cells = [_Cell(1, text, roles[1], weight="bold", line=line)]
            if line == 0:
                cells.insert(0, _Cell(0, number, roles[0], weight="bold"))
            self._row(cells, source)
        self.y -= 0.2 * self._line

    def item_block(
        self,
        number: str,
        short: str,
        long: str,
        marker: str | None,
        amounts: list[_Cell],
        source: _Source,
    ) -> None:
        rows = [
            [_Cell(1, text, PdfTextRole.SHORT_TEXT, weight="bold", line=line)]
            for line, text in enumerate(self.wrap(short, "bold") or [""])
        ]
        rows[0].insert(0, _Cell(0, number, PdfTextRole.ITEM_NUMBER))
        if self.style.long_text:
            rows += [
                [_Cell(1, text, PdfTextRole.LONG_TEXT, line=line)]
                for line, text in enumerate(self.wrap(long.strip(), "regular"))
            ]
        if marker:
            rows.append([_Cell(1, marker, PdfTextRole.ITEM_TYPE, weight="italic")])
        rows[-1] += amounts
        self._keep(min(len(rows), 3))
        for cells in rows:
            self._row(cells, source)
        self.y -= 0.4 * self._line

    def total(
        self,
        label: str,
        amount: str,
        roles: tuple[PdfTextRole, PdfTextRole],
        source: _Source,
        *,
        rule: bool = False,
    ) -> None:
        lines = self.wrap(label, "bold") or [""]
        self._keep(len(lines))
        if rule:
            self._rule(self.y + 0.9 * self._line)
        rows = [
            [_Cell(1, text, roles[0], weight="bold", line=line)]
            for line, text in enumerate(lines)
        ]
        rows[-1].append(_Cell(5, amount, roles[1], "right", weight="bold"))
        for cells in rows:
            self._row(cells, source)
        self.y -= 0.6 * self._line

    def finish(self) -> None:
        self._footer()
        self._canvas.showPage()

    def _row(self, cells: list[_Cell], source: _Source) -> None:
        if self.y < self._bottom:
            self._break()
        for cell in cells:
            self._cell(cell, self.y, source)
            if cell.adds is not None:
                self.running += cell.adds
        self.y -= self._line

    def _keep(self, lines: int) -> None:
        if self.y - (lines - 1) * self._line < self._bottom:
            self._break()

    def _break(self) -> None:
        if self._carry_forward:
            self._carry_line(self.style.margin + 0.4 * self._line)
        self._footer()
        self._canvas.showPage()
        self._new_page()
        self._column_headers()
        if self._carry_forward:
            self._carry_line(self.y)
            self.y -= 1.4 * self._line

    def _new_page(self) -> None:
        self.page += 1
        style = self.style
        top = self._page_height - style.margin
        left, right = self._header
        right_width = self._width(right, style.font, style.font_size)
        room = self._edges[-1] - style.margin - right_width - 12
        self._draw(self._fit(left, style.font, style.font_size, room), style.margin, top,
                   PdfTextRole.HEADER, style.font, style.font_size)
        self._draw(right, self._edges[-1] - right_width, top, PdfTextRole.HEADER, style.font,
                   style.font_size, width=right_width)
        self._rule(top - 0.45 * self._line)
        self.y = top - 1.9 * self._line

    def _column_headers(self) -> None:
        labels = self.labels
        role = PdfTextRole.COLUMN_HEADER
        for cell in (
            _Cell(0, labels["oz"], role, weight="bold"),
            _Cell(1, labels["text"], role, weight="bold"),
            _Cell(2, labels["qty"], role, "right", weight="bold"),
            _Cell(3, labels["unit"], role, weight="bold"),
            _Cell(4, labels["unit_price"], role, "right", weight="bold"),
            _Cell(5, labels["total"], role, "right", weight="bold"),
        ):
            self._cell(cell, self.y, _NO_SOURCE)
        self._rule(self.y - 0.45 * self._line)
        self.y -= 1.6 * self._line

    def _carry_line(self, y: float) -> None:
        label = self.labels["carry_forward"]
        self._cell(_Cell(1, label, PdfTextRole.CARRY_FORWARD_LABEL, weight="bold"), y, _NO_SOURCE)
        amount = _Cell(5, self.money(self.running), PdfTextRole.CARRY_FORWARD, "right",
                       weight="bold")
        self._cell(amount, y, _NO_SOURCE)

    def _footer(self) -> None:
        style = self.style
        text = f"{self.labels['page']} {self.page}"
        width = self._width(text, style.font, style.font_size)
        self._draw(text, self._edges[-1] - width, style.margin / 2, PdfTextRole.PAGE_NUMBER,
                   style.font, style.font_size, width=width)

    def _cell(self, cell: _Cell, y: float, source: _Source) -> None:
        font = self._fonts[cell.weight]
        size = self.style.font_size
        width = self._width(cell.text, font, size)
        if cell.align == "right":
            x = self._edges[cell.column + 1] - _PAD - width
        else:
            x = self._edges[cell.column] + _PAD
        self._draw(cell.text, x, y, cell.role, font, size, source, line=cell.line, width=width)

    def _draw(
        self,
        text: str,
        x: float,
        y: float,
        role: PdfTextRole,
        font: str,
        size: float,
        source: _Source = _NO_SOURCE,
        *,
        line: int = 0,
        width: float | None = None,
    ) -> None:
        """The only place text reaches the page, so the callback sees all of it."""
        if not text:
            return
        self._canvas.setFont(font, size)
        self._canvas.drawString(x, y, text)
        if self._on_text is not None:
            self._on_text(PdfTextRun(
                text=text,
                role=role,
                page=self.page,
                x=x,
                y=y,
                width=self._width(text, font, size) if width is None else width,
                font=font,
                size=size,
                item=source.item,
                category=source.category,
                lot=source.lot,
                line=line,
            ))

    def _rule(self, y: float) -> None:
        self._canvas.setLineWidth(0.5)
        self._canvas.line(self.style.margin, y, self._edges[-1], y)

    def _width(self, text: str, font: str, size: float) -> float:
        return float(self._string_width(text, font, size))

    def _width_of_column(self, column: int) -> float:
        return self._edges[column + 1] - self._edges[column] - 2 * _PAD

    def _wrap(self, text: str, font: str, size: float, width: float) -> list[str]:
        lines: list[str] = []
        for paragraph in text.splitlines():
            current = ""
            for word in paragraph.split():
                candidate = f"{current} {word}" if current else word
                if self._width(candidate, font, size) <= width:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                *pieces, current = self._split_word(word, font, size, width)
                lines.extend(pieces)
            lines.append(current)
        return lines

    def _split_word(self, word: str, font: str, size: float, width: float) -> list[str]:
        """Break a word wider than its column; real LV text almost never needs it."""
        pieces: list[str] = []
        while len(word) > 1 and self._width(word, font, size) > width:
            cut = len(word) - 1
            while cut > 1 and self._width(word[:cut], font, size) > width:
                cut -= 1
            pieces.append(word[:cut])
            word = word[cut:]
        pieces.append(word)
        return pieces

    def _fit(self, text: str, font: str, size: float, width: float) -> str:
        if self._width(text, font, size) <= width:
            return text
        while text and self._width(f"{text}…", font, size) > width:
            text = text[:-1]
        return f"{text}…" if text else ""


_HEADING_ROLES = {
    "lot": (PdfTextRole.LOT_NUMBER, PdfTextRole.LOT_LABEL),
    "category": (PdfTextRole.CATEGORY_NUMBER, PdfTextRole.CATEGORY_LABEL),
}
_TOTAL_ROLES = {
    "subtotal": (PdfTextRole.SUBTOTAL_LABEL, PdfTextRole.SUBTOTAL),
    "lot_subtotal": (PdfTextRole.SUBTOTAL_LABEL, PdfTextRole.SUBTOTAL),
    "grand_total": (PdfTextRole.GRAND_TOTAL_LABEL, PdfTextRole.GRAND_TOTAL),
}


def _print_block(printer: _Printer, block: Block) -> None:
    if isinstance(block, Heading):
        source = _Source(category=block.category, lot=block.lot)
        printer.heading(block.number, block.label, _HEADING_ROLES[block.kind], source)
        return
    if isinstance(block, Total):
        source = _Source(category=block.category, lot=block.lot)
        printer.total(block.label, block.amount, _TOTAL_ROLES[block.kind], source,
                      rule=block.kind == "grand_total")
        return
    cells: list[_Cell] = []
    if block.qty is not None:
        cells.append(_Cell(2, block.qty, PdfTextRole.QTY, "right"))
    if block.unit:
        cells.append(_Cell(3, block.unit, PdfTextRole.UNIT))
    if block.unit_price is not None:
        role = PdfTextRole.MARKUP_RATE if block.rate else PdfTextRole.UNIT_PRICE
        cells.append(_Cell(4, block.unit_price, role, "right"))
    if block.total is not None:
        role = PdfTextRole.UNIT_PRICE_ONLY if block.unit_price_only else PdfTextRole.TOTAL_PRICE
        cells.append(_Cell(5, block.total, role, "right", adds=block.amount))
    source = _Source(item=block.item, category=block.category, lot=block.lot)
    printer.item_block(block.number, block.short_text, block.long_text, block.marker, cells,
                       source)


def to_pdf(
    doc: GAEBDocument,
    path: str | Path,
    title: str | None = None,
    *,
    style: PdfStyle | None = None,
    on_text: Callable[[PdfTextRun], None] | None = None,
) -> None:
    """Render a GAEB document as a printable PDF.

    Args:
        doc: The document to render.
        path: Output PDF file path.
        title: Document title (defaults to the project name).
        style: Layout settings; German labels and number format by default.
        on_text: Called with a :class:`PdfTextRun` for every string drawn, in
            drawing order.

    Raises:
        ImportError: If ``reportlab`` is not installed.
    """
    try:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as e:
        raise ImportError(
            "PDF export requires reportlab. Install with: pip install pyGAEB[pdf]"
        ) from e

    style = style or PdfStyle()
    lv = build_lv(doc, style.locale, title)

    canvas = Canvas(str(Path(path)), pagesize=style.page_size)
    canvas.setTitle(lv.title)
    printer = _Printer(canvas, style, stringWidth, on_text, (lv.title, lv.version),
                       priced=lv.priced)
    printer.first_page(lv.title, lv.meta)
    for block in lv.blocks:
        _print_block(printer, block)
    printer.finish()
    canvas.save()


__all__ = ["PdfStyle", "PdfTextRole", "PdfTextRun", "to_pdf"]
