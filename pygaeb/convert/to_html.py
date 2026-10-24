"""HTML export: an LV as a self-contained page or a fragment to embed in an app.

Uses the same walk as the PDF printout. Every string from the document is escaped,
so a GAEB file cannot inject markup into the page. Rows carry stable classes
(``lv-heading``, ``lv-position``, ``lv-total``) and positions a ``data-oz``
attribute, so an app can style them and link back to the item.

Usage::

    from pygaeb import GAEBParser
    from pygaeb.convert.to_html import to_html

    doc = GAEBParser.parse("tender.X83")
    to_html(doc, "tender.html")                  # a complete page
    fragment = to_html(doc, standalone=False)    # just the LV, to embed
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Literal

from pygaeb.convert._lv import Heading, Lv, Position, Total, build_lv
from pygaeb.models.document import GAEBDocument

_STYLE = """
.lv { font: 14px/1.45 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #1a1a1a; }
.lv h1 { font-size: 1.5em; margin: 0 0 .25em; }
.lv-meta { color: #555; margin: 0 0 1.25em; }
.lv-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.lv-table th, .lv-table td { padding: .3em .5em; vertical-align: bottom; text-align: left; }
.lv-table thead th { border-bottom: 1px solid #1a1a1a; white-space: nowrap; }
.lv-table .num { text-align: right; white-space: nowrap; }
.lv-table .oz { white-space: nowrap; vertical-align: top; }
.lv-heading td { font-weight: 600; padding-top: 1em; }
.lv-position td.text { vertical-align: top; }
.lv-position .short { font-weight: 600; margin: 0; }
.lv-position .long, .lv-position .marker { margin: .2em 0 0; }
.lv-position .marker { font-style: italic; }
.lv-total td { font-weight: 600; }
.lv-grand-total td { border-top: 1px solid #1a1a1a; }
@media print { .lv { font-size: 10pt; } .lv-table thead { display: table-header-group; } }
""".strip()


def _p(css: str, text: str) -> str:
    return f'<p class="{css}">{escape(text)}</p>'


def _row(css: str, cells: list[str], attrs: str = "") -> str:
    return f'<tr class="{css}"{attrs}>{"".join(cells)}</tr>'


def render_html(
    lv: Lv, *, long_text: bool = True, standalone: bool = True, lang: str = "de"
) -> str:
    """HTML for an LV walked by :func:`pygaeb.convert._lv.build_lv`."""
    labels = lv.labels
    head = [
        ("oz", labels["oz"]), ("text", labels["text"]), ("num", labels["qty"]),
        ("unit", labels["unit"]), ("num", labels["unit_price"]), ("num", labels["total"]),
    ]
    rows: list[str] = []
    for block in lv.blocks:
        if isinstance(block, Heading):
            rows.append(_row(f"lv-heading lv-{block.kind} depth-{block.depth}", [
                f'<td class="oz">{escape(block.number)}</td>',
                f'<td class="text" colspan="5">{escape(block.label)}</td>',
            ]))
        elif isinstance(block, Total):
            kind = block.kind.replace("_", "-")
            rows.append(_row(f"lv-total lv-{kind}", [
                '<td class="oz"></td>',
                f'<td class="text" colspan="4">{escape(block.label)}</td>',
                f'<td class="num">{escape(block.amount)}</td>',
            ]))
        else:
            rows.append(_position(block, long_text))
    table = (
        '<table class="lv-table"><thead><tr>'
        + "".join(f'<th class="{css}">{escape(text)}</th>' for css, text in head)
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    body = (
        f'<section class="lv" lang="{escape(lang)}"><h1>{escape(lv.title)}</h1>'
        f'<p class="lv-meta">{escape(" · ".join(lv.meta))}</p>{table}</section>'
    )
    if not standalone:
        return body
    return (
        f'<!DOCTYPE html>\n<html lang="{escape(lang)}"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        f"<title>{escape(lv.title)}</title><style>{_STYLE}</style></head>"
        f"<body>{body}</body></html>\n"
    )


def _position(block: Position, long_text: bool) -> str:
    text = [_p("short", block.short_text)]
    if long_text:
        text += [_p("long", line.strip()) for line in block.long_text.splitlines() if line.strip()]
    if block.marker:
        text.append(_p("marker", block.marker))
    item_id = getattr(block.item, "id", None)
    attrs = f' data-oz="{escape(block.number)}"'
    if item_id:
        attrs += f' data-id="{escape(str(item_id))}"'
    unit_price_css = "num rate" if block.rate else "num"
    total_css = "num unit-price-only" if block.unit_price_only else "num"
    return _row(f"lv-position depth-{block.depth}", [
        f'<td class="oz">{escape(block.number)}</td>',
        f'<td class="text">{"".join(text)}</td>',
        f'<td class="num">{escape(block.qty or "")}</td>',
        f'<td class="unit">{escape(block.unit or "")}</td>',
        f'<td class="{unit_price_css}">{escape(block.unit_price or "")}</td>',
        f'<td class="{total_css}">{escape(block.total or "")}</td>',
    ], attrs)


def to_html(
    doc: GAEBDocument,
    path: str | Path | None = None,
    title: str | None = None,
    *,
    locale: Literal["de", "en"] = "de",
    long_text: bool = True,
    standalone: bool = True,
) -> str:
    """Render a GAEB document as HTML.

    Args:
        doc: The document to render.
        path: If given, the HTML is also written there (UTF-8).
        title: Document title (defaults to the project name).
        locale: Labels and number format: ``"de"`` (default) or ``"en"``.
        long_text: Include the long texts.
        standalone: ``True`` for a complete page with its own styles; ``False`` for a
            ``<section class="lv">`` fragment to embed and style yourself.

    Returns:
        The HTML text.
    """
    text = render_html(build_lv(doc, locale, title), long_text=long_text,
                       standalone=standalone, lang=locale)
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text


__all__ = ["to_html"]
