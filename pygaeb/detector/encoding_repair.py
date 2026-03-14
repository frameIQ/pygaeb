"""Pre-parse encoding repair via ftfy (XML tracks) + charset-normalizer (binary detection)."""

from __future__ import annotations

import logging
import re

import ftfy
from charset_normalizer import from_bytes

logger = logging.getLogger("pygaeb.detector")

_BOM_UTF8 = b"\xef\xbb\xbf"
_BOM_UTF16_LE = b"\xff\xfe"
_BOM_UTF16_BE = b"\xfe\xff"
_XML_DECL_RE = re.compile(
    rb'<\?xml[^>]*encoding=["\']([^"\']+)["\']', re.IGNORECASE
)


def repair_encoding(raw: bytes, is_xml: bool = True) -> tuple[str, str]:
    """Repair encoding issues in raw file bytes.

    Returns (repaired_text, detected_encoding).
    """
    detected_encoding = "utf-8"

    raw, detected_encoding = _strip_bom(raw, detected_encoding)

    if is_xml:
        declared_enc = _extract_declared_encoding(raw)
        try:
            text = raw.decode(declared_enc or "utf-8")
        except (UnicodeDecodeError, LookupError):
            text = _detect_and_decode(raw)
            detected_encoding = "repaired"

        repaired = ftfy.fix_text(text)
        if repaired != text:
            logger.debug("ftfy repaired encoding issues")
            detected_encoding = "repaired-ftfy"
        return repaired, detected_encoding
    else:
        return _detect_and_decode_binary(raw)


def _strip_bom(raw: bytes, default_enc: str) -> tuple[bytes, str]:
    if raw.startswith(_BOM_UTF8):
        return raw[3:], "utf-8-sig"
    if raw.startswith(_BOM_UTF16_LE):
        return raw[2:], "utf-16-le"
    if raw.startswith(_BOM_UTF16_BE):
        return raw[2:], "utf-16-be"
    return raw, default_enc


def _extract_declared_encoding(raw: bytes) -> str | None:
    match = _XML_DECL_RE.search(raw[:200])
    if match:
        return match.group(1).decode("ascii", errors="ignore")
    return None


def _detect_and_decode(raw: bytes) -> str:
    """Attempt decoding with charset-normalizer fallback."""
    for enc in ("utf-8", "windows-1252", "iso-8859-1", "iso-8859-15"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    result = from_bytes(raw)
    best = result.best()
    if best is not None:
        return str(best)
    return raw.decode("utf-8", errors="replace")


def _detect_and_decode_binary(raw: bytes) -> tuple[str, str]:
    """Detect encoding from raw bytes (for GAEB 90 / non-XML)."""
    result = from_bytes(raw)
    best = result.best()
    if best is not None:
        return str(best), best.encoding
    return raw.decode("utf-8", errors="replace"), "utf-8-fallback"
