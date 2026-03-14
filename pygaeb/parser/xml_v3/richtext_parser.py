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

    paragraphs = _extract_paragraphs(soup)
    tables = _extract_tables(soup)
    images = _extract_images(soup)
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
    for p in soup.find_all(["p", "div", "span"]):
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
    return [
        str(img.get("src", ""))
        for img in soup.find_all("img")
        if img.get("src")
    ]


def _to_plain_text(soup: BeautifulSoup) -> str:
    text = soup.get_text(separator="\n", strip=True)
    text = _TA_RE.sub("", text)
    text = _TB_RE.sub("", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
