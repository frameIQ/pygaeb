"""Two-pass malformed XML recovery + byte-level sanitisation."""

from __future__ import annotations

import logging
import re

from lxml import etree

from pygaeb.exceptions import GAEBParseError
from pygaeb.models.enums import ValidationSeverity
from pygaeb.models.item import ValidationResult
from pygaeb.parser._xml_safety import SAFE_PARSER, SAFE_RECOVER_PARSER

logger = logging.getLogger("pygaeb.parser")

_NULL_BYTES_RE = re.compile(rb"[\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e-\x1f]")
_BARE_AMP_RE = re.compile(rb"&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9a-fA-F]+);)")


def parse_xml_safe(
    text: str,
    source_file: str | None = None,
) -> tuple[etree._Element, list[ValidationResult]]:
    """Parse XML with two-pass recovery strategy.

    Returns (root_element, validation_warnings).
    Raises GAEBParseError if even recovery fails.
    """
    warnings: list[ValidationResult] = []
    raw = text.encode("utf-8")

    try:
        root = etree.fromstring(raw, parser=SAFE_PARSER)
        return root, warnings
    except etree.XMLSyntaxError:
        pass

    sanitised = _sanitise_bytes(raw)
    if sanitised != raw:
        warnings.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message="Applied byte-level sanitisation to repair malformed XML",
        ))
        try:
            root = etree.fromstring(sanitised, parser=SAFE_PARSER)
            return root, warnings
        except etree.XMLSyntaxError:
            pass

    try:
        root = etree.fromstring(sanitised, parser=SAFE_RECOVER_PARSER)
        if root is None:
            raise GAEBParseError(
                f"XML recovery produced empty tree: {source_file}",
                errors=[str(e) for e in SAFE_RECOVER_PARSER.error_log],
            )
        warnings.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message=(
                f"Recovered from malformed XML "
                f"({len(SAFE_RECOVER_PARSER.error_log)} errors)"
            ),
        ))
        return root, warnings
    except etree.XMLSyntaxError as e:
        raise GAEBParseError(
            f"Cannot parse XML even in recovery mode: {source_file}: {e}",
            errors=[str(e)],
        ) from e


def _sanitise_bytes(raw: bytes) -> bytes:
    """Apply byte-level fixups for common corruptions."""
    result = _NULL_BYTES_RE.sub(b"", raw)
    result = _BARE_AMP_RE.sub(b"&amp;", result)
    return result
