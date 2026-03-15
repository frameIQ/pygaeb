"""Main entry point: GAEBParser — auto-detects version and routes to correct parser track."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pygaeb.config import get_settings
from pygaeb.detector.encoding_repair import repair_encoding
from pygaeb.detector.format_detector import FormatFamily, ParserTrack
from pygaeb.detector.version_detector import ParseRoute, detect_version
from pygaeb.exceptions import GAEBParseError, GAEBValidationError
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, SourceVersion, ValidationMode, ValidationSeverity
from pygaeb.models.item import ValidationResult

logger = logging.getLogger("pygaeb.parser")


class GAEBParser:
    """Parse any GAEB file — auto-detects version and format.

    Usage:
        doc = GAEBParser.parse("tender.X83")
        doc = GAEBParser.parse("old.D83")
        doc = GAEBParser.parse_bytes(raw, filename="tender.X83")
        doc = GAEBParser.parse_string(xml, filename="tender.X83")
    """

    @staticmethod
    def parse(
        path: str | Path,
        validation: ValidationMode = ValidationMode.LENIENT,
        xsd_dir: str | None = None,
        keep_xml: bool = False,
        max_file_size: int | None = None,
        post_parse_hook: Callable[[Any, Any], None] | None = None,
        collect_raw_data: bool = False,
        extra_validators: list[Callable[[GAEBDocument], list[ValidationResult]]] | None = None,
    ) -> GAEBDocument:
        """Parse a GAEB file from disk and return a unified GAEBDocument.

        Set *keep_xml* to ``True`` to retain raw lxml elements on every
        model (``item.source_element``) and enable ``doc.xpath()``.

        *max_file_size* overrides the configured ``max_file_size_mb``
        limit (in bytes).  Pass ``0`` to disable the check.

        *post_parse_hook* is called with ``(item, source_element)`` for
        every parsed item — useful for extracting vendor-specific XML
        elements into ``item.raw_data``.

        *collect_raw_data* when ``True`` automatically populates
        ``item.raw_data`` with any XML child elements not consumed by
        the built-in parser.

        *extra_validators* are per-call validation functions appended
        after the built-in and globally-registered validators.
        """
        path = Path(path)
        if not path.exists():
            raise GAEBParseError(f"File not found: {path}")

        _enforce_size_limit(path.stat().st_size, max_file_size)

        raw = path.read_bytes()
        route = detect_version(path)
        return _parse_core(
            raw, route, path, validation, xsd_dir, keep_xml,
            post_parse_hook=post_parse_hook,
            collect_raw_data=collect_raw_data,
            extra_validators=extra_validators,
        )

    @staticmethod
    def parse_bytes(
        data: bytes,
        filename: str = "input.X83",
        validation: ValidationMode = ValidationMode.LENIENT,
        xsd_dir: str | None = None,
        keep_xml: bool = False,
        max_file_size: int | None = None,
        post_parse_hook: Callable[[Any, Any], None] | None = None,
        collect_raw_data: bool = False,
        extra_validators: list[Callable[[GAEBDocument], list[ValidationResult]]] | None = None,
    ) -> GAEBDocument:
        """Parse GAEB data from bytes (useful for web uploads, S3 streams, etc.).

        The filename hint is used for version/phase detection from the extension.
        """
        _enforce_size_limit(len(data), max_file_size)
        hint_path = Path(filename)
        with tempfile.NamedTemporaryFile(suffix=hint_path.suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            route = detect_version(tmp_path)
            return _parse_core(
                data, route, hint_path, validation, xsd_dir, keep_xml,
                post_parse_hook=post_parse_hook,
                collect_raw_data=collect_raw_data,
                extra_validators=extra_validators,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def parse_string(
        xml_text: str,
        filename: str = "input.X83",
        validation: ValidationMode = ValidationMode.LENIENT,
        xsd_dir: str | None = None,
        keep_xml: bool = False,
        max_file_size: int | None = None,
        post_parse_hook: Callable[[Any, Any], None] | None = None,
        collect_raw_data: bool = False,
        extra_validators: list[Callable[[GAEBDocument], list[ValidationResult]]] | None = None,
    ) -> GAEBDocument:
        """Parse GAEB data from an XML string.

        The filename hint is used for version/phase detection from the extension.
        """
        return GAEBParser.parse_bytes(
            xml_text.encode("utf-8"), filename, validation, xsd_dir, keep_xml,
            max_file_size,
            post_parse_hook=post_parse_hook,
            collect_raw_data=collect_raw_data,
            extra_validators=extra_validators,
        )


def _enforce_size_limit(size_bytes: int, explicit_limit: int | None) -> None:
    """Raise ``GAEBParseError`` if *size_bytes* exceeds the configured maximum.

    *explicit_limit* (in bytes) overrides the global setting when provided.
    Pass ``0`` to disable the check entirely.
    """
    if explicit_limit is not None:
        limit = explicit_limit
    else:
        limit = get_settings().max_file_size_mb * 1024 * 1024
    if limit > 0 and size_bytes > limit:
        mb = size_bytes / (1024 * 1024)
        limit_mb = limit / (1024 * 1024)
        raise GAEBParseError(
            f"File size ({mb:.1f} MB) exceeds the maximum allowed "
            f"({limit_mb:.0f} MB). Increase max_file_size_mb in settings or "
            f"pass max_file_size=0 to disable."
        )


def _parse_core(
    raw: bytes,
    route: ParseRoute,
    source_path: Path,
    validation: ValidationMode,
    xsd_dir: str | None,
    keep_xml: bool = False,
    *,
    post_parse_hook: Callable[[Any, Any], None] | None = None,
    collect_raw_data: bool = False,
    extra_validators: list[Callable[[GAEBDocument], list[ValidationResult]]] | None = None,
) -> GAEBDocument:
    """Shared parsing pipeline for all entry points."""
    logger.debug(
        "Detected: version=%s track=%s phase=%s for %s",
        route.version, route.track, route.exchange_phase, source_path.name,
    )

    if route.warnings:
        for w in route.warnings:
            logger.warning(w)

    needs_xml_temporarily = (post_parse_hook is not None or collect_raw_data) and not keep_xml
    effective_keep_xml = keep_xml or post_parse_hook is not None or collect_raw_data

    is_xml = route.format_family != FormatFamily.GAEB_90
    text, encoding_info = repair_encoding(raw, is_xml=is_xml)
    route.encoding_info = encoding_info

    doc = _dispatch_parser(route, source_path, text, effective_keep_xml)

    if collect_raw_data:
        _collect_raw_data(doc)

    if post_parse_hook is not None:
        _run_post_parse_hook(doc, post_parse_hook)

    if needs_xml_temporarily:
        doc.discard_xml()

    if xsd_dir is None:
        xsd_dir = get_settings().xsd_dir

    if xsd_dir:
        _run_xsd_validation(doc, source_path, text, route, xsd_dir)
    else:
        doc.add_info("XSD validation skipped: no schema directory configured")

    from pygaeb.validation import run_validation
    run_validation(doc, route, extra_validators=extra_validators)

    if validation == ValidationMode.STRICT:
        errors = [
            r for r in doc.validation_results
            if r.severity == ValidationSeverity.ERROR
        ]
        if errors:
            raise GAEBValidationError(
                f"Strict validation failed with {len(errors)} error(s): "
                f"{errors[0].message}"
            )

    logger.debug(
        "Parsed %s: %d items, %d validation results",
        source_path.name, doc.item_count, len(doc.validation_results),
    )

    return doc


def _run_post_parse_hook(
    doc: GAEBDocument,
    hook: Callable[[Any, Any], None],
) -> None:
    """Call *hook(item, source_element)* for every item that has a source_element."""
    for item in doc.iter_items():
        hook(item, getattr(item, "source_element", None))


def _collect_raw_data(doc: GAEBDocument) -> None:
    """Populate ``item.raw_data`` with child XML elements not consumed by the parser."""
    from pygaeb.parser.xml_v3.base_v3_parser import KNOWN_ITEM_TAGS

    for item in doc.iter_items():
        el = getattr(item, "source_element", None)
        if el is None:
            continue
        extras: dict[str, Any] = {}
        for child in el:
            tag = child.tag
            if "}" in tag:
                tag = tag.split("}", 1)[1]
            if tag not in KNOWN_ITEM_TAGS:
                extras[tag] = child.text
        if extras:
            item.raw_data = extras


_TRADE_PHASES = frozenset({
    ExchangePhase.X93,
    ExchangePhase.X94,
    ExchangePhase.X96,
    ExchangePhase.X97,
})

_COST_PHASES = frozenset({
    ExchangePhase.X50,
    ExchangePhase.X51,
})

_QUANTITY_PHASES = frozenset({
    ExchangePhase.X31,
})


def _dispatch_parser(
    route: ParseRoute, path: Path, text: str, keep_xml: bool = False,
) -> GAEBDocument:
    """Route to the correct parser track based on detection result."""
    if route.track == ParserTrack.TRACK_C:
        raise GAEBParseError(
            "GAEB 90 (fixed-width) parsing is not yet supported — planned for v1.1"
        )

    if route.exchange_phase in _TRADE_PHASES:
        from pygaeb.parser.xml_v3.trade_parser import TradeParser
        parser = TradeParser(route, keep_xml=keep_xml)
        return parser.parse(path, text)

    if route.exchange_phase in _COST_PHASES:
        from pygaeb.parser.xml_v3.cost_parser import CostParser
        cost_parser = CostParser(route, keep_xml=keep_xml)
        return cost_parser.parse(path, text)

    if route.exchange_phase in _QUANTITY_PHASES:
        from pygaeb.parser.xml_v3.qty_parser import QtyParser
        qty_parser = QtyParser(route, keep_xml=keep_xml)
        return qty_parser.parse(path, text)

    if route.track == ParserTrack.TRACK_A:
        from pygaeb.parser.xml_v2.v2_parser import V2Parser
        parser = V2Parser(route, keep_xml=keep_xml)  # type: ignore[assignment]
        return parser.parse(path, text)

    if route.version == SourceVersion.DA_XML_30:
        from pygaeb.parser.xml_v3.v30_compat import V30Compat
        parser = V30Compat(route, keep_xml=keep_xml)  # type: ignore[assignment]
    elif route.version == SourceVersion.DA_XML_31:
        from pygaeb.parser.xml_v3.v31_compat import V31Compat
        parser = V31Compat(route, keep_xml=keep_xml)  # type: ignore[assignment]
    elif route.version == SourceVersion.DA_XML_33:
        from pygaeb.parser.xml_v3.v33_compat import V33Compat
        parser = V33Compat(route, keep_xml=keep_xml)  # type: ignore[assignment]
    else:
        from pygaeb.parser.xml_v3.v32_compat import V32Compat
        parser = V32Compat(route, keep_xml=keep_xml)  # type: ignore[assignment]

    return parser.parse(path, text)


def _run_xsd_validation(
    doc: GAEBDocument,
    path: Path,
    text: str,
    route: ParseRoute,
    xsd_dir: str,
) -> None:
    """Run optional XSD validation if schemas are available."""
    from lxml import etree

    xsd_path = Path(xsd_dir)
    version_dir = xsd_path / f"v{route.version.value.replace('.', '')}"

    if not version_dir.exists():
        doc.add_info(
            f"XSD validation skipped: schema directory not found for version {route.version.value}"
        )
        return

    xsd_files = list(version_dir.glob("*.xsd"))
    if not xsd_files:
        doc.add_info(f"XSD validation skipped: no .xsd files in {version_dir}")
        return

    from pygaeb.parser._xml_safety import SAFE_PARSER

    try:
        with xsd_files[0].open("rb") as xsd_fh:
            schema_doc = etree.parse(xsd_fh, parser=SAFE_PARSER)
        schema = etree.XMLSchema(schema_doc)
        if doc.xml_root is not None:
            xml_doc = doc.xml_root
        else:
            xml_doc = etree.fromstring(text.encode("utf-8"), parser=SAFE_PARSER)
        if not schema.validate(xml_doc):
            for error in schema.error_log:  # type: ignore[attr-defined]
                doc.add_warning(
                    f"XSD validation: {error.message}",
                    xpath=f"line {error.line}",
                )
    except Exception as e:
        doc.add_warning(f"XSD validation failed: {e}")
