"""Export GAEBDocument items to a flat CSV file."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from pygaeb.convert._rows import item_table
from pygaeb.models.document import GAEBDocument

# A spreadsheet reads a cell starting with one of these as a formula (OWASP CSV injection).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def to_csv(
    doc: GAEBDocument,
    path: str | Path,
    delimiter: str = ",",
    encoding: str = "utf-8",
    *,
    escape_formulas: bool = True,
) -> None:
    """Export every item as one CSV row, with the columns of the document's kind.

    Tender and award documents, trade orders (X93-X97), cost estimates (X50/X51)
    and quantity determinations (X31) each get their own columns; see the
    "Export to CSV" guide. Amounts are written exactly, as their decimal text.
    Classification columns are filled once items have been classified.
    Attachments are never included, only a boolean ``has_attachments`` column.

    Text from the document that starts with ``=``, ``+``, ``-``, ``@``, a tab or a
    carriage return gets a leading ``'``, so a spreadsheet shows it instead of
    running it as a formula. Numbers are never changed. Pass
    ``escape_formulas=False`` for the text exactly as the document has it.
    """
    table = item_table(doc)
    path = Path(path)
    with path.open("w", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=table.columns, delimiter=delimiter)
        writer.writeheader()
        for row in table.rows:
            writer.writerow({key: _cell(value, escape_formulas) for key, value in row.items()})


def _cell(value: Any, escape_formulas: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if escape_formulas and isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return str(value)
