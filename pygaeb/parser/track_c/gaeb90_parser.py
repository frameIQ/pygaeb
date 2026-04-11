"""GAEB 90 fixed-width parser (Track C).

Minimal implementation supporting the most common record types found in
legacy ``.P83``/``.P84`` files. The format uses 80-character lines where
the first 2 characters identify the line type.

Common line types handled:
  - ``00``: Header/info record (project info)
  - ``01``: BoQ-Bereich / category
  - ``02``: Position number (OZ)
  - ``03``: Short text
  - ``05``: Quantity + unit
  - ``06``: Unit price
  - ``07``: Total price
  - ``99``: End-of-file marker

Lines that don't match a known type are logged as warnings but do not
abort parsing — the parser is intentionally tolerant.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import ItemType, ValidationSeverity
from pygaeb.models.item import Item, ValidationResult

logger = logging.getLogger("pygaeb.parser.gaeb90")


class GAEB90Parser:
    """Minimal Track C parser for legacy GAEB 90 files."""

    def __init__(self, route: ParseRoute) -> None:
        self._route = route

    def parse(self, path: Path, text: str) -> GAEBDocument:
        """Parse fixed-width GAEB 90 text into a GAEBDocument."""
        warnings: list[ValidationResult] = []
        items: list[Item] = []
        categories: dict[str, BoQCtgy] = {}
        current_category: BoQCtgy | None = None
        current_item: Item | None = None
        project_name: str | None = None
        project_no: str | None = None

        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            if not raw_line.strip():
                continue
            if len(raw_line) < 2:
                continue

            line_type = raw_line[:2]
            content = raw_line[2:].rstrip()

            if line_type == "00":
                project_no = content[:20].strip() or None
                project_name = content[20:80].strip() or None

            elif line_type == "01":
                rno = content[:8].strip()
                label = content[8:80].strip()
                if rno not in categories:
                    cat = BoQCtgy(rno=rno, label=label, items=[])
                    categories[rno] = cat
                current_category = categories[rno]

            elif line_type == "02":
                if current_item is not None:
                    items.append(current_item)
                oz = content[:14].strip()
                current_item = Item(
                    oz=oz,
                    item_type=ItemType.NORMAL,
                )
                if current_category is None:
                    # Orphan item — no category yet, create default
                    if "DEFAULT" not in categories:
                        categories["DEFAULT"] = BoQCtgy(
                            rno="DEFAULT", label="(no category)", items=[],
                        )
                    current_category = categories["DEFAULT"]
                current_category.items.append(current_item)

            elif line_type == "03":
                if current_item is not None:
                    text_part = content.strip()
                    if current_item.short_text:
                        current_item.short_text += " " + text_part
                    else:
                        current_item.short_text = text_part

            elif line_type == "05":
                if current_item is not None:
                    qty_str = content[:14].strip()
                    unit_str = content[14:24].strip()
                    current_item.qty = _parse_decimal(qty_str)
                    if unit_str:
                        current_item.unit = unit_str

            elif line_type == "06":
                if current_item is not None:
                    up_str = content[:14].strip()
                    current_item.unit_price = _parse_decimal(up_str)

            elif line_type == "07":
                if current_item is not None:
                    tp_str = content[:14].strip()
                    current_item.total_price = _parse_decimal(tp_str)

            elif line_type == "99":
                break

            else:
                logger.debug(
                    "GAEB 90 line %d: unknown type %r — skipped",
                    line_no, line_type,
                )

        if current_item is not None and current_item not in items:
            # Last item already in category but ensure it's accounted for
            pass

        if not categories:
            categories["1"] = BoQCtgy(rno="1", label="Default", items=items)

        body = BoQBody(categories=list(categories.values()))
        lot = Lot(rno="1", label="Lot 1", body=body)
        boq = BoQ(lots=[lot])

        warnings.append(ValidationResult(
            severity=ValidationSeverity.WARNING,
            message=(
                "GAEB 90 parser is minimal — only basic line types "
                "(00/01/02/03/05/06/07/99) are recognized. "
                "Vendor extensions, long text, and pricing components "
                "are not preserved."
            ),
        ))

        doc = GAEBDocument(
            source_version=self._route.version,
            exchange_phase=self._route.exchange_phase,
            gaeb_info=GAEBInfo(version="90", prog_system="pyGAEB"),
            award=AwardInfo(
                project_no=project_no,
                project_name=project_name,
                currency="EUR",
                boq=boq,
            ),
            source_file=str(path),
            validation_results=warnings,
        )
        return doc


def _parse_decimal(s: str) -> Decimal | None:
    """Parse a fixed-width decimal field, handling German comma notation."""
    if not s:
        return None
    cleaned = s.strip().replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
