"""Rich text parser for tgBoQText long texts using BeautifulSoup4 + lxml backend."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from pygaeb.models.item import RichText

logger = logging.getLogger("pygaeb.parser")

_TA_RE = re.compile(r"\[TA\]", re.IGNORECASE)
_TB_RE = re.compile(r"\[TB\]", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


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

    paragraphs = _extract_paragraphs(soup)
    tables = _extract_tables(soup)
    plain = _to_plain_text(soup)

    if not paragraphs and not tables and not images and not plain:
        return None

    return RichText(
        paragraphs=paragraphs,
        tables=tables,
        images=images,
        raw_html=html,
        plain_text=plain,
    )


def parse_plaintext(text: str | None) -> RichText | None:
    """Wrap plain text (DA XML 2.x style) into a RichText model."""
    if not text or not text.strip():
        return None
    return RichText.from_plain(text.strip())


def _extract_paragraphs(soup: BeautifulSoup) -> list[str]:
    paragraphs: list[str] = []
    # Innermost blocks only — <p><span>x</span></p> would otherwise yield x twice.
    blocks = [el for el in soup.find_all(["p", "div"]) if el.find(["p", "div"]) is None]
    for p in blocks or soup.find_all("span"):
        text = p.get_text(strip=True)
        if text:
            text = _TA_RE.sub("", text)
            text = _TB_RE.sub("", text)
            text = text.strip()
            if text:
                paragraphs.append(text)

    if not paragraphs:
        text = soup.get_text(strip=True)
        if text:
            text = _TA_RE.sub("", text)
            text = _TB_RE.sub("", text)
            text = text.strip()
            if text:
                paragraphs = [text]

    return paragraphs


def _extract_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for table in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


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


def _to_plain_text(soup: BeautifulSoup) -> str:
    text = soup.get_text(separator="\n", strip=True)
    text = _TA_RE.sub("", text)
    text = _TB_RE.sub("", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
