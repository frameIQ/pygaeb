"""Markdown export: an LV as headings, positions and sums, to read or to give an LLM.

Uses the same walk as the PDF printout, so headings, sums, the "Nur Einh.-Preis"
rule and markup rates read the same in every format.

Usage::

    from pygaeb import GAEBParser
    from pygaeb.convert.to_markdown import to_markdown

    doc = GAEBParser.parse("tender.X83")
    text = to_markdown(doc)                          # the Markdown, as a string
    to_markdown(doc, "tender.md", locale="en")       # also written to a file
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pygaeb.convert._lv import Heading, Lv, Position, Total, build_lv
from pygaeb.models.document import GAEBDocument

_INLINE = re.compile(r"([\\`*_\[\]<>])")
_LINE_START = re.compile(r"^(\s*)([#>])", re.MULTILINE)


def _escape(text: str) -> str:
    """Keep document text literal: no accidental emphasis, links, headings or quotes."""
    return _LINE_START.sub(r"\1\\\2", _INLINE.sub(r"\\\1", text))


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _amounts(block: Position, labels: dict[str, str]) -> str:
    parts: list[str] = []
    if block.marker:
        parts.append(f"*{_escape(block.marker)}*")
    unit = _escape(block.unit or "")
    if block.qty is not None:
        parts.append(" ".join(p for p in (labels["qty"], block.qty, unit) if p))
    elif unit:
        parts.append(unit)
    if block.unit_price is not None:
        label = labels["rate"] if block.rate else labels["unit_price"]
        parts.append(f"{label} {block.unit_price}")
    if block.total is not None:
        parts.append(block.total if block.unit_price_only else f"{labels['total']} {block.total}")
    return " · ".join(parts)


def render_markdown(lv: Lv, *, long_text: bool = True) -> str:
    """Markdown for an LV walked by :func:`pygaeb.convert._lv.build_lv`."""
    out = [f"# {_escape(lv.title)}", "", " · ".join(_escape(m) for m in lv.meta), ""]
    for block in lv.blocks:
        if isinstance(block, Heading):
            level = "#" * min(2 + block.depth, 6)
            text = " ".join(p for p in (block.number, block.label) if p)
            out += [f"{level} {_escape(text)}", ""]
        elif isinstance(block, Total):
            out += [f"**{_escape(block.label)}: {block.amount}**", ""]
        else:
            name = " ".join(p for p in (block.number, block.short_text) if p)
            out += [f"**{_escape(name)}**", ""]
            if long_text:
                for line in _lines(block.long_text):
                    out += [_escape(line), ""]
            amounts = _amounts(block, lv.labels)
            if amounts:
                out += [amounts, ""]
    return "\n".join(out).rstrip() + "\n"


def to_markdown(
    doc: GAEBDocument,
    path: str | Path | None = None,
    title: str | None = None,
    *,
    locale: Literal["de", "en"] = "de",
    long_text: bool = True,
) -> str:
    """Render a GAEB document as Markdown.

    Args:
        doc: The document to render.
        path: If given, the Markdown is also written there (UTF-8).
        title: Document title (defaults to the project name).
        locale: Labels and number format: ``"de"`` (default) or ``"en"``.
        long_text: Include the long texts.

    Returns:
        The Markdown text.
    """
    text = render_markdown(build_lv(doc, locale, title), long_text=long_text)
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


__all__ = ["to_markdown"]
