"""Export GAEBDocument to JSON — full nested BoQ tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pygaeb.models.document import GAEBDocument


def to_json(
    doc: GAEBDocument,
    path: str | Path,
    include_attachments: bool = False,
    indent: int = 2,
) -> None:
    """Export a GAEBDocument to a JSON file.

    By default, binary attachment data is stripped (metadata kept).
    Pass include_attachments=True to include base64-encoded data.
    """
    data = _doc_to_dict(doc, include_attachments)
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=str)


def to_json_string(
    doc: GAEBDocument,
    include_attachments: bool = False,
    indent: int = 2,
) -> str:
    """Export a GAEBDocument to a JSON string."""
    data = _doc_to_dict(doc, include_attachments)
    return json.dumps(data, indent=indent, ensure_ascii=False, default=str)


def _doc_to_dict(doc: GAEBDocument, include_attachments: bool) -> dict[str, Any]:
    data = doc.model_dump(mode="json", exclude={"raw_data"})

    if not include_attachments:
        _strip_attachment_data(data)

    return data


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
