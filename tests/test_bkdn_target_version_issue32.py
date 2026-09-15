"""Regression tests for issue #32.

The BoQ breakdown has two spellings: every DA XML 3.x version spells each
level as its own `<BoQBkdn>` carrying `<Type>`/`<Length>`/`<Num>` children
(the official 3.3 2021-05 XSD included); 2.x nests level elements
(`<OZEbene Length="3"/>`) inside a single `<LVGliederung>`. The writer used to
emit the nested shape for 3.3 and both 3.2 and 3.3 output was non-conforming.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from pygaeb import GAEBParser, GAEBWriter, SourceVersion

FIXTURE = Path(__file__).parent / "fixtures" / "gaebxml.x83"

_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">
  <GAEBInfo><Version>3.2</Version><Date>2026-08-13</Date>
    <ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ><BoQInfo><Name>LV</Name>
    <BoQBkdn><Type>BoQLevel</Type><Length>2</Length></BoQBkdn>
    <BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn>
  </BoQInfo><BoQBody>
    <BoQCtgy RNoPart="01"><LblTx>C</LblTx><BoQBody><Itemlist>
      <Item RNoPart="0010"><Qty>1.000</Qty><QU>Stk</QU></Item>
    </Itemlist></BoQBody></BoQCtgy>
  </BoQBody></BoQ></Award></GAEB>"""


def _bkdn_elements(xml: str) -> list[etree._Element]:
    root = etree.fromstring(xml.encode())
    return [e for e in root.iter() if etree.QName(e).localname == "BoQBkdn"]


def _child_text(el: etree._Element, tag: str) -> str | None:
    """Text of the first child named *tag*, ignoring the default namespace."""
    for child in el:
        if etree.QName(child).localname == tag:
            return child.text
    return None


def _write(doc, version: SourceVersion) -> str:
    return GAEBWriter().to_bytes(doc, target_version=version)[0].decode()


@pytest.fixture
def doc():
    return GAEBParser().parse_string(_DOC)


def test_32_writes_sibling_type_length_form(doc):
    xml = _write(doc, SourceVersion.DA_XML_32)
    bkdns = _bkdn_elements(xml)

    assert len(bkdns) == 2, "3.2 spells each level as its own BoQBkdn"
    for el in bkdns:
        children = [etree.QName(c).localname for c in el]
        assert children == ["Type", "Length", "Num"]
        assert el.get("Length") is None

    assert "<Type>BoQLevel</Type>" in xml
    assert "<Type>Item</Type>" in xml


def test_33_writes_sibling_type_length_form(doc):
    """3.3 uses the same sibling form: tgBoQBkdn = Type, LblBoQBkdn?, Length, Num."""
    xml = _write(doc, SourceVersion.DA_XML_33)
    bkdns = _bkdn_elements(xml)

    assert len(bkdns) == 2
    levels = [
        tuple(_child_text(el, tag) for tag in ("Type", "Length", "Num")) for el in bkdns
    ]
    assert levels == [("BoQLevel", "2", "Yes"), ("Item", "4", "Yes")]
    assert "<BoQLevel " not in xml


def test_20_writes_nested_level_element_form(doc):
    """2.x nests the levels: <LVGliederung><OZEbene Length=".."/>…</LVGliederung>."""
    xml = _write(doc, SourceVersion.DA_XML_20)
    assert xml.count("<LVGliederung>") == 1
    assert '<OZEbene Length="2"' in xml
    assert "<Type>" not in xml


@pytest.mark.parametrize(
    ("version", "sibling_form"),
    [
        (SourceVersion.DA_XML_33, True),
        (SourceVersion.DA_XML_32, True),
        (SourceVersion.DA_XML_31, True),
        (SourceVersion.DA_XML_30, True),
    ],
)
def test_form_per_version(doc, version, sibling_form):
    bkdns = _bkdn_elements(_write(doc, version))
    assert (len(bkdns) == 2) is sibling_form


@pytest.mark.parametrize(
    "version",
    [
        SourceVersion.DA_XML_33,
        SourceVersion.DA_XML_32,
        SourceVersion.DA_XML_31,
        SourceVersion.DA_XML_30,
    ],
)
def test_breakdown_round_trips_for_every_version(doc, version):
    before = [(b.bkdn_type, b.length) for b in doc.award.boq.boq_info.bkdn]
    again = GAEBParser().parse_string(_write(doc, version))
    after = [(b.bkdn_type, b.length) for b in again.award.boq.boq_info.bkdn]
    assert after == before


def test_fixture_written_as_32_keeps_its_original_shape():
    """The fixture is a real-shaped 3.2 file: writing it back as 3.2 must match."""
    doc = GAEBParser().parse(str(FIXTURE))
    xml = _write(doc, SourceVersion.DA_XML_32)

    assert len(_bkdn_elements(xml)) == 3
    assert xml.count("<Type>BoQLevel</Type>") == 2
    assert xml.count("<Type>Item</Type>") == 1

    again = GAEBParser().parse_string(xml)
    assert [(b.bkdn_type, b.length) for b in again.award.boq.boq_info.bkdn] == [
        (b.bkdn_type, b.length) for b in doc.award.boq.boq_info.bkdn
    ]
