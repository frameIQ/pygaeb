"""Main entry point: GAEBParser — auto-detects version and routes to correct parser track."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from pygaeb.config import get_settings
from pygaeb.detector.encoding_repair import repair_encoding
from pygaeb.detector.format_detector import FormatFamily, ParserTrack
from pygaeb.detector.version_detector import ParseRoute, detect_version
from pygaeb.exceptions import GAEBParseError, GAEBValidationError
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import SourceVersion, ValidationMode, ValidationSeverity

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
    ) -> GAEBDocument:
        """Parse a GAEB file from disk and return a unified GAEBDocument."""
        path = Path(path)
        if not path.exists():
            raise GAEBParseError(f"File not found: {path}")

        raw = path.read_bytes()
        route = detect_version(path)
        return _parse_core(raw, route, path, validation, xsd_dir)

    @staticmethod
    def parse_bytes(
        data: bytes,
        filename: str = "input.X83",
        validation: ValidationMode = ValidationMode.LENIENT,
        xsd_dir: str | None = None,
    ) -> GAEBDocument:
        """Parse GAEB data from bytes (useful for web uploads, S3 streams, etc.).

        The filename hint is used for version/phase detection from the extension.
        """
        hint_path = Path(filename)
        with tempfile.NamedTemporaryFile(suffix=hint_path.suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            route = detect_version(tmp_path)
            return _parse_core(data, route, hint_path, validation, xsd_dir)
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def parse_string(
        xml_text: str,
        filename: str = "input.X83",
        validation: ValidationMode = ValidationMode.LENIENT,
        xsd_dir: str | None = None,
    ) -> GAEBDocument:
        """Parse GAEB data from an XML string.

        The filename hint is used for version/phase detection from the extension.
        """
        return GAEBParser.parse_bytes(
            xml_text.encode("utf-8"), filename, validation, xsd_dir
        )


def _parse_core(
    raw: bytes,
    route: ParseRoute,
    source_path: Path,
    validation: ValidationMode,
    xsd_dir: str | None,
) -> GAEBDocument:
    """Shared parsing pipeline for all entry points."""
    logger.debug(
        "Detected: version=%s track=%s phase=%s for %s",
        route.version, route.track, route.exchange_phase, source_path.name,
    )

    if route.warnings:
        for w in route.warnings:
            logger.warning(w)

    is_xml = route.format_family != FormatFamily.GAEB_90
    text, encoding_info = repair_encoding(raw, is_xml=is_xml)
    route.encoding_info = encoding_info

    doc = _dispatch_parser(route, source_path, text)

    if xsd_dir is None:
        xsd_dir = get_settings().xsd_dir

    if xsd_dir:
        _run_xsd_validation(doc, source_path, text, route, xsd_dir)
    else:
        doc.add_info("XSD validation skipped: no schema directory configured")

    from pygaeb.validation import run_validation
    run_validation(doc, route)

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


def _dispatch_parser(route: ParseRoute, path: Path, text: str) -> GAEBDocument:
    """Route to the correct parser track based on detection result."""
    if route.track == ParserTrack.TRACK_C:
        raise GAEBParseError(
            "GAEB 90 (fixed-width) parsing is not yet supported — planned for v1.1"
        )

    if route.track == ParserTrack.TRACK_A:
        from pygaeb.parser.xml_v2.v2_parser import V2Parser
        parser = V2Parser(route)
        return parser.parse(path, text)

    if route.version == SourceVersion.DA_XML_30:
        from pygaeb.parser.xml_v3.v30_compat import V30Compat
        parser = V30Compat(route)  # type: ignore[assignment]
    elif route.version == SourceVersion.DA_XML_31:
        from pygaeb.parser.xml_v3.v31_compat import V31Compat
        parser = V31Compat(route)  # type: ignore[assignment]
    elif route.version == SourceVersion.DA_XML_33:
        from pygaeb.parser.xml_v3.v33_compat import V33Compat
        parser = V33Compat(route)  # type: ignore[assignment]
    else:
        from pygaeb.parser.xml_v3.v32_compat import V32Compat
        parser = V32Compat(route)  # type: ignore[assignment]

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

    try:
        schema_doc = etree.parse(str(xsd_files[0]))
        schema = etree.XMLSchema(schema_doc)
        xml_doc = etree.fromstring(text.encode("utf-8"))
        if not schema.validate(xml_doc):
            for error in schema.error_log:  # type: ignore[attr-defined]
                doc.add_warning(
                    f"XSD validation: {error.message}",
                    xpath=f"line {error.line}",
                )
    except Exception as e:
        doc.add_warning(f"XSD validation failed: {e}")
