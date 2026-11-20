"""Attachments added in code reach the written DA XML 3.3 file.

The schema embeds only JPEG, GIF and PNG, as ``<image>`` inside a long-text
paragraph; any other file is referenced by name with ``<attachment>``. A file
that pyGAEB parsed already carries its attachments in the long text's markup,
which the writer copies, so those must not be written a second time.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pygaeb import ExchangePhase, GAEBDocument, GAEBParser, GAEBWriter, Item, SourceVersion
from pygaeb.builder import BoQBuilder
from pygaeb.parser.gaeb_parser import validate_xml

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(16))
URL = "https://example.com/plan.pdf"
_XSD_DIR = os.environ.get("PYGAEB_XSD_DIR")


def _tender(*attachments: tuple[str, bytes, str]) -> GAEBDocument:
    builder = BoQBuilder(phase="X83", version="3.3")
    # The leaf number: RNoPart takes no dots, so "01.0010" would fail the schema.
    item = builder.add_category("01", "Fenster").add_item("0010", "Fenster", qty=2, unit="Stk")
    item.set_long_text("Fenster nach Plan")
    for name, data, mime in attachments:
        item.add_attachment(name, data, mime_type=mime)
    return builder.build()


def _write_and_read(
    doc: GAEBDocument, phase: ExchangePhase = ExchangePhase.X83,
) -> tuple[GAEBDocument, list[str]]:
    data, warnings = GAEBWriter.to_bytes(doc, phase=phase)
    return GAEBParser.parse_bytes(data, filename=f"tender.{phase.value}"), warnings


def _item(doc: GAEBDocument) -> Item:
    item = next(iter(doc.iter_items()))
    assert isinstance(item, Item)
    return item


def test_image_added_in_code_survives_a_write() -> None:
    doc, _ = _write_and_read(_tender(("plan.png", PNG, "image/png")))
    assert [(a.filename, a.mime_type, a.data) for a in _item(doc).attachments] == [
        ("plan.png", "image/png", PNG)
    ]


def test_reference_added_in_code_survives_a_write() -> None:
    doc, warnings = _write_and_read(_tender((URL, b"", "application/pdf")))
    assert [(a.filename, a.data) for a in _item(doc).attachments] == [(URL, b"")]
    assert not any("dropped" in w for w in warnings)


def test_bytes_the_schema_cannot_embed_become_a_reference() -> None:
    doc, warnings = _write_and_read(_tender(("plan.pdf", b"%PDF-1.4", "application/pdf")))
    assert [(a.filename, a.data) for a in _item(doc).attachments] == [("plan.pdf", b"")]
    assert any("plan.pdf" in w and "dropped" in w for w in warnings)


def test_a_second_write_does_not_repeat_them() -> None:
    once, _ = _write_and_read(_tender(("plan.png", PNG, "image/png"), (URL, b"", "")))
    twice, _ = _write_and_read(once)
    assert len(_item(twice).attachments) == 2


def test_a_bid_restates_no_attachments() -> None:
    bid, _ = _write_and_read(_tender(("plan.png", PNG, "image/png")), ExchangePhase.X84)
    assert _item(bid).attachments == []


@pytest.mark.skipif(
    not (_XSD_DIR and Path(_XSD_DIR).is_dir()),
    reason="set PYGAEB_XSD_DIR to the 2021-05 schema folder",
)
def test_written_attachments_are_schema_valid() -> None:
    doc = _tender(("plan.png", PNG, "image/png"), (URL, b"", ""), ("plan.pdf", b"%PDF", ""))
    data, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X83)
    result = validate_xml(data, SourceVersion.DA_XML_33, ExchangePhase.X83, _XSD_DIR)
    assert result is not None
    assert result.valid, [e.message for e in result.errors]
