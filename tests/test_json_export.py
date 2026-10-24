"""``to_json``: every document kind exports, attachments included, and loads back."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pygaeb import GAEBParser, to_json, to_json_string
from pygaeb.cli import main
from pygaeb.models.document import GAEBDocument
from tests.document_kinds import DOCUMENT_KINDS
from tests.test_itwo_comments_v170 import ITWO_WITH_COMMENTS

FIXTURES = Path(__file__).parent / "fixtures"
# The iTWO sample embeds a PNG image as <image Type="image/png">iVBORw0KGgo=</image>.
SAMPLES = {**DOCUMENT_KINDS, "X83 with an embedded image": (ITWO_WITH_COMMENTS, "itwo.X83")}


def _parse(kind: str) -> GAEBDocument:
    xml, filename = SAMPLES[kind]
    return GAEBParser.parse_string(xml, filename=filename)


def _attachments(data: object) -> list[dict[str, object]]:
    """Every attachment dict anywhere in a dumped document."""
    found: list[dict[str, object]] = []
    if isinstance(data, dict):
        found += [a for a in data.get("attachments", []) if isinstance(a, dict)]
        for value in data.values():
            found += _attachments(value)
    elif isinstance(data, list):
        for value in data:
            found += _attachments(value)
    return found


@pytest.mark.parametrize("kind", list(SAMPLES))
def test_every_document_kind_loads_back_unchanged(kind: str) -> None:
    doc = _parse(kind)
    text = to_json_string(doc, include_attachments=True)

    assert GAEBDocument.model_validate_json(text).model_dump() == doc.model_dump()
    assert GAEBDocument.model_validate(json.loads(text)).model_dump() == doc.model_dump()


def test_images_are_written_as_standard_base64() -> None:
    # Raised UnicodeDecodeError: the PNG bytes went into JSON as UTF-8 text.
    doc = _parse("X83 with an embedded image")
    image = next(a for a in _attachments(json.loads(to_json_string(doc, include_attachments=True)))
                 if a["filename"] == "photo.png")

    assert image["data"] == "iVBORw0KGgo="
    assert base64.b64decode(str(image["data"])) == b"\x89PNG\r\n\x1a\n"


def test_default_export_leaves_attachment_data_out_and_still_loads() -> None:
    doc = _parse("X83 with an embedded image")
    text = to_json_string(doc)

    dumped = _attachments(json.loads(text))
    assert dumped and all("data" not in a for a in dumped)
    back = next(GAEBDocument.model_validate_json(text).iter_items()).attachments
    image = next(a for a in back if a.filename == "photo.png")
    assert (image.data, image.size_bytes, image.mime_type) == (b"", 8, "image/png")


def test_items_carry_the_values_pygaeb_derives() -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    data = json.loads(to_json_string(doc))
    items = data["award"]["boq"]["lots"][0]["body"]["categories"][0]["items"]

    assert (items[0]["full_oz"], items[0]["computed_total"], items[0]["affects_total"]) == (
        "01.0010", "1000.00", True,
    )
    assert items[0]["qty"] == "10.000"  # amounts stay exact decimal strings
    markup = next(i for i in items if i["item_type"] == "Markup")
    assert markup["computed_total"] == "100.00"
    assert data["grand_total"] == str(doc.grand_total) == "1755.00"


def test_trade_lines_carry_their_line_total() -> None:
    doc = _parse("X96 trade")
    data = json.loads(to_json_string(doc))
    lines = data["order"]["items"]

    assert all("line_total" in line for line in lines)
    assert data["grand_total"] == str(doc.grand_total)


def test_file_and_command_line_exports_handle_images(tmp_path: Path) -> None:
    source = tmp_path / "itwo.X83"
    source.write_text(ITWO_WITH_COMMENTS, encoding="utf-8")
    to_json(_parse("X83 with an embedded image"), tmp_path / "direct.json")

    result = CliRunner().invoke(
        main, ["export", str(source), "-f", "json", "-o", str(tmp_path / "cli.json")],
    )
    assert result.exit_code == 0, result.output
    for name in ("cli.json", "direct.json"):
        data = json.loads((tmp_path / name).read_text(encoding="utf-8"))
        assert data["grand_total"] is not None
