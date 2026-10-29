"""Encoding repair before parsing: XML decoded as a parser would, GAEB 90 by detection."""

from __future__ import annotations

import codecs
import logging
import re

import ftfy
from charset_normalizer import from_bytes

logger = logging.getLogger("pygaeb.detector")

# UTF-32 first: its little-endian mark begins with the UTF-16 one.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
_XML_DECL_RE = re.compile(
    rb'\s*<\?xml[^>]*?\bencoding\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE
)
_DECL_ENCODING_RE = re.compile(
    r'﻿?\s*<\?xml[^>]*?\bencoding\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE
)


def repair_encoding(raw: bytes, is_xml: bool = True) -> tuple[str, str]:
    """Repair encoding issues in raw file bytes.

    Returns (repaired_text, detected_encoding). XML text comes back declared
    as UTF-8 (see ``decode_xml``).
    """
    if not is_xml:
        _encoding, body = sniff_unicode(raw)
        return _detect_and_decode_binary(body)

    text, encoding = decode_xml(raw)
    # Typography fixes off: they would rewrite quotes, ligatures and widths in contract text.
    repaired = ftfy.fix_text(
        text, uncurl_quotes=False, fix_latin_ligatures=False, fix_character_width=False,
    )
    if repaired != text:
        logger.debug("ftfy repaired encoding issues")
        encoding = "repaired-ftfy"
    return repaired, encoding


def decode_xml(raw: bytes) -> tuple[str, str]:
    """Decode XML bytes as an XML parser would, surviving a wrong encoding label.

    Returns ``(text, encoding)``. A byte-order mark outranks the declaration,
    and the text's declaration is rewritten to name UTF-8, because callers
    hand ``text.encode("utf-8")`` to lxml.
    """
    text, encoding = decode_xml_as_written(raw)
    return declare_utf8(text), encoding


def decode_xml_as_written(raw: bytes) -> tuple[str, str]:
    """Like ``decode_xml`` but with the declaration left as the file wrote it.

    Source positions are counted on this text: it is what an editor shows.
    """
    encoding, body = sniff_unicode(raw)
    encoding = encoding or _declared_encoding(body) or "utf-8"
    try:
        text = body.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text, encoding = _decode_fallback(body), "repaired"
    return text, encoding


def declare_utf8(text: str) -> str:
    """Make the XML declaration name UTF-8, the encoding callers hand to lxml."""
    match = _DECL_ENCODING_RE.match(text)
    if match is None:
        return text
    return text[: match.start(1)] + "UTF-8" + text[match.end(1):]


def sniff_unicode(raw: bytes) -> tuple[str | None, bytes]:
    """Return the encoding a byte-order mark gives away, and the bytes after the mark.

    Without a mark, UTF-16 is recognised by how it encodes ``<?`` (XML 1.0,
    appendix F).
    """
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return encoding, raw[len(bom):]
    if raw.startswith(b"<\x00?\x00"):
        return "utf-16-le", raw
    if raw.startswith(b"\x00<\x00?"):
        return "utf-16-be", raw
    return None, raw


def _declared_encoding(raw: bytes) -> str | None:
    match = _XML_DECL_RE.match(raw[:200])
    if match is None:
        return None
    try:
        name = codecs.lookup(match.group(1).decode("ascii", errors="ignore")).name
    except LookupError:
        return None
    # The label was readable as ASCII, so the bytes are not UTF-16/32 whatever
    # it says (a common .NET export mistake).
    return None if name.startswith(("utf-16", "utf-32")) else name


def _decode_fallback(raw: bytes) -> str:
    """Bytes their declared encoding rejects: UTF-8, else Windows-1252, else Latin-1."""
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _detect_and_decode_binary(raw: bytes) -> tuple[str, str]:
    """Detect encoding from raw bytes (for GAEB 90 / non-XML)."""
    result = from_bytes(raw)
    best = result.best()
    if best is not None:
        return str(best), best.encoding
    return raw.decode("utf-8", errors="replace"), "utf-8-fallback"
