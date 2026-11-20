"""GAEB version converter — convert between DA XML versions (2.0 through 3.3)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ExchangePhase, SourceVersion
from pygaeb.writer.version_registry import WRITABLE_VERSIONS

logger = logging.getLogger("pygaeb.converter")

#: How the writer words a warning about data the output lacks: no schema has a
#: place for it ("dropped"), or the target phase has none ("not written").
_LOSS_MARKERS = ("dropped", "not written")

# Oldest first. The enum's string values cannot be compared directly: "90"
# sorts above "3.3".
_VERSION_ORDER: tuple[SourceVersion, ...] = (
    SourceVersion.GAEB_90,
    SourceVersion.DA_XML_20,
    SourceVersion.DA_XML_21,
    SourceVersion.DA_XML_30,
    SourceVersion.DA_XML_31,
    SourceVersion.DA_XML_32,
    SourceVersion.DA_XML_33,
)


def _family(version: SourceVersion) -> str:
    """``"90"`` for GAEB 90, else the major DA XML version (``"2"`` or ``"3"``)."""
    if version is SourceVersion.GAEB_90:
        return "90"
    return str(version.value).split(".")[0]


class ConversionReport(BaseModel):
    """Report generated after a GAEB version conversion."""

    source_version: SourceVersion
    target_version: SourceVersion
    source_phase: ExchangePhase
    target_phase: ExchangePhase
    items_converted: int = 0
    fields_dropped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_upgrade(self) -> bool:
        return _VERSION_ORDER.index(self.target_version) > _VERSION_ORDER.index(
            self.source_version
        )

    @property
    def is_downgrade(self) -> bool:
        return _VERSION_ORDER.index(self.target_version) < _VERSION_ORDER.index(
            self.source_version
        )

    @property
    def is_same_family(self) -> bool:
        """True when both versions are in the same family: GAEB 90, DA XML 2.x or 3.x."""
        return _family(self.source_version) == _family(self.target_version)

    @property
    def has_data_loss(self) -> bool:
        """True when the output lacks data the source had, including what the
        target phase has no place for (prices in a tender)."""
        return len(self.fields_dropped) > 0


def _losses(writer_warnings: list[str]) -> list[str]:
    return [w for w in writer_warnings if any(m in w.lower() for m in _LOSS_MARKERS)]


def _parse_source(source: str | Path | bytes, source_filename: str | None) -> GAEBDocument:
    from pygaeb.parser import GAEBParser

    if isinstance(source, bytes):
        return GAEBParser.parse_bytes(source, filename=source_filename)
    return GAEBParser.parse(source)


def _name_disagrees(output: Path, phase: ExchangePhase) -> str | None:
    """A warning when *output*'s extension names another phase than the one written."""
    try:
        named = ExchangePhase(output.suffix[1:].upper()).normalized()
    except ValueError:
        return None
    if named is phase:
        return None
    return (
        f"{output.name} is named as {named.value} but holds {phase.value}; "
        f"pass target_phase=ExchangePhase.{named.value} to write a {named.value}"
    )


class GAEBConverter:
    """Convert GAEB files between DA XML versions.

    Wraps ``GAEBParser.parse()`` + ``GAEBWriter.write()`` with conversion
    semantics and a detailed :class:`ConversionReport`.

    The phase stays the source's unless *target_phase* says otherwise; a GAEB 90
    phase becomes its DA XML phase (``D83`` → ``X83``).

    Usage::

        report = GAEBConverter.convert(
            "tender_2005.X83", "tender_33.X83",
            target_version=SourceVersion.DA_XML_33,
        )
        print(f"Converted {report.items_converted} items")
        for warning in report.fields_dropped:
            print(f"  Dropped: {warning}")

    """

    @staticmethod
    def convert(
        source: str | Path | bytes,
        output: str | Path,
        target_version: SourceVersion = SourceVersion.DA_XML_33,
        target_phase: ExchangePhase | None = None,
        encoding: str = "utf-8",
        *,
        source_filename: str | None = None,
    ) -> ConversionReport:
        """Convert a GAEB file to a different DA XML version.

        Args:
            source: Input file path or raw bytes.
            output: Output file path.
            target_version: Target DA XML version (default: 3.3).
            target_phase: Override exchange phase (default: keep original).
                Converting to another phase writes only what that phase holds:
                a tender (X83) has no prices. The report counts what is left out.
            encoding: XML encoding (default: utf-8).
            source_filename: For bytes, the file's name: its extension gives the
                phase of a GAEB 90 file, which the content does not declare.

        Returns:
            A :class:`ConversionReport` with conversion details and any warnings.

        Raises:
            ValueError: If target_version is not writable (e.g. GAEB_90), or
                target_phase belongs to another kind of document.
            GAEBParseError: If the source file cannot be parsed.
        """
        from pygaeb.writer import GAEBWriter
        from pygaeb.writer.gaeb_writer import target_phase_for

        if target_version not in WRITABLE_VERSIONS:
            supported = ", ".join(
                v.value for v in sorted(WRITABLE_VERSIONS, key=lambda v: v.value)
            )
            raise ValueError(
                f"Cannot convert to {target_version.value}. Supported: {supported}"
            )

        doc = _parse_source(source, source_filename)
        effective_phase = target_phase_for(doc, target_phase)

        writer_warnings = GAEBWriter.write(
            doc, output,
            phase=effective_phase,
            target_version=target_version,
            encoding=encoding,
        )
        mismatch = _name_disagrees(Path(output), effective_phase)
        if mismatch:
            writer_warnings.append(mismatch)

        report = ConversionReport(
            source_version=doc.source_version,
            target_version=target_version,
            source_phase=doc.exchange_phase,
            target_phase=effective_phase,
            items_converted=doc.item_count,
            fields_dropped=_losses(writer_warnings),
            warnings=writer_warnings,
        )

        logger.info(
            "Converted %s → %s (%d items, %d warnings)",
            doc.source_version.value, target_version.value,
            report.items_converted, len(report.warnings),
        )
        return report

    @staticmethod
    def convert_bytes(
        source: str | Path | bytes,
        target_version: SourceVersion = SourceVersion.DA_XML_33,
        target_phase: ExchangePhase | None = None,
        encoding: str = "utf-8",
        *,
        source_filename: str | None = None,
    ) -> tuple[bytes, ConversionReport]:
        """Convert a GAEB file and return the result as bytes.

        Args:
            source: Input file path or raw bytes.
            target_version: Target DA XML version (default: 3.3).
            target_phase: Override exchange phase (default: keep original).
            encoding: XML encoding (default: utf-8).
            source_filename: For bytes, the file's name, as in :meth:`convert`.

        Returns:
            Tuple of (converted_xml_bytes, ConversionReport).
        """
        from pygaeb.writer import GAEBWriter
        from pygaeb.writer.gaeb_writer import target_phase_for

        if target_version not in WRITABLE_VERSIONS:
            raise ValueError(f"Cannot convert to {target_version.value}.")

        doc = _parse_source(source, source_filename)
        effective_phase = target_phase_for(doc, target_phase)

        xml_bytes, writer_warnings = GAEBWriter.to_bytes(
            doc,
            phase=effective_phase,
            target_version=target_version,
            encoding=encoding,
        )

        report = ConversionReport(
            source_version=doc.source_version,
            target_version=target_version,
            source_phase=doc.exchange_phase,
            target_phase=effective_phase,
            items_converted=doc.item_count,
            fields_dropped=_losses(writer_warnings),
            warnings=writer_warnings,
        )

        return xml_bytes, report
