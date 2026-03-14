"""Format detection: DA XML (2.x/3.x) vs GAEB 90 fixed-width routing."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger("pygaeb.detector")


class FormatFamily(str, Enum):
    DA_XML = "DA_XML"
    GAEB_90 = "GAEB_90"
    UNKNOWN = "UNKNOWN"


class ParserTrack(str, Enum):
    TRACK_A = "TrackA"  # DA XML 2.x (German elements)
    TRACK_B = "TrackB"  # DA XML 3.x (English elements)
    TRACK_C = "TrackC"  # GAEB 90 fixed-width


def detect_format(path: str | Path) -> FormatFamily:
    """Sniff the first 512 bytes of a file to determine the format family."""
    path = Path(path)
    try:
        header = path.read_bytes()[:512]
    except OSError as e:
        logger.error("Cannot read file %s: %s", path, e)
        return FormatFamily.UNKNOWN

    header_lower = header.lower()

    if b"<?xml" in header_lower or b"<gaeb" in header_lower:
        logger.debug("Detected DA XML family for %s", path.name)
        return FormatFamily.DA_XML

    if _looks_like_gaeb90(header):
        logger.debug("Detected GAEB 90 family for %s", path.name)
        return FormatFamily.GAEB_90

    ext = path.suffix.upper()
    if ext in (".X83", ".X84", ".X86", ".X89", ".X80", ".X81", ".X82", ".X85",
               ".X31", ".D83", ".D84", ".D86", ".D89", ".D80", ".D81", ".D82",
               ".D85", ".D31", ".P83", ".P84"):
        logger.debug("Detected DA XML from extension %s", ext)
        return FormatFamily.DA_XML

    logger.warning("Unknown format for %s", path.name)
    return FormatFamily.UNKNOWN


def _looks_like_gaeb90(header: bytes) -> bool:
    """Heuristic: GAEB 90 files have 80-char fixed-width lines."""
    lines = header.split(b"\n")
    if len(lines) < 2:
        lines = header.split(b"\r\n")
    valid_lines = 0
    for line in lines[:5]:
        stripped = line.rstrip(b"\r")
        if len(stripped) == 80 or (76 <= len(stripped) <= 82):
            valid_lines += 1
    return valid_lines >= 2
