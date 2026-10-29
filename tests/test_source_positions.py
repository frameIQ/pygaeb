"""Source positions (``positions=True``) and findings that name their item."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from lxml import etree

from pygaeb import GAEBParser, GAEBWriter
from pygaeb.detector.encoding_repair import decode_xml_as_written
from pygaeb.models.boq import BoQCtgy
from pygaeb.models.enums import SourceVersion
from pygaeb.models.item import ValidationResult
from pygaeb.models.source import SourceSpan
from pygaeb.parser.xml_v2.german_element_map import GERMAN_TO_ENGLISH
from pygaeb.validation import CrossPhaseValidator
from tests.document_kinds import DOCUMENT_KINDS

FIXTURES = Path(__file__).parent / "fixtures"
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def _tender(sep: str = "\n") -> str:
    """Two categories, three items; C2's item reuses the leaf OZ 0010."""
    return sep.join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">',
        "<GAEBInfo><Version>3.3</Version></GAEBInfo>",
        '<Award><BoQ ID="B1"><BoQInfo>'
        "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length></BoQBkdn>"
        "<BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn></BoQInfo><BoQBody>",
        '<BoQCtgy ID="C1" RNoPart="01"><LblTx><p><span>Masonry</span></p></LblTx>'
        "<BoQBody><Itemlist>",
        '<Item ID="I1" RNoPart="0010"><Qty>10.000</Qty><QU>m2</QU></Item>',
        '<Item ID="I2" RNoPart="0020"><Qty>12.3456</Qty><QU>m2</QU></Item>',
        "</Itemlist></BoQBody></BoQCtgy>",
        '<BoQCtgy ID="C2" RNoPart="02"><LblTx><p><span>Concrete</span></p></LblTx>'
        "<BoQBody><Itemlist>",
        '<Item ID="I3" RNoPart="0010"><Qty>4.000</Qty><QU>t</QU></Item>',
        "</Itemlist></BoQBody></BoQCtgy>",
        "</BoQBody></BoQ></Award></GAEB>",
    ])


def _at(text: str, line: int, column: int) -> str:
    """The text from a 1-based (line, column) to the end of that line."""
    return _LINE_BREAK.split(text)[line - 1][column - 1:]


def _assert_spans(text: str, span: SourceSpan | None, tag: str) -> None:
    assert span is not None
    assert _at(text, span.start_line, span.start_column).startswith(f"<{tag}")
    end_line = _LINE_BREAK.split(text)[span.end_line - 1]
    assert end_line[: span.end_column - 1].endswith(f"</{tag}>")


def _qty_finding(results: list[ValidationResult]) -> ValidationResult:
    return next(r for r in results if "4 decimal places" in r.message)


def test_off_by_default() -> None:
    doc = GAEBParser.parse_string(_tender(), "tender.X83")
    assert all(item.source_span is None for item in doc.iter_items())
    finding = _qty_finding(doc.validation_results)
    assert finding.item_id == "I2"
    assert finding.source_span is None


@pytest.mark.parametrize("sep", ["\n", "\r\n", "\r", ""], ids=["LF", "CRLF", "CR", "one-line"])
def test_spans_cover_items_and_categories(sep: str) -> None:
    text = _tender(sep)
    doc = GAEBParser.parse_string(text, "tender.X83", positions=True)
    items = list(doc.iter_items())
    assert [item.id for item in items] == ["I1", "I2", "I3"]
    for item in items:
        _assert_spans(text, item.source_span, "Item")
    for ctgy in doc.award.boq.lots[0].body.categories:
        _assert_spans(text, ctgy.source_span, "BoQCtgy")
    spans = [item.source_span for item in items if item.source_span]
    assert len({(span.start_line, span.start_column) for span in spans}) == 3


def test_columns_count_characters_in_a_latin1_file() -> None:
    text = (
        _tender("")
        .replace('encoding="utf-8"', 'encoding="ISO-8859-1"')
        .replace("Masonry", "Mauerwerk für Außenwände")
    )
    doc = GAEBParser.parse_bytes(text.encode("iso-8859-1"), "tender.X83", positions=True)
    for item in doc.iter_items():
        _assert_spans(text, item.source_span, "Item")


