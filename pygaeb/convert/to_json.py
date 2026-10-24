"""Export GAEBDocument to JSON — full nested BoQ tree."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import Item
from pygaeb.models.order import OrderItem


def to_json(
    doc: GAEBDocument,
    path: str | Path,
    include_attachments: bool = False,
    indent: int = 2,
) -> None:
    """Export a GAEBDocument to a JSON file.

    Amounts are exact decimal strings (``"1755.00"``). Next to what the document
    stores, every item carries the values pyGAEB derives (``full_oz``,
    ``computed_total``, ``affects_total``; ``line_total`` for trade lines) and the
    document its ``grand_total``; loading the JSON back ignores them.

    Attachment data is left out, keeping file name, type and size, unless
    *include_attachments* is true, which writes it as standard base64.
    ``GAEBDocument.model_validate_json()`` reads either file back.
    """
    data = _doc_to_dict(doc, include_attachments)
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def to_json_string(
    doc: GAEBDocument,
    include_attachments: bool = False,
    indent: int = 2,
) -> str:
    """Export a GAEBDocument to a JSON string, as :func:`to_json` writes it."""
    data = _doc_to_dict(doc, include_attachments)
    return json.dumps(data, indent=indent, ensure_ascii=False)


def _doc_to_dict(doc: GAEBDocument, include_attachments: bool) -> dict[str, Any]:
    data = doc.model_dump(mode="json")
    _add_derived(doc, data)
    data["grand_total"] = _amount(doc.grand_total)

    if not include_attachments:
        _strip_attachment_data(data)

    return data


def _add_derived(model: BaseModel, data: dict[str, Any]) -> None:
    """Walk the model beside its dump, adding what pyGAEB computes instead of storing."""
    if isinstance(model, Item):
        data["full_oz"] = model.full_oz
        data["computed_total"] = _amount(model.computed_total)
        data["affects_total"] = model.affects_total
    elif isinstance(model, OrderItem):
        data["line_total"] = _amount(model.line_total)

    for name in type(model).model_fields:
        if name in data:
            _walk(getattr(model, name), data[name])


def _walk(value: Any, dumped: Any) -> None:
    if isinstance(value, BaseModel) and isinstance(dumped, dict):
        _add_derived(value, dumped)
    elif isinstance(value, (list, tuple)) and isinstance(dumped, list):
        # strict: a dump keeps every element, so a mismatch would pair the wrong items.
        for inner, inner_dumped in zip(value, dumped, strict=True):
            _walk(inner, inner_dumped)
    elif isinstance(value, dict) and isinstance(dumped, dict):
        for inner, inner_dumped in zip(value.values(), dumped.values(), strict=True):
            _walk(inner, inner_dumped)


def _amount(value: Decimal | None) -> str | None:
    # The same exact string form the dump gives every stored amount.
    return None if value is None else str(value)


def _strip_attachment_data(obj: Any) -> None:
    """Recursively strip binary 'data' field from attachment dicts, keeping metadata."""
    if isinstance(obj, dict):
        if "attachments" in obj:
            for att in obj["attachments"]:
                if isinstance(att, dict):
                    att.pop("data", None)
        for v in obj.values():
            _strip_attachment_data(v)
    elif isinstance(obj, list):
        for item in obj:
            _strip_attachment_data(item)
