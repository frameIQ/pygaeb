"""Regression tests for issue #27.

Two independent bugs surfaced by the same real-world file shape:
  - Items placed directly under <BoQBody> with no <BoQCtgy> wrapper were dropped.
  - A DA XML 3.2 breakdown declaring a single level was misread as the 3.3 form,
    losing the Item level and tripping the structural validator.
"""

from __future__ import annotations

from pygaeb import GAEBParser, GAEBWriter
from pygaeb.models.enums import BkdnType
from pygaeb.validation.structural_validator import validate_structure

_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">
  <GAEBInfo><Version>3.2</Version><Date>2026-08-11</Date><ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>Issue 27</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ><BoQInfo><Name>LV</Name>{bkdn}</BoQInfo>
  <BoQBody>{body}</BoQBody></BoQ></Award></GAEB>"""

_ITEMLIST = (
    '<Itemlist><Item RNoPart="0010"><Qty>10.000</Qty><QU>m2</QU>'
    "</Item></Itemlist>"
)
_CTGY = (
    '<BoQCtgy RNoPart="01"><LblTx>Cat</LblTx><BoQBody>'
    '<Itemlist><Item RNoPart="0020"><Qty>5.000</Qty><QU>m</QU></Item></Itemlist>'
    "</BoQBody></BoQCtgy>"
)

BKDN_1LVL_V32 = "<BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn>"
BKDN_2LVL_V32 = (
    "<BoQBkdn><Type>BoQLevel</Type><Length>2</Length></BoQBkdn>"
    "<BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn>"
)
BKDN_1LVL_V33 = '<BoQBkdn><Item Length="4"/></BoQBkdn>'
BKDN_2LVL_V33 = '<BoQBkdn><BoQLevel Length="2"/><Item Length="4"/></BoQBkdn>'


def _parse(bkdn: str, body: str):
    return GAEBParser().parse_string(_HEADER.format(bkdn=bkdn, body=body))


# --- bare Itemlist under BoQBody -------------------------------------------


def test_bare_itemlist_yields_items():
    boq = _parse(BKDN_1LVL_V33, _ITEMLIST).award.boq
    items = list(boq.iter_items())
    assert len(items) == 1
    assert items[0].oz == "0010"


def test_bare_item_without_itemlist_yields_items():
    body = '<Item RNoPart="0010"><Qty>10.000</Qty><QU>m2</QU></Item>'
    assert len(list(_parse(BKDN_1LVL_V33, body).award.boq.iter_items())) == 1


def test_bare_itemlist_alongside_categories():
    boq = _parse(BKDN_2LVL_V33, _CTGY + _ITEMLIST).award.boq
    assert {i.oz for i in boq.iter_items()} == {"0010", "0020"}


def test_bare_itemlist_survives_roundtrip_without_gaining_a_category():
    doc = _parse(BKDN_1LVL_V33, _ITEMLIST)
    xml = GAEBWriter().to_bytes(doc)[0].decode()

    body = xml.split("<BoQBody>", 1)[1].split("</BoQBody>", 1)[0]
    assert "BoQCtgy" not in body, "writer invented a category level"

    assert len(list(GAEBParser().parse_string(xml).award.boq.iter_items())) == 1


def test_category_roundtrip_still_wrapped():
    doc = _parse(BKDN_2LVL_V33, _CTGY)
    xml = GAEBWriter().to_bytes(doc)[0].decode()
    assert "<BoQCtgy" in xml
    assert len(list(GAEBParser().parse_string(xml).award.boq.iter_items())) == 1


# --- BoQBkdn format detection ----------------------------------------------


def test_single_level_v32_bkdn_is_not_read_as_v33():
    bkdn = _parse(BKDN_1LVL_V32, _ITEMLIST).award.boq.boq_info.bkdn
    assert [(b.bkdn_type, b.length) for b in bkdn] == [(BkdnType.ITEM, 4)]


def test_single_level_v32_bkdn_passes_structural_validation():
    doc = _parse(BKDN_1LVL_V32, _ITEMLIST)
    assert [r.message for r in validate_structure(doc)] == []


def test_multi_level_v32_bkdn_unchanged():
    bkdn = _parse(BKDN_2LVL_V32, _CTGY).award.boq.boq_info.bkdn
    assert [(b.bkdn_type, b.length) for b in bkdn] == [
        (BkdnType.BOQ_LEVEL, 2),
        (BkdnType.ITEM, 4),
    ]


def test_v33_bkdn_unchanged():
    bkdn = _parse(BKDN_2LVL_V33, _CTGY).award.boq.boq_info.bkdn
    assert [(b.bkdn_type, b.length) for b in bkdn] == [
        (BkdnType.BOQ_LEVEL, 2),
        (BkdnType.ITEM, 4),
    ]


def test_sibling_v33_bkdn_elements_are_all_read():
    """DA XML 2.x translates each <LVGliederung> into its own <BoQBkdn>."""
    bkdn = _parse(
        '<BoQBkdn><BoQLevel Length="2"/></BoQBkdn><BoQBkdn><Item Length="4"/></BoQBkdn>',
        _CTGY,
    ).award.boq.boq_info.bkdn
    assert [(b.bkdn_type, b.length) for b in bkdn] == [
        (BkdnType.BOQ_LEVEL, 2),
        (BkdnType.ITEM, 4),
    ]


# --- the reporter's file, and the same shape in DA XML 2.x ------------------


def test_reporter_minimal_repro():
    """Verbatim from issue #27 — reported Items: 0, expected 1."""
    doc = _parse(
        "<OutlCompl>AllTxt</OutlCompl>"
        "<BoQBkdn><Type>Item</Type><Length>2</Length><Num>Yes</Num></BoQBkdn>",
        '<Itemlist><Item ID="id3" RNoPart="1"><Qty>1.000</Qty><QU>Stk</QU>'
        "<Description><CompleteText><DetailTxt><Text><p><span>"
        "Test position long text</span></p></Text></DetailTxt></CompleteText>"
        "</Description></Item></Itemlist>",
    )
    assert len(list(doc.award.boq.iter_items())) == 1
    assert [r.message for r in validate_structure(doc)] == []


def test_da_xml_2x_bare_positionsliste():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
 <GAEBInfo><Version>2.0</Version><Datum>2026-08-11</Datum>
  <Programmsystem>t</Programmsystem></GAEBInfo>
 <Vergabe><Leistungsverzeichnis><LVInfo><Name>LV</Name>
   <LVGliederung><OZEbene Length="2"/><Teilposition Length="4"/></LVGliederung>
  </LVInfo>
  <LVBereich><Positionsliste><Position RNoPart="0010">
    <Menge>1.000</Menge><Mengeneinheit>Stk</Mengeneinheit>
  </Position></Positionsliste></LVBereich>
 </Leistungsverzeichnis></Vergabe></GAEB>"""
    doc = GAEBParser().parse_string(xml)
    assert len(list(doc.award.boq.iter_items())) == 1