def test_utf16_file_with_byte_order_mark() -> None:
    text = _tender("\r\n").replace('encoding="utf-8"', 'encoding="UTF-16"')
    doc = GAEBParser.parse_bytes(text.encode("utf-16"), "tender.X83", positions=True)
    for item in doc.iter_items():
        _assert_spans(text, item.source_span, "Item")


def test_parse_string_counts_on_the_string_as_given() -> None:
    # parse_string rewrites the declaration to UTF-8; positions must not shift with it.
    text = _tender("").replace('encoding="utf-8"', 'encoding="ISO-8859-1"')
    doc = GAEBParser.parse_string(text, "tender.X83", positions=True)
    for item in doc.iter_items():
        _assert_spans(text, item.source_span, "Item")


def test_an_empty_item_right_before_an_end_tag() -> None:
    # In "<Item/></Itemlist>" the end tag belongs to the parent, not to the item.
    empty = '<Item ID="I3" RNoPart="0010"/>'
    text = _tender("").replace(
        '<Item ID="I3" RNoPart="0010"><Qty>4.000</Qty><QU>t</QU></Item>', empty,
    )
    doc = GAEBParser.parse_string(text, "tender.X83", positions=True)
    span = next(item.source_span for item in doc.iter_items() if item.id == "I3")
    assert span is not None
    assert span.start_line == span.end_line == 1
    assert text[span.start_column - 1 : span.end_column - 1] == empty


@pytest.mark.parametrize("sep", ["\n", "\r\n", "\r"], ids=["LF", "CRLF", "CR"])
def test_an_end_tag_broken_over_lines(sep: str) -> None:
    text = _tender(sep).replace("</Item>", f"</Item{sep}  >")
    doc = GAEBParser.parse_string(text, "tender.X83", positions=True)
    for item in doc.iter_items():
        assert item.source_span is not None
        assert _at(text, item.source_span.start_line, item.source_span.start_column).startswith(
            f'<Item ID="{item.id}"'
        )
        end_line = _LINE_BREAK.split(text)[item.source_span.end_line - 1]
        assert end_line[: item.source_span.end_column - 1] == "  >"


def test_entity_declarations_leave_positions_out() -> None:
    text = _tender().replace("<GAEB ", '<!DOCTYPE GAEB [<!ENTITY lol "lol">]>\n<GAEB ', 1)
    doc = GAEBParser.parse_string(text, "tender.X83", positions=True)
    assert len(list(doc.iter_items())) == 3
    assert all(item.source_span is None for item in doc.iter_items())
    messages = [r.message for r in doc.validation_results]
    assert "Source positions unavailable: the file declares entities" in messages


def test_a_repaired_file_leaves_positions_out() -> None:
    doc = GAEBParser.parse_string(
        _tender().replace("Masonry", "Masonry & Co"), "tender.X83", positions=True,
    )
    assert all(item.source_span is None for item in doc.iter_items())
    assert any(
        r.message == "Source positions unavailable: the XML needed repair before parsing"
        for r in doc.validation_results
    )


def test_findings_name_their_item_and_its_span() -> None:
    doc = GAEBParser.parse_string(_tender(), "tender.X83", positions=True)
    item = next(i for i in doc.iter_items() if i.id == "I2")
    finding = _qty_finding(doc.validation_results)
    assert finding.item_id == "I2"
    assert finding.xpath_location == "*[@ID='I2']/Qty"
    assert item.source_span is not None
    assert finding.source_span == item.source_span


def test_an_item_without_id_keeps_its_rnopart_location() -> None:
    doc = GAEBParser.parse_string(_tender().replace(' ID="I2"', ""), "tender.X83")
    finding = _qty_finding(doc.validation_results)
    assert finding.item_id is None
    assert finding.xpath_location == "Item[@RNoPart='0020']/Qty"


