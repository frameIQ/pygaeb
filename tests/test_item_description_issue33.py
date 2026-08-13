"""Regression tests for issue #33.

Item text was written as flat `<ShortText>`/`<LongText>` regardless of target
version. Those are the 2.x spelling; DA XML 3.x carries both inside
`<Description><CompleteText>`, so 3.x output was not what consumers expect and
all inline `<span>` markup was lost.
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
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ>
    <BoQInfo><Name>LV</Name><BoQBkdn><Item Length="4"/></BoQBkdn></BoQInfo>
    <BoQBody><Itemlist>
      <Item RNoPart="0010"><Qty>1.000</Qty><QU>Stk</QU>
        <Description><CompleteText>
          <DetailTxt><Text><p>{detail}</p></Text></DetailTxt>
          <OutlineText><OutlTxt><TextOutlTxt><span>{outline}</span>
            </TextOutlTxt></OutlTxt></OutlineText>
        </CompleteText></Description>
      </Item>
    </Itemlist></BoQBody>
  </BoQ></Award></GAEB>"""


def _parse(detail: str = "<span>Body text.</span>", outline: str = "Label"):
    return GAEBParser().parse_string(_DOC.format(detail=detail, outline=outline))


def _write(doc, version: SourceVersion = SourceVersion.DA_XML_33) -> str:
    return GAEBWriter().to_bytes(doc, target_version=version)[0].decode()


def _localnames(xml: str) -> list[str]:
    root = etree.fromstring(xml.encode())
    return [etree.QName(e).localname for e in root.iter() if not callable(e.tag)]


# --- 3.x shape --------------------------------------------------------------


@pytest.mark.parametrize(
    "version",
    [SourceVersion.DA_XML_33, SourceVersion.DA_XML_32, SourceVersion.DA_XML_31],
)
def test_3x_writes_the_description_tree(version):
    names = _localnames(_write(_parse(), version))
    for tag in ("Description", "CompleteText", "DetailTxt", "Text",
                "OutlineText", "OutlTxt", "TextOutlTxt"):
        assert tag in names, f"{tag} missing from {version.value} output"


@pytest.mark.parametrize(
    "version",
    [SourceVersion.DA_XML_33, SourceVersion.DA_XML_32, SourceVersion.DA_XML_31],
)
def test_3x_does_not_write_the_2x_spelling(version):
    names = _localnames(_write(_parse(), version))
    assert "ShortText" not in names
    assert "LongText" not in names


def test_inline_span_markup_is_preserved():
    doc = _parse(detail='<span>plain </span><span style="b">bold</span>')
    xml = _write(doc)
    assert xml.count("<span") >= 3, "inline spans dropped"
    assert 'style="b"' in xml, "inline formatting attribute dropped"


def test_short_text_lands_in_outline_text():
    root = etree.fromstring(_write(_parse(outline="My label")).encode())
    outl = [e for e in root.iter() if etree.QName(e).localname == "TextOutlTxt"]
    assert len(outl) == 1
    assert "My label" in "".join(outl[0].itertext())


# --- 2.x keeps the flat spelling -------------------------------------------


def test_2x_still_uses_flat_elements():
    """_translate_to_german renames these; the Description tree has no mapping."""
    xml = _write(_parse(), SourceVersion.DA_XML_20)
    assert "Kurztext" in xml or "Langtext" in xml
    assert "CompleteText" not in xml
    assert "Beschreibung" not in xml


# --- namespace safety -------------------------------------------------------


def test_embedded_markup_does_not_carry_the_source_namespace():
    """Source is DA83/3.2; writing as 3.3 must not leak the old namespace."""
    xml = _write(_parse(), SourceVersion.DA_XML_33)
    namespaces = {
        etree.QName(e).namespace
        for e in etree.fromstring(xml.encode()).iter()
        if not callable(e.tag)
    }
    assert len(namespaces) == 1, f"mixed namespaces in output: {namespaces}"


# --- edge cases -------------------------------------------------------------


def test_item_without_any_text_writes_no_description():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">
  <GAEBInfo><Version>3.2</Version><Date>2026-08-13</Date>
    <ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ>
    <BoQInfo><Name>LV</Name><BoQBkdn><Item Length="4"/></BoQBkdn></BoQInfo>
    <BoQBody><Itemlist><Item RNoPart="0010"><Qty>1.000</Qty><QU>Stk</QU></Item>
    </Itemlist></BoQBody></BoQ></Award></GAEB>"""
    assert "Description" not in _localnames(_write(GAEBParser().parse_string(xml)))


def test_plaintext_long_text_is_rebuilt_as_markup():
    """A 2.x source has no raw_html, so the tree is built from the paragraphs."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
 <GAEBInfo><Version>2.0</Version><Datum>2026-08-13</Datum>
  <Programmsystem>t</Programmsystem></GAEBInfo>
 <Vergabe><Leistungsverzeichnis><LVInfo><Name>LV</Name></LVInfo>
  <LVBereich><Positionsliste><Position RNoPart="0010">
    <Menge>1.000</Menge><Mengeneinheit>Stk</Mengeneinheit>
    <Kurztext>Kurz</Kurztext><Langtext>Lang und ausführlich.</Langtext>
  </Position></Positionsliste></LVBereich>
 </Leistungsverzeichnis></Vergabe></GAEB>"""
    out = _write(GAEBParser().parse_string(xml), SourceVersion.DA_XML_33)
    names = _localnames(out)
    assert "DetailTxt" in names and "Text" in names
    assert "Lang und ausführlich." in out


# --- round trip -------------------------------------------------------------


@pytest.mark.parametrize(
    "version", [SourceVersion.DA_XML_33, SourceVersion.DA_XML_32],
)
def test_fixture_text_round_trips(version):
    doc = GAEBParser().parse(str(FIXTURE))
    again = GAEBParser().parse_string(_write(doc, version))

    before = [(i.short_text, i.long_text.plain_text if i.long_text else None)
              for i in doc.award.boq.iter_items()]
    after = [(i.short_text, i.long_text.plain_text if i.long_text else None)
             for i in again.award.boq.iter_items()]
    assert after == before


def test_fixture_text_is_stable_over_repeated_round_trips():
    doc = GAEBParser().parse(str(FIXTURE))
    seen = []
    for _ in range(3):
        xml = _write(doc, SourceVersion.DA_XML_32)
        doc = GAEBParser().parse_string(xml)
        seen.append([(i.short_text, i.long_text.plain_text if i.long_text else None)
                     for i in doc.award.boq.iter_items()])
    assert seen[0] == seen[1] == seen[2]
