"""Version detection: what a GAEB file declares about its version and exchange phase.

The file says what it is. ``<GAEBInfo><Version>`` gives the DA XML version and
the payload's ``<DP>`` (``<Award><DP>86</DP>``) the exchange phase. From 3.2 on
the namespace names both (``…/DA86/3.3``); before that one dated namespace
served several versions (BVBS's 3.1 test files carry ``…/200407``, the 2.0
namespace). The file name's extension is only a fallback: for GAEB 90, which
is not XML, and for files that declare nothing. Where they disagree the
content wins, and the route carries a warning that the parse reports.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from pygaeb.detector.encoding_repair import declare_utf8, decode_xml
from pygaeb.detector.format_detector import FormatFamily, ParserTrack, format_of
from pygaeb.models.enums import DocumentKind, ExchangePhase, SourceVersion
from pygaeb.parser._xml_safety import safe_iterparse

logger = logging.getLogger("pygaeb.detector")

#: Namespaces from before 3.2, each shared by several versions: ``<Version>``
#: decides, these are the guesses without one. The writer uses 200407 for 2.0
#: to 3.0, BVBS's 3.1 files use it too, and the GXML Toolbox writes 3.1 as 200706.
_DATED_NAMESPACES: dict[str, SourceVersion] = {
    "http://www.gaeb.de/GAEB_DA_XML/200407": SourceVersion.DA_XML_20,
    "http://www.gaeb.de/GAEB_DA_XML/200511": SourceVersion.DA_XML_21,
    "http://www.gaeb.de/GAEB_DA_XML/200706": SourceVersion.DA_XML_31,
}
#: From 3.2 on (and in pyGAEB's own 3.1 output): one namespace per phase and version.
_PHASE_NAMESPACE = re.compile(r"/DA([0-9A-Za-z.]+)/(\d+\.\d+)/?$")

_VERSIONS: dict[str, SourceVersion] = {
    v.value: v for v in SourceVersion if v is not SourceVersion.GAEB_90
}

#: The elements that open a document's payload, by the kind of document.
_PAYLOADS: dict[str, DocumentKind] = {
    "Award": DocumentKind.PROCUREMENT,
    "Vergabe": DocumentKind.PROCUREMENT,  # DA XML 2.x
    "Order": DocumentKind.TRADE,
    "ElementalCosting": DocumentKind.COST,
    "QtyDeterm": DocumentKind.QUANTITY,
}
_GERMAN_PAYLOADS = frozenset({"Vergabe"})
#: Payload children that open the body: a payload's <DP> comes before them.
_BODIES = frozenset({"BoQ", "Leistungsverzeichnis", "OrderItem", "ECBody"})

#: The phase a document of each kind is read as when it declares none.
_DEFAULT_PHASES: dict[DocumentKind, ExchangePhase] = {
    DocumentKind.PROCUREMENT: ExchangePhase.X83,
    DocumentKind.TRADE: ExchangePhase.X96,
    DocumentKind.COST: ExchangePhase.X50,
    DocumentKind.QUANTITY: ExchangePhase.X31,
}
#: DP codes with more detail than pyGAEB's phases keep.
_DP_ALIASES = {"50.1": "50", "50.2": "50", "51.1": "51", "51.2": "51"}
#: Phases pyGAEB has no model for, read as the nearest one it has.
_READ_AS: dict[str, tuple[ExchangePhase, str]] = {
    "87": (ExchangePhase.X86, "Auftragsbestätigung, the award confirmed"),
}

# Hard upper bound on the events detection reads. A GAEB header (root,
# GAEBInfo, PrjInfo, the payload up to its <DP>) is a few dozen elements; the
# limit only matters for XML that carries no GAEB header.
_MAX_HEADER_EVENTS = 1000

_PHASE_FROM_EXT: dict[str, ExchangePhase] = {
    f".{phase.value}": phase for phase in ExchangePhase
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


@dataclass
class _Header:
    """What the start of a DA XML file declares."""

    namespace: str | None = None
    version: str | None = None
    payload: str | None = None
    dp: str | None = None


def detect_version(path: str | Path, text: str | None = None) -> ParseRoute:
    """Detect format, version, and exchange phase from a GAEB file."""
    path = Path(path)
    return detect_route(path.read_bytes(), path.name, text=text)


def detect_route(
    data: bytes, filename: str | None = None, *, text: str | None = None,
) -> ParseRoute:
    """Detect format, version and exchange phase of *data*, a file called *filename*.

    *filename* contributes only its extension, for what the file does not
    declare itself; without one, the content alone decides. *text*, when
    given, is the decoded XML.
    """
    suffix = Path(filename).suffix.upper() if filename else ""
    named = _PHASE_FROM_EXT.get(suffix)
    fmt = format_of(data, filename or "")

    if fmt == FormatFamily.DA_XML:
        xml = declare_utf8(text) if text is not None else decode_xml(data)[0]
        return _detect_xml(xml.encode("utf-8"), named)

    warnings: list[str] = []
    if fmt == FormatFamily.ONORM_B2063:
        warnings.append(
            "ÖNORM B 2063 (Austrian standard) is not supported. "
            "pyGAEB only handles German GAEB DA XML files. "
            "Please convert ÖNORM files to GAEB format using "
            "an Austrian AVA tool such as ABK or California.pro."
        )
    elif fmt == FormatFamily.GAEB_2000:
        warnings.append(
            "GAEB 2000 (.P8x) is not supported. pyGAEB reads GAEB DA XML and GAEB 90."
        )
    elif fmt == FormatFamily.UNKNOWN:
        warnings.append("Unknown format — defaulting to DA XML 3.3")

    if named is None:
        phase = ExchangePhase.X83
        # pyGAEB does not read the phase from a GAEB 90 file yet: the name gives it.
        if fmt == FormatFamily.GAEB_90 and filename:
            warnings.append(
                f"The name {filename} gives no GAEB 90 phase (.D81 to .D86); read as X83"
            )
        elif fmt == FormatFamily.GAEB_90:
            warnings.append(
                "GAEB 90 data without a file name gives no phase; read as X83. "
                "Pass its name (.D81 to .D86) to read another phase"
            )
    else:
        phase = named
    is_90 = fmt == FormatFamily.GAEB_90
    return ParseRoute(
        format_family=fmt,
        track=ParserTrack.TRACK_C if is_90 else ParserTrack.TRACK_B,
        version=SourceVersion.GAEB_90 if is_90 else SourceVersion.DA_XML_33,
        exchange_phase=phase,
        warnings=warnings,
    )


def _detect_xml(xml: bytes, named: ExchangePhase | None) -> ParseRoute:
    """Route a DA XML file by what its header declares."""
    warnings: list[str] = []
    header = _read_header(xml, warnings)
    version = _decide_version(header, warnings)
    phase = _decide_phase(header, named, warnings)
    return ParseRoute(
        format_family=FormatFamily.DA_XML,
        track=_track_for_version(version),
        version=version,
        exchange_phase=phase,
        namespace=header.namespace,
        # The namespace and <DP> can both name an unsupported phase.
        warnings=list(dict.fromkeys(warnings)),
    )


def _read_header(xml: bytes, warnings: list[str]) -> _Header:
    """Read the namespace, <Version>, payload element and <DP>, then stop.

    Stops at the payload's <DP>, or where its body begins, so a large file is
    not read beyond its first few dozen elements.
    """
    header = _Header()
    stack: list[str] = []
    try:
        # NOTE: no elem.clear() here. On "start" events the element still shares
        # nodes with libxml2's open stack; clearing it corrupts the heap (#44).
        for events_seen, (event, elem) in enumerate(
            safe_iterparse(source=io.BytesIO(xml), events=("start", "end")),
            start=1,
        ):
            tag = _local_tag(elem.tag)
            if event == "start":
                stack.append(tag)
                depth = len(stack)
                if depth == 1:
                    header.namespace = _extract_ns(elem.tag)
                elif depth == 2 and tag in _PAYLOADS and header.payload is None:
                    header.payload = tag
                elif depth == 3 and stack[1] == header.payload and tag in _BODIES:
                    break
            else:
                depth = len(stack)
                if depth == 3 and stack[1] == "GAEBInfo" and tag == "Version":
                    header.version = (elem.text or "").strip() or None
                elif depth == 3 and stack[1] == header.payload and tag == "DP":
                    header.dp = (elem.text or "").strip() or None
                    break
                stack.pop()
                if depth == 2 and tag == header.payload:
                    break
            if events_seen >= _MAX_HEADER_EVENTS:
                warnings.append(
                    f"No GAEB phase element within the first {_MAX_HEADER_EVENTS} "
                    "elements — stopped version detection"
                )
                break
    except etree.XMLSyntaxError as e:
        warnings.append(f"XML parse error during detection: {e}")
    except (etree.LxmlError, ValueError, LookupError) as e:
        warnings.append(f"Detection error: {e}")
    return header


def _decide_version(header: _Header, warnings: list[str]) -> SourceVersion:
    """The version the namespace names, else the one <Version> declares."""
    declared = _VERSIONS.get(header.version or "")
    if header.version and declared is None:
        warnings.append(
            f"<Version>{header.version[:20]}</Version> is not a DA XML version "
            "pyGAEB reads (2.0 to 3.3)"
        )
    version = _version_from_namespace(header, declared, warnings)
    if header.payload in _GERMAN_PAYLOADS and version not in (
        SourceVersion.DA_XML_20, SourceVersion.DA_XML_21,
    ):
        # German element names exist only in 2.x; a 3.x parser would read nothing.
        warnings.append(
            f"The file uses DA XML 2.x element names (<{header.payload}>) but declares "
            f"{version.value}; read as 2.0"
        )
        return SourceVersion.DA_XML_20
    return version


def _version_from_namespace(
    header: _Header, declared: SourceVersion | None, warnings: list[str],
) -> SourceVersion:
    namespace = header.namespace or ""
    match = _PHASE_NAMESPACE.search(namespace)
    if match:
        named = _VERSIONS.get(match.group(2))
        if named is None:
            warnings.append(
                f"Namespace {namespace} is DA XML {match.group(2)}, which pyGAEB does "
                "not read; read as 3.3"
            )
            return SourceVersion.DA_XML_33
        if declared is not None and declared is not named:
            warnings.append(
                f"<Version> says {declared.value} but the namespace {namespace} is "
                f"{named.value}; read as {named.value}"
            )
        return named
    if namespace in _DATED_NAMESPACES:
        if declared is not None:
            return declared
        guess = _DATED_NAMESPACES[namespace]
        warnings.append(
            f"GAEBInfo has no <Version>, and {namespace} serves several versions; "
            f"read as {guess.value}"
        )
        return guess
    if namespace:
        warnings.append(f"Unknown namespace {namespace}")
    if declared is not None:
        return declared
    if header.payload in _GERMAN_PAYLOADS:
        return SourceVersion.DA_XML_20
    warnings.append("Could not detect version — defaulting to 3.3")
    return SourceVersion.DA_XML_33


def _decide_phase(
    header: _Header, named: ExchangePhase | None, warnings: list[str],
) -> ExchangePhase:
    """The phase the namespace or <DP> declares, else the file name's.

    A ``<DP>`` that refines the namespace's phase (``83Z`` in a DA83 file)
    wins; one that contradicts it loses, because the namespace is what a
    schema check goes by.
    """
    kind = _PAYLOADS.get(header.payload or "")
    match = _PHASE_NAMESPACE.search(header.namespace or "")
    from_ns = _phase_from_code(match.group(1), warnings, "namespace") if match else None
    from_dp = _phase_from_code(header.dp, warnings, "<DP>") if header.dp else None

    phase = from_ns or from_dp
    if from_ns and from_dp and from_dp is not from_ns:
        if _number(from_dp) == _number(from_ns):
            phase = from_dp
        else:
            warnings.append(
                f"<DP> says {from_dp.value} but the namespace {header.namespace} is "
                f"{from_ns.value}; read as {from_ns.value}"
            )

    if phase is not None and kind is not None and phase.document_kind is not kind:
        warnings.append(
            f"{phase.value} is no phase of a {kind.value} document (<{header.payload}>); "
            "the phase is ignored"
        )
        phase = None

    by_name = named.normalized() if named is not None else None
    if phase is None:
        if by_name is not None and (kind is None or by_name.document_kind is kind):
            return by_name
        phase = _DEFAULT_PHASES[kind or DocumentKind.PROCUREMENT]
        warnings.append(
            f"The file declares no exchange phase (no <DP>, no phase in its namespace)"
            f"{', and its name gives none that fits' if named else ''}; read as {phase.value}"
        )
        return phase
    if by_name is not None and by_name is not phase:
        warnings.append(
            f"The file name says {by_name.value}, the file itself {phase.value}; "
            f"read as {phase.value}"
        )
    return phase


def _phase_from_code(code: str, warnings: list[str], source: str) -> ExchangePhase | None:
    """The phase a DP code (``86``, ``83Z``, ``50.1``) or namespace part names."""
    text = code.strip().upper()
    # Older pyGAEB wrote a GAEB 90 phase into <DP> as "D83".
    if text[:1] in ("X", "D") and text[1:2].isdigit():
        text = text[1:]
    text = _DP_ALIASES.get(text, text)
    if text in _READ_AS:
        phase, what = _READ_AS[text]
        warnings.append(
            f"Phase {text} ({what}) is not supported; read as {phase.value}"
        )
        return phase
    try:
        return ExchangePhase("X" + text)
    except ValueError:
        warnings.append(f"{source} {code[:20]!r} names no exchange phase pyGAEB reads")
        return None


def _number(phase: ExchangePhase) -> str:
    """``86`` for X86, X86ZR and X86ZE."""
    return phase.normalized().value[1:3]


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_ns(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def _track_for_version(version: SourceVersion) -> ParserTrack:
    if version in (SourceVersion.DA_XML_20, SourceVersion.DA_XML_21):
        return ParserTrack.TRACK_A
    if version == SourceVersion.GAEB_90:
        return ParserTrack.TRACK_C
    return ParserTrack.TRACK_B