def test_findings_without_ids_keep_their_old_locations() -> None:
    # Cross-phase findings name the full OZ; a duplicate OZ names the part after its last dot.
    tender = GAEBParser.parse_string(_tender().replace(' ID="I2"', ""), "tender.X83")
    bid = GAEBParser.parse_string(
        _tender().replace('<Item ID="I2" RNoPart="0020"><Qty>12.3456</Qty><QU>m2</QU></Item>', ""),
        "bid.X84",
    )
    missing = next(
        r for r in CrossPhaseValidator.check(tender, bid) if "missing in response" in r.message
    )
    assert (missing.item_id, missing.xpath_location) == (None, "Item[@RNoPart='01.0020']")

    text, name = DOCUMENT_KINDS["X52 cost BoQ"]
    match = re.search(r'<Item RNoPart="01\.01">.*?</Item>', text, re.S)
    assert match is not None
    doc = GAEBParser.parse_string(text.replace(match.group(0), match.group(0) * 2), name)
    duplicate = next(r for r in doc.validation_results if r.message.startswith("Duplicate OZ"))
    assert (duplicate.item_id, duplicate.xpath_location) == (None, "Item[@RNoPart='01']")


def test_duplicate_oz_points_at_the_repeat() -> None:
    text = _tender().replace('RNoPart="0020"', 'RNoPart="0010"')
    doc = GAEBParser.parse_string(text, "tender.X83", positions=True)
    finding = next(r for r in doc.validation_results if r.message.startswith("Duplicate OZ"))
    assert finding.item_id == "I2"
    assert finding.source_span is not None


def test_a_category_total_finding_points_at_the_category() -> None:
    text = (
        _tender()
        .replace(
            "<Qty>10.000</Qty><QU>m2</QU>",
            "<Qty>10.000</Qty><QU>m2</QU><UP>2.00</UP><IT>20.00</IT>",
        )
        .replace(
            "</Itemlist></BoQBody></BoQCtgy>",
            "</Itemlist></BoQBody><Totals><Total>99.00</Total></Totals></BoQCtgy>",
            1,
        )
    )
    doc = GAEBParser.parse_string(text, "award.X86", positions=True)
    ctgy = doc.award.boq.lots[0].body.categories[0]
    finding = next(
        r for r in doc.validation_results if r.message.startswith("Category '01' total mismatch")
    )
    assert finding.xpath_location == "*[@ID='C1']/Totals/Total"
    assert ctgy.source_span is not None
    assert finding.source_span == ctgy.source_span


def test_da_xml_2_files_with_german_element_names() -> None:
    award = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    xml, _ = GAEBWriter.to_bytes(award, target_version=SourceVersion.DA_XML_20)
    text = xml.decode("utf-8")
    doc = GAEBParser.parse_bytes(xml, "award.X86", positions=True)
    items = list(doc.iter_items())
    assert items
    for item in items:
        assert item.source_span is not None
        start = _at(text, item.source_span.start_line, item.source_span.start_column)
        match = re.match(r"<([\w:]+)", start)
        assert match is not None
        name = match.group(1).rsplit(":", 1)[-1]
        assert GERMAN_TO_ENGLISH.get(name, name) in {"Item", "MarkupItem"}


def test_exports_do_not_change() -> None:
    off = GAEBParser.parse_string(_tender(), "tender.X83")
    on = GAEBParser.parse_string(_tender(), "tender.X83", positions=True)
    assert off.model_dump(mode="json") == on.model_dump(mode="json")


_NS = "http://www.gaeb.de/GAEB_DA_XML/DA83/3.3"


