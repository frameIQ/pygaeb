"""Format detection: DA XML (2.x/3.x), GAEB 90 fixed-width, and the formats
pyGAEB refuses with a clear error (GAEB 2000, ÖNORM)."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from pygaeb.detector.encoding_repair import sniff_unicode

logger = logging.getLogger("pygaeb.detector")

# .P8x is GAEB 2000, a format pyGAEB does not read.
_GAEB_2000_EXTENSIONS = frozenset({".P81", ".P82", ".P83", ".P84", ".P85", ".P86"})


class FormatFamily(str, Enum):
    DA_XML = "DA_XML"
    GAEB_90 = "GAEB_90"
    GAEB_2000 = "GAEB_2000"
    ONORM_B2063 = "ONORM_B2063"
    UNKNOWN = "UNKNOWN"


class ParserTrack(str, Enum):
    TRACK_A = "TrackA"  # DA XML 2.x (German elements)
    TRACK_B = "TrackB"  # DA XML 3.x (English elements)
    TRACK_C = "TrackC"  # GAEB 90 fixed-width


#: How much of a file the format is read from.
HEADER_BYTES = 512


def detect_format(path: str | Path) -> FormatFamily:
    """Sniff the first 512 bytes of a file to determine the format family."""
    path = Path(path)
    try:
        with path.open("rb") as file:
            header = file.read(HEADER_BYTES)
    except OSError as e:
        logger.error("Cannot read file %s: %s", path, e)
        return FormatFamily.UNKNOWN
    return format_of(header, path.name)


def format_of(header: bytes, name: str = "") -> FormatFamily:
    """The format family of a file that starts with *header* and is called *name*.

    The content decides; *name*'s extension only settles what the first bytes
    leave open. An empty *name* (bytes without a file name) has no extension.
    """
    header = header[:HEADER_BYTES]
    path = Path(name)
    label = name or "<bytes>"

    # Checked as UTF-8, so a UTF-16 file's "<?xml" matches below.
    encoding, body = sniff_unicode(header)
    view = body.decode(encoding, errors="ignore").encode("utf-8") if encoding else header
    header_lower = view.lower()

    # The GAEB root decides first: AVA tools that export both standards name
    # ÖNORM in ProgSystem or project texts, inside these 512 bytes.
    if b"<gaeb" in header_lower:
        logger.debug("Detected DA XML family for %s", label)
        return FormatFamily.DA_XML

    # ÖNORM B 2063 (Austrian standard) — distinct from German GAEB
    if b"onorm" in header_lower or b"\xc3\x96norm" in header_lower or b"b 2063" in header_lower:
        logger.debug("Detected ÖNORM B 2063 for %s", label)
        return FormatFamily.ONORM_B2063
    if path.suffix.lower() in (".onlv", ".onlb"):
        logger.debug("Detected ÖNORM B 2063 from extension for %s", label)
        return FormatFamily.ONORM_B2063

    if b"<?xml" in header_lower:
        logger.debug("Detected DA XML family for %s", label)
        return FormatFamily.DA_XML

    if _looks_like_gaeb90(header):
        logger.debug("Detected GAEB 90 family for %s", label)
        return FormatFamily.GAEB_90

    ext = path.suffix.upper()
    if ext in _GAEB_2000_EXTENSIONS:
        # Neither XML nor fixed-width, under a GAEB 2000 extension: refused
        # clearly instead of failing later as malformed XML.
        logger.debug("Detected GAEB 2000 from extension %s", ext)
        return FormatFamily.GAEB_2000
    if ext in (".X83", ".X84", ".X86", ".X89", ".X80", ".X81", ".X82", ".X85",
               ".X31", ".D83", ".D84", ".D86", ".D89", ".D80", ".D81", ".D82",
               ".D85", ".D31"):
        logger.debug("Detected DA XML from extension %s", ext)
        return FormatFamily.DA_XML

    logger.warning("Unknown format for %s", label)
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
