"""Rich text parser for tgBoQText long texts using BeautifulSoup4 + lxml backend.

The prose is read in one ordered walk rather than block by block, for two reasons
that both cost real text before:

- A line break is part of the text. Standard texts break every line with
  ``<br/>``, and each line's trailing space sits inside its ``<span>``; stripping
  every string glued ``Hinterfüllen`` onto ``von``. Text is now taken verbatim and
  ``<br/>`` becomes ``\\n``. Adjacent spans are *not* separated — a style run can
  split a word, and ``Ver`` + ``dichten`` must stay one word.
- A ``<TextComplement>`` is part of the sentence. The issuer's fields name the
  material or product (``Stoff 'Beton C25/30' oder gleichwertiger Art``) and sit
  between ``<Text>`` blocks, where a block-only reader never looked. They are
  rendered inline, and returned as structure in ``RichText.complements``.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from bs4 import BeautifulSoup
from bs4.element import Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

from pygaeb.models.enums import ComplementKind
from pygaeb.models.item import RichText, TextComplement, join_inline

logger = logging.getLogger("pygaeb.parser")

_TA_RE = re.compile(r"\[TA\]", re.IGNORECASE)
_TB_RE = re.compile(r"\[TB\]", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_HORIZONTAL_SPACE_RE = re.compile(r"[^\S\n]+")

#: Elements that start and end a paragraph. GAEB's own ``<Text>`` is one.
_BLOCKS = frozenset(
    {
        "p", "div", "li", "ul", "ol", "text", "blockquote",
        "h1", "h2", "h3", "h4", "h5", "h6", "body", "html",
    }
)
_FIELD_PARTS = frozenset({"complcaption", "complbody", "compltail", "complbodydec", "complbodyint"})
_NOT_TEXT = (Comment, Declaration, Doctype, ProcessingInstruction)

#: A field body with nothing in it but quote marks, dots, dashes or underscores is
#: blank, whatever ``Empty`` says — several AVA programs mark blanks only with dots.
_PLACEHOLDER_RE = re.compile(r"[\s'\"‚‘’„“”.…_\-]*")  # noqa: RUF001 — German quote marks


def parse_richtext(html: str | None) -> RichText | None:
    """Parse GAEB tgBoQText HTML-like long text into a RichText model."""
    if not html or not html.strip():
        return None

    soup = BeautifulSoup(html, "lxml")

    # Images come out first and are then removed from the tree. GAEB carries a
    # graphic as base64 *inside* the element, so a <p> wrapping one yields the whole
    # blob as its text — tens of kilobytes of base64 landing in the prose, where it
    # is unreadable and drowns the specification it was meant to illustrate.
    images = _extract_images(soup)
    _remove_images(soup)

    complements: list[TextComplement] = []
    plain_lines = _flow(soup, tables_inline=True, complements=complements)
    paragraphs = _flow(soup, tables_inline=False, complements=[])
    tables = _extract_tables(soup)
    plain = "\n".join(line for paragraph in plain_lines for line in paragraph.split("\n"))

    if not paragraphs and not tables and not images and not plain:
        return None

    return RichText(
        paragraphs=paragraphs,
        tables=tables,
        images=images,
        raw_html=html,
        plain_text=plain,
        complements=complements,
    )


def parse_plaintext(text: str | None) -> RichText | None:
    """Wrap plain text (DA XML 2.x style) into a RichText model."""
    if not text or not text.strip():
        return None
    return RichText.from_plain(text.strip())


#: A colon is not among them: ``Fabrikat:`` introduces the field that follows it.
_SENTENCE_END = ".!?;"
_CONTEXT_CHARS = 80


class _Flow:
    """Prose in document order.

    Text is kept verbatim, ``<br/>`` is a line break, and a block edge is a
    paragraph boundary — except where a field sits mid-sentence. Standard texts
    put each field between two ``<Text>`` blocks, so ``Stoffen,`` + field +
    ``oder gleichwertiger Art`` is one sentence across three blocks; a field that
    opens or closes a sentence keeps its paragraph break.
    """

    def __init__(self) -> None:
        self.paragraphs: list[str] = []
        self._parts: list[str] = []
        self._pending = False
        self._after_field = False

    def text(self, value: str) -> None:
        # Only <br/> breaks a line; a newline in the markup is indentation.
        value = _WHITESPACE_RE.sub(" ", value)
        if not value.strip():
            # Whitespace between inline elements is a word gap; between blocks it
            # is only indentation.
            if self._parts and not self._pending:
                self._parts.append(" ")
            return
        if self._pending:
            self._pending = False
            if self._after_field and _continues(self._current(), value):
                self._join(value)
            else:
                self._flush()
                self._parts.append(value)
        elif self._after_field:
            self._join(value)
        else:
            self._parts.append(value)
        self._after_field = False

    def field(self, rendered: str) -> None:
        if self._pending:
            self._pending = False
            last = self._current().rstrip()[-1:]
            if last and last in _SENTENCE_END:
                self._flush()
        self._join(rendered)
        self._after_field = True

    def _current(self) -> str:
        return "".join(self._parts)

    def preceding(self) -> str:
        """The text of the paragraph so far — what a field about to follow is read after."""
        return self._current()

    def line(self) -> None:
        if self._parts and not self._pending:
            self._parts.append("\n")

    def block(self) -> None:
        if self._parts:
            self._pending = True

    def finish(self) -> list[str]:
        self._flush()
        return self.paragraphs

    def _join(self, value: str) -> None:
        current = "".join(self._parts)
        self._parts = [join_inline(current, value)] if current else [value]

    def _flush(self) -> None:
        paragraph = _clean("".join(self._parts))
        if paragraph:
            self.paragraphs.append(paragraph)
        self._parts = []
        self._after_field = False


def _context(text: str) -> str:
    """The last clause before a field: what it is the value of.

    Cut at the last line break or sentence end, trailing colon dropped, so
    ``Fenster, weiß.\nAngebotenes Fabrikat:`` gives ``Angebotenes Fabrikat``.
    """
    clause = _clean(text).split("\n")[-1] if text.strip() else ""
    for mark in ".!?;":
        _, found, rest = clause.rpartition(mark)
        if found and rest.strip():
            clause = rest
    clause = clause.strip().rstrip(":,").strip()
    return clause[-_CONTEXT_CHARS:].strip()


def _continues(left: str, right: str) -> bool:
    """Whether the text after a field carries on the field's sentence."""
    head = right.lstrip()[:1]
    return left.rstrip().endswith(",") or head.islower() or head.isdigit() or (
        bool(head) and head in ",.;:)"
    )