@st.composite
def _random_tenders(draw: st.DrawFn) -> str:
    """Random nesting, IDs, empty items, label text, line breaks and end-tag layout."""
    sep = draw(st.sampled_from(["", "\n", "\r\n", "\r"]))
    item_end = draw(st.sampled_from(["</Item>", f"</Item{sep or ' '}  >"]))
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<GAEB xmlns="{_NS}">',
        "<GAEBInfo><Version>3.3</Version></GAEBInfo>",
        "<Award><BoQ><BoQInfo>"
        "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length></BoQBkdn>"
        "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length></BoQBkdn>"
        "<BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn></BoQInfo><BoQBody>",
    ]

    def item_list(prefix: str) -> None:
        parts.append("<BoQBody><Itemlist>")
        for n in range(draw(st.integers(0, 3))):
            attrs = f' ID="{prefix}I{n}"' if draw(st.booleans()) else ""
            attrs += f' RNoPart="{(n + 1) * 10:04d}"'
            if draw(st.booleans()):
                parts.append(f"<Item{attrs}/>")
            else:
                qty = draw(st.integers(0, 999))
                parts.append(f"<Item{attrs}><Qty>{qty}.000</Qty><QU>m</QU>{item_end}")
        parts.append("</Itemlist></BoQBody>")

    for c in range(draw(st.integers(1, 3))):
        label = escape(draw(st.text(alphabet="aZ09 äöüß€\N{EN DASH}😀&<>\"'", max_size=12)))
        parts.append(
            f'<BoQCtgy ID="C{c}" RNoPart="{c + 1:02d}"><LblTx><p><span>{label}</span></p></LblTx>'
        )
        if draw(st.booleans()):
            parts.append("<BoQBody>")
            for s in range(draw(st.integers(1, 2))):
                parts.append(f'<BoQCtgy ID="C{c}S{s}" RNoPart="{s + 1:02d}">')
                item_list(f"C{c}S{s}")
                parts.append("</BoQCtgy>")
            parts.append("</BoQBody>")
        else:
            item_list(f"C{c}")
        parts.append("</BoQCtgy>")
    parts.append("</BoQBody></BoQ></Award></GAEB>")
    return sep.join(parts)


def _categories(ctgys: list[BoQCtgy]) -> Iterator[BoQCtgy]:
    for ctgy in ctgys:
        yield ctgy
        yield from _categories(ctgy.subcategories)


@settings(max_examples=60, deadline=None)
@given(_random_tenders())
def test_spans_cover_exactly_their_element(text: str) -> None:
    on = GAEBParser.parse_string(text, "tender.X83", positions=True)
    off = GAEBParser.parse_string(text, "tender.X83")
    assert on.model_dump(mode="json") == off.model_dump(mode="json")
    starts = [0] + [m.end() for m in _LINE_BREAK.finditer(text)]
    nodes = [("Item", item.id, item.source_span) for item in on.iter_items()]
    nodes += [
        ("BoQCtgy", ctgy.id, ctgy.source_span)
        for ctgy in _categories(on.award.boq.lots[0].body.categories)
    ]
    for tag, node_id, span in nodes:
        assert span is not None
        piece = text[
            starts[span.start_line - 1] + span.start_column - 1
            : starts[span.end_line - 1] + span.end_column - 1
        ]
        # Exactly one whole element, nothing before or after it.
        wrapper = etree.fromstring(f'<w xmlns="{_NS}">{piece}</w>'.encode())
        assert len(wrapper) == 1
        assert not (wrapper.text or wrapper[0].tail)
        assert etree.QName(wrapper[0]).localname == tag
        assert wrapper[0].get("ID") == node_id


_BVBS = os.environ.get("PYGAEB_BVBS_FIXTURES")


@pytest.mark.skipif(not _BVBS, reason="set PYGAEB_BVBS_FIXTURES to check positions on BVBS files")
def test_bvbs_files() -> None:
    assert _BVBS is not None
    files = sorted(p for p in Path(_BVBS).rglob("*") if p.suffix.upper().startswith(".X8"))
    assert files
    for path in files:
        raw = path.read_bytes()
        doc = GAEBParser.parse_bytes(raw, path.name, positions=True)
        text = decode_xml_as_written(raw)[0]
        for item in doc.iter_items():
            assert item.source_span is not None, path
            assert _at(text, item.source_span.start_line, item.source_span.start_column).startswith(
                "<"
            ), path
