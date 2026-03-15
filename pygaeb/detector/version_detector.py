"""Version detection: reads GAEBInfo/@Version, namespace URI, and file extension."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from pygaeb.detector.format_detector import FormatFamily, ParserTrack, detect_format
from pygaeb.models.enums import ExchangePhase, SourceVersion

logger = logging.getLogger("pygaeb.detector")

_NS_VERSION_RE = re.compile(r"/(\d+\.\d+)/?")
_NS_PHASE_RE = re.compile(r"/((?:DA|D|X)\w+)/", re.IGNORECASE)

_GAEB_NAMESPACES = {
    "http://www.gaeb.de/GAEB_DA_XML/200407": SourceVersion.DA_XML_20,
    "http://www.gaeb.de/GAEB_DA_XML/200511": SourceVersion.DA_XML_21,
}

_PHASE_FROM_EXT: dict[str, ExchangePhase] = {
    ".X80": ExchangePhase.X80,
    ".X81": ExchangePhase.X81,
    ".X82": ExchangePhase.X82,
    ".X83": ExchangePhase.X83,
    ".X84": ExchangePhase.X84,
    ".X85": ExchangePhase.X85,
    ".X86": ExchangePhase.X86,
    ".X89": ExchangePhase.X89,
    ".X31": ExchangePhase.X31,
    # Trade phases
    ".X93": ExchangePhase.X93,
    ".X94": ExchangePhase.X94,
    ".X96": ExchangePhase.X96,
    ".X97": ExchangePhase.X97,
    # Cost & Calculation phases
    ".X50": ExchangePhase.X50,
    ".X51": ExchangePhase.X51,
    ".X52": ExchangePhase.X52,
    # DA XML 2.x D-prefixed aliases
    ".D80": ExchangePhase.D80,
    ".D81": ExchangePhase.D81,
    ".D82": ExchangePhase.D82,
    ".D83": ExchangePhase.D83,
    ".D84": ExchangePhase.D84,
    ".D85": ExchangePhase.D85,
    ".D86": ExchangePhase.D86,
    ".D89": ExchangePhase.D89,
    ".D31": ExchangePhase.D31,
}


@dataclass
class ParseRoute:
    """Result of format/version detection — gates all downstream parsing."""

    format_family: FormatFamily
    track: ParserTrack
    version: SourceVersion
    exchange_phase: ExchangePhase
    namespace: str | None = None
    encoding_info: str = "utf-8"
    warnings: list[str] = field(default_factory=list)


def detect_version(path: str | Path, text: str | None = None) -> ParseRoute:
    """Detect format, version, and exchange phase from a GAEB file."""
    path = Path(path)
    fmt = detect_format(path)

    if fmt == FormatFamily.GAEB_90:
        return ParseRoute(
            format_family=FormatFamily.GAEB_90,
            track=ParserTrack.TRACK_C,
            version=SourceVersion.GAEB_90,
            exchange_phase=_phase_from_extension(path),
        )

    if fmt == FormatFamily.UNKNOWN:
        return ParseRoute(
            format_family=FormatFamily.UNKNOWN,
            track=ParserTrack.TRACK_B,
            version=SourceVersion.DA_XML_33,
            exchange_phase=_phase_from_extension(path),
            warnings=["Unknown format — defaulting to DA XML 3.3"],
        )

    return _detect_xml_version(path, text)


def _detect_xml_version(path: Path, text: str | None = None) -> ParseRoute:
    """Parse XML header to extract version and namespace."""
    warnings: list[str] = []
    namespace: str | None = None
    version: SourceVersion | None = None
    phase = _phase_from_extension(path)

    try:
        raw = text.encode("utf-8") if text is not None else path.read_bytes()

        for _event, elem in etree.iterparse(
            source=_bytes_io(raw),
            events=("start",),
        ):
            tag = _local_tag(elem.tag)
            ns = _extract_ns(elem.tag)

            if namespace is None and ns:
                namespace = ns
                ns_version = _version_from_namespace(ns)
                if ns_version:
                    version = ns_version

            if tag == "GAEBInfo" or tag == "GAEB":
                v = elem.get("Version") or elem.get("version")
                if v:
                    version = _parse_version_string(v)

            if tag == "GAEB":
                v = elem.get("Version") or elem.get("version")
                if v:
                    version = _parse_version_string(v)

            if tag in ("Award", "Order", "ElementalCosting", "QtyDeterm",
                       "Vergabe", "BoQ", "Leistungsverzeichnis", "GAEBInfo",
                       "GAEB"):
                if tag in ("Vergabe", "Leistungsverzeichnis"):
                    if version is None:
                        version = SourceVersion.DA_XML_20
                    break
                if tag == "Order" and phase == ExchangePhase.X83:
                    phase_from_ns = _phase_from_namespace(namespace or "")
                    if phase_from_ns is not None:
                        phase = phase_from_ns
                if tag == "ElementalCosting" and phase == ExchangePhase.X83:
                    phase_from_ns = _phase_from_namespace(namespace or "")
                    if phase_from_ns is not None:
                        phase = phase_from_ns
                if tag == "QtyDeterm" and phase == ExchangePhase.X83:
                    phase_from_ns = _phase_from_namespace(namespace or "")
                    phase = phase_from_ns if phase_from_ns is not None else ExchangePhase.X31
                if version is not None:
                    break
            elem.clear()

    except etree.XMLSyntaxError as e:
        warnings.append(f"XML parse error during detection: {e}")
    except Exception as e:
        warnings.append(f"Detection error: {e}")

    if version is None:
        version = _guess_version_from_extension(path)
        if version is None:
            version = SourceVersion.DA_XML_33
            warnings.append("Could not detect version — defaulting to 3.3")

    track = _track_for_version(version)

    return ParseRoute(
        format_family=FormatFamily.DA_XML,
        track=track,
        version=version,
        exchange_phase=phase,
        namespace=namespace,
        warnings=warnings,
    )


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_ns(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def _bytes_io(raw: bytes) -> object:
    import io
    return io.BytesIO(raw)


def _version_from_namespace(ns: str) -> SourceVersion | None:
    if ns in _GAEB_NAMESPACES:
        return _GAEB_NAMESPACES[ns]
    match = _NS_VERSION_RE.search(ns)
    if match:
        v = match.group(1)
        return _parse_version_string(v)
    return None


def _parse_version_string(v: str) -> SourceVersion | None:
    v = v.strip()
    version_map = {
        "2.0": SourceVersion.DA_XML_20,
        "2.1": SourceVersion.DA_XML_21,
        "3.0": SourceVersion.DA_XML_30,
        "3.1": SourceVersion.DA_XML_31,
        "3.2": SourceVersion.DA_XML_32,
        "3.3": SourceVersion.DA_XML_33,
    }
    return version_map.get(v)


def _track_for_version(version: SourceVersion) -> ParserTrack:
    if version in (SourceVersion.DA_XML_20, SourceVersion.DA_XML_21):
        return ParserTrack.TRACK_A
    if version == SourceVersion.GAEB_90:
        return ParserTrack.TRACK_C
    return ParserTrack.TRACK_B


def _phase_from_extension(path: Path) -> ExchangePhase:
    ext = path.suffix.upper()
    return _PHASE_FROM_EXT.get(ext, ExchangePhase.X83)


_NS_TRADE_PHASE_MAP: dict[str, ExchangePhase] = {
    "DA93": ExchangePhase.X93,
    "DA94": ExchangePhase.X94,
    "DA96": ExchangePhase.X96,
    "DA97": ExchangePhase.X97,
}


def _phase_from_namespace(ns: str) -> ExchangePhase | None:
    match = _NS_PHASE_RE.search(ns)
    if match:
        phase_str = match.group(1).upper()
        if phase_str in _NS_TRADE_PHASE_MAP:
            return _NS_TRADE_PHASE_MAP[phase_str]
        if phase_str.startswith("DA"):
            phase_str = "X" + phase_str[2:]
        try:
            return ExchangePhase(phase_str)
        except ValueError:
            pass
    return None


def _guess_version_from_extension(path: Path) -> SourceVersion | None:
    ext = path.suffix.upper()
    if ext.startswith(".D"):
        return SourceVersion.DA_XML_20
    if ext.startswith(".X"):
        return SourceVersion.DA_XML_33
    return None
