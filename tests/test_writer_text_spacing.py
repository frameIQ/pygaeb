"""Long texts keep their spacing through a write: whitespace between runs is content.

The writer pretty-prints its output. Inside a long text that would put each run
on a line of its own, and a re-read would find spaces that were never there:
``"!"`` became ``" ! "``, and ``cm.`` after a text complement became ``cm .``.
Both shapes come from the BVBS test file ``ava/award.X86``.
"""

from __future__ import annotations

from pygaeb import ExchangePhase, GAEBDocument, GAEBParser, GAEBWriter, Item

XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
<GAEBInfo><Version>3.3</Version><ProgSystem>TestSuite</ProgSystem></GAEBInfo>
<Award><AwardInfo><Cur>EUR</Cur></AwardInfo><BoQ>
<BoQInfo><Name>LV</Name><BoQBkdn><BoQLevel Length="2"/><Item Length="4"/></BoQBkdn></BoQInfo>
<BoQBody><BoQCtgy RNoPart="01"><LblTx>Hinweise</LblTx><BoQBody><Itemlist>
<Item RNoPart="0010"><Qty>1</Qty><QU>Stk</QU><Description><CompleteText><DetailTxt><Text>\
<p><span>Achtungszeichen "</span><span style="font-weight:bold;">!</span><span>"</span></p>\
</Text></DetailTxt></CompleteText></Description></Item>
<Item RNoPart="0020"><Qty>1</Qty><QU>Stk</QU><Description><CompleteText><DetailTxt>\
<Text><span>Fenster </span></Text>\
<TextComplement Kind="Owner" MarkLbl="1"><ComplCaption><span>Höhe</span></ComplCaption>\
<ComplBody><span>'90'</span></ComplBody><ComplTail><span>cm</span></ComplTail></TextComplement>\
<Text><span>. Alternativ</span></Text>\
</DetailTxt></CompleteText></Description></Item>
</Itemlist></BoQBody></BoQCtgy></BoQBody>
</BoQ></Award>
</GAEB>
"""


def _texts(doc: GAEBDocument) -> dict[str, str]:
    return {i.full_oz: i.long_text_plain for i in doc.iter_items() if isinstance(i, Item)}


def test_runs_and_text_complements_keep_their_spacing() -> None:
    original = GAEBParser.parse_bytes(XML.encode(), filename="hinweise.X86")
    data, _ = GAEBWriter.to_bytes(original, phase=ExchangePhase.X86)
    again = GAEBParser.parse_bytes(data, filename="again.X86")
    assert _texts(again) == _texts(original)
    assert '"!"' in _texts(again)["01.0010"]
    assert "cm. Alternativ" in _texts(again)["01.0020"]


def test_the_rest_of_the_file_is_still_indented() -> None:
    original = GAEBParser.parse_bytes(XML.encode(), filename="hinweise.X86")
    data, _ = GAEBWriter.to_bytes(original, phase=ExchangePhase.X86)
    text = data.decode("utf-8")
    assert '<span>Achtungszeichen "</span><span' in text  # the runs stay side by side
    assert "\n  <Award>" in text or "\n  <PrjInfo>" in text  # the structure is indented