def _flow(
    root: BeautifulSoup, *, tables_inline: bool, complements: list[TextComplement]
) -> list[str]:
    flow = _Flow()
    _walk(root, flow, complements, tables_inline=tables_inline)
    return flow.finish()


def _walk(
    node: Tag, flow: _Flow, complements: list[TextComplement], *, tables_inline: bool
) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            if not isinstance(child, _NOT_TEXT):
                flow.text(str(child))
            continue
        if not isinstance(child, Tag):
            continue

        name = child.name
        if name == "textcomplement":
            complement = _complement(child)
            complement.context = _context(flow.preceding())
            complements.append(complement)
            flow.field(complement.inline)
        elif name == "br":
            flow.line()
        elif name == "table":
            flow.block()
            if tables_inline:
                for row in _table_rows(child, complements):
                    flow.text(" | ".join(row))
                    flow.block()
        elif name in _BLOCKS:
            flow.block()
            _walk(child, flow, complements, tables_inline=tables_inline)
            flow.block()
        else:
            _walk(child, flow, complements, tables_inline=tables_inline)


def _clean(text: str) -> str:
    """Collapse runs of spaces per line, drop empty lines, remove tab markers."""
    text = _TB_RE.sub("", _TA_RE.sub("", text))
    lines = (_HORIZONTAL_SPACE_RE.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _inline(node: Tag | None) -> str:
    """An element's text on one line: verbatim runs, ``<br/>`` as a space, fields inline."""
    if node is None:
        return ""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            if not isinstance(child, _NOT_TEXT):
                parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name == "br":
                parts.append(" ")
            elif child.name == "textcomplement":
                parts.append(f" {_complement(child).inline} ")
            elif child.name not in _FIELD_PARTS:
                parts.append(_inline(child))
    return _WHITESPACE_RE.sub(" ", _TB_RE.sub("", _TA_RE.sub("", "".join(parts)))).strip()


def _complement(tag: Tag) -> TextComplement:
    """One ``<TextComplement>``. Names arrive lowercased from the HTML parser."""
    kind = (
        ComplementKind.BIDDER
        if str(tag.get("kind", "")).strip().lower() == "bidder"
        else ComplementKind.OWNER
    )
    body = _inline(_part(tag, "complbody"))
    empty = str(tag.get("empty", "")).strip().lower() == "yes" or bool(
        _PLACEHOLDER_RE.fullmatch(body)
    )

    typed = _part(tag, "complbodydec") or _part(tag, "complbodyint")
    number_kind: Literal["dec", "int"] | None = None
    if typed is not None:
        number_kind = "dec" if typed.name == "complbodydec" else "int"

    return TextComplement(
        kind=kind,
        mark=str(tag.get("marklbl", "")).strip(),
        caption=_inline(_part(tag, "complcaption")),
        body="" if empty else body,
        tail=_inline(_part(tag, "compltail")),
        empty=empty,
        number=_number(typed.get("value") if typed is not None else None),
        number_kind=number_kind,
        id=_attr(tag, "id"),
        art_chr_ident=_attr(tag, "artchrident"),
    )


def _part(tag: Tag, name: str) -> Tag | None:
    found = tag.find(name)
    return found if isinstance(found, Tag) else None


def _attr(tag: Tag, name: str) -> str | None:
    value = str(tag.get(name, "") or "").strip()
    return value or None


def _number(value: object) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _table_rows(table: Tag, complements: list[TextComplement]) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["td", "th"]):
            for tag in cell.find_all("textcomplement"):
                complements.append(_complement(tag))
            cells.append(_inline(cell))
        if cells:
            rows.append(cells)
    return rows


def _extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
    return [rows for table in soup.find_all("table") if (rows := _table_rows(table, []))]


def _extract_images(soup: BeautifulSoup) -> list[str]:
    """Every graphic in the text, as a data URI ready to render.

    Two shapes appear in the wild. HTML-ish long texts use ``<img src="...">``,
    which is already a URI. GAEB DA XML uses its own ``<image Type="image/jpeg"
    Name="bagger.jpg">`` with the base64 as the element's content — so that one is
    assembled into a data URI here rather than handed on as a bare blob.
    """
    images: list[str] = []

    for img in soup.find_all("img"):
        src = str(img.get("src", "")).strip()
        if src:
            images.append(src)

    for element in soup.find_all("image"):
        encoded = _WHITESPACE_RE.sub("", element.get_text() or "")
        if not encoded:
            continue
        # The attribute is spelled Type in the schema; BeautifulSoup lowercases it.
        mime = str(element.get("type") or element.get("Type") or "image/jpeg").strip()
        images.append(f"data:{mime};base64,{encoded}")

    return images


def _remove_images(soup: BeautifulSoup) -> None:
    """Take the graphics out of the tree so their base64 cannot reach the prose."""
    for element in soup.find_all(["image", "img"]):
        element.decompose()
