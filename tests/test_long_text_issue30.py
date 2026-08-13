"""Regression tests for issue #30.

`Description/CompleteText` holds the text-supplement flags (`ComplTSA`,
`ComplTSB`) and the `OutlineText` alongside the actual `DetailTxt`. The parser
matched `CompleteText` and then swept the whole subtree into `long_text`, so
every item's long text was prefixed with "No\\nNo" and suffixed with the short
text. Only `DetailTxt` is the long text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pygaeb import GAEBParser

FIXTURE = Path(__file__).parent / "fixtures" / "gaebxml.x83"

_ITEM = """
    <Item RNoPart="0010">
      <Qty>1.000</Qty><QU>Stk</QU>
      <Description>
        <CompleteText>
          <ComplTSA>No</ComplTSA>
          <ComplTSB>No</ComplTSB>
          <DetailTxt><Text><p><span>{detail}</span></p></Text></DetailTxt>
          <OutlineText>
            <OutlTSA>No</OutlTSA>
            <OutlTxt><TextOutlTxt><span>{outline}</span></TextOutlTxt></OutlTxt>
          </OutlineText>
        </CompleteText>
      </Description>
    </Item>
"""

_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">
  <GAEBInfo><Version>3.2</Version><Date>2026-08-13</Date>
    <ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ>
    <BoQInfo><Name>LV</Name>
      <BoQBkdn><Item Length="4"/></BoQBkdn></BoQInfo>
    <BoQBody><Itemlist>{items}</Itemlist></BoQBody>
  </BoQ></Award></GAEB>"""


def _parse_one(detail: str = "The actual long text.", outline: str = "Short label"):
    xml = _DOC.format(items=_ITEM.format(detail=detail, outline=outline))
    doc = GAEBParser().parse_string(xml)
    return next(iter(doc.award.boq.iter_items()))


def test_long_text_excludes_supplement_flags_and_outline():
    item = _parse_one()
    assert item.long_text is not None
    assert item.long_text.plain_text == "The actual long text."


def test_short_text_still_comes_from_outline():
    assert _parse_one().short_text == "Short label"


@pytest.mark.parametrize("junk", ["No", "Short label"])
def test_no_junk_in_any_long_text_representation(junk):
    lt = _parse_one().long_text
    assert junk not in (lt.plain_text or "")
    assert not any(junk == p for p in (lt.paragraphs or []))


def test_paragraphs_are_not_duplicated():
    """The detail text was previously emitted twice — once via Text, once via CompleteText."""
    assert _parse_one().long_text.paragraphs == ["The actual long text."]


def test_detail_txt_directly_under_description_still_read():
    """Not every writer nests DetailTxt inside CompleteText."""
    xml = _DOC.format(items="""
        <Item RNoPart="0010"><Qty>1.000</Qty><QU>Stk</QU>
          <Description>
            <DetailTxt><Text><p><span>Bare detail text.</span></p></Text></DetailTxt>
          </Description>
        </Item>""")
    doc = GAEBParser().parse_string(xml)
    item = next(iter(doc.award.boq.iter_items()))
    assert item.long_text.plain_text == "Bare detail text."


# --- against the real-shaped fixture ---------------------------------------


def test_fixture_long_texts_are_clean():
    doc = GAEBParser().parse(str(FIXTURE))
    items = list(doc.award.boq.iter_items())
    assert len(items) == 6

    for item in items:
        lt = item.long_text
        assert lt is not None
        assert not (lt.plain_text or "").startswith("No"), (
            f"{item.oz}: supplement flag leaked into long text"
        )
        # The outline text must not appear as a paragraph of its own. It may
        # legitimately occur as a word inside the detail text.
        assert item.short_text not in (lt.paragraphs or []), (
            f"{item.oz}: outline text leaked into long text"
        )

    assert items[0].short_text == "Baustelleneinrichtung"
    assert items[0].long_text.plain_text == (
        "Einrichten der Baustelle vor Beginn der Bauarbeiten."
    )
