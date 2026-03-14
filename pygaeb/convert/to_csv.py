"""Export GAEBDocument items to a flat CSV file."""

from __future__ import annotations

import csv
from pathlib import Path

from pygaeb.models.document import GAEBDocument

_HEADERS = [
    "oz",
    "short_text",
    "qty",
    "unit",
    "unit_price",
    "total_price",
    "computed_total",
    "item_type",
    "lot_label",
    "hierarchy_path",
    "has_attachments",
    "bim_guid",
    "trade",
    "element_type",
    "sub_type",
    "classification_confidence",
    "classification_flag",
]


def to_csv(
    doc: GAEBDocument,
    path: str | Path,
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> None:
    """Export all items as a flat CSV file.

    Includes classification columns (trade, element_type, etc.) if items
    have been classified. Attachments are never included — only a boolean
    `has_attachments` column.
    """
    path = Path(path)
    with path.open("w", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=_HEADERS, delimiter=delimiter)
        writer.writeheader()

        for item in doc.award.boq.iter_items():
            row = {
                "oz": item.oz,
                "short_text": item.short_text,
                "qty": str(item.qty) if item.qty is not None else "",
                "unit": item.unit or "",
                "unit_price": str(item.unit_price) if item.unit_price is not None else "",
                "total_price": str(item.total_price) if item.total_price is not None else "",
                "computed_total": (
                    str(item.computed_total) if item.computed_total is not None else ""
                ),
                "item_type": item.item_type.value,
                "lot_label": item.lot_label or "",
                "hierarchy_path": " > ".join(item.hierarchy_path),
                "has_attachments": str(item.has_attachments),
                "bim_guid": item.bim_guid or "",
                "trade": "",
                "element_type": "",
                "sub_type": "",
                "classification_confidence": "",
                "classification_flag": "",
            }

            if item.classification:
                row["trade"] = item.classification.trade
                row["element_type"] = item.classification.element_type
                row["sub_type"] = item.classification.sub_type
                row["classification_confidence"] = str(item.classification.confidence)
                row["classification_flag"] = item.classification.flag

            writer.writerow(row)
