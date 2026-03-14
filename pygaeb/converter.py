"""GAEB version converter — convert between DA XML versions (2.0 through 3.3)."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from pygaeb.models.enums import ExchangePhase, SourceVersion
from pygaeb.writer.version_registry import WRITABLE_VERSIONS

logger = logging.getLogger("pygaeb.converter")


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
        return self.target_version.value > self.source_version.value

    @property
    def is_downgrade(self) -> bool:
        return self.target_version.value < self.source_version.value

    @property
    def is_same_family(self) -> bool:
        """True when both versions are in the same language family (both 3.x or both 2.x)."""
        src = self.source_version.value
        tgt = self.target_version.value
        return (src >= "3" and tgt >= "3") or (src < "3" and tgt < "3")

    @property
    def has_data_loss(self) -> bool:
        return len(self.fields_dropped) > 0


class GAEBConverter:
    """Convert GAEB files between DA XML versions.

    Wraps ``GAEBParser.parse()`` + ``GAEBWriter.write()`` with conversion
    semantics and a detailed :class:`ConversionReport`.

    Usage::

        report = GAEBConverter.convert(
            "old.D83", "new.X83",
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
    ) -> ConversionReport:
        """Convert a GAEB file to a different DA XML version.

        Args:
            source: Input file path or raw bytes.
            output: Output file path.
            target_version: Target DA XML version (default: 3.3).
            target_phase: Override exchange phase (default: keep original).
            encoding: XML encoding (default: utf-8).

        Returns:
            A :class:`ConversionReport` with conversion details and any warnings.

        Raises:
            ValueError: If target_version is not writable (e.g. GAEB_90).
            GAEBParseError: If the source file cannot be parsed.
        """
        from pygaeb.parser import GAEBParser
        from pygaeb.writer import GAEBWriter

        if target_version not in WRITABLE_VERSIONS:
            supported = ", ".join(
                v.value for v in sorted(WRITABLE_VERSIONS, key=lambda v: v.value)
            )
            raise ValueError(
                f"Cannot convert to {target_version.value}. Supported: {supported}"
            )

        if isinstance(source, bytes):
            doc = GAEBParser.parse_bytes(source)
        else:
            doc = GAEBParser.parse(source)

        effective_phase = target_phase or doc.exchange_phase

        writer_warnings = GAEBWriter.write(
            doc, output,
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
            fields_dropped=[w for w in writer_warnings if "dropped" in w.lower()],
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
    ) -> tuple[bytes, ConversionReport]:
        """Convert a GAEB file and return the result as bytes.

        Args:
            source: Input file path or raw bytes.
            target_version: Target DA XML version (default: 3.3).
            target_phase: Override exchange phase (default: keep original).
            encoding: XML encoding (default: utf-8).

        Returns:
            Tuple of (converted_xml_bytes, ConversionReport).
        """
        from pygaeb.parser import GAEBParser
        from pygaeb.writer import GAEBWriter

        if target_version not in WRITABLE_VERSIONS:
            raise ValueError(f"Cannot convert to {target_version.value}.")

        if isinstance(source, bytes):
            doc = GAEBParser.parse_bytes(source)
        else:
            doc = GAEBParser.parse(source)

        effective_phase = target_phase or doc.exchange_phase

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
            fields_dropped=[w for w in writer_warnings if "dropped" in w.lower()],
            warnings=writer_warnings,
        )

        return xml_bytes, report
