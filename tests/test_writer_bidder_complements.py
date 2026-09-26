"""A bid answers the tender's fields — and only the bidder's.

An X84 carries, per position, the bidder's ``TextComplement`` fields and nothing
else of the text. The writer used to copy every field it found, the issuer's
included, straight from the tender, so a bid echoed the issuer's own values back
and could not carry an answer at all.

The tender here is written for these tests, in the shape of a standard text.
"""

from __future__ import annotations

from decimal import Decimal

from lxml import etree

from pygaeb import ComplementKind, GAEBParser, GAEBWriter, PhaseTransition
from pygaeb.models.enums import ExchangePhase
from pygaeb.models.item import Item

DETAIL = (
    "<Text><p><span>Rinne liefern,</span></p></Text>"
    '<TextComplement Kind="Owner" MarkLbl="31"><ComplCaption>Material </ComplCaption>'
    "<ComplBody><span>'Beton C25/30'</span></ComplBody><ComplTail/></TextComplement>"
    "<Text><p><span>oder gleichwertiger Art,</span></p></Text>"
    '<TextComplement Kind="Bidder" MarkLbl="32" Empty="Yes"><ComplCaption>Material </ComplCaption>'
    "<ComplBody><span>'..........'</span></ComplBody><ComplTail>,</ComplTail></TextComplement>"
    "<Text><p><span>Breite in cm</span></p></Text>"
    '<TextComplement Kind="Bidder" MarkLbl="33" Empty="Yes"><ComplBodyInt Value="0"/>'
    "<ComplBody><span>'....'</span></ComplBody></TextComplement>"
)

TENDER = f"""<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
  <GAEBInfo><Version>3.3</Version><VersDate>2021-05</VersDate><Date>2026-09-26</Date>
    <ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ ID="B1">
    <BoQInfo><Name>LV</Name><BoQBkdn><Item Length="4"/></BoQBkdn></BoQInfo>
    <BoQBody><Itemlist>
      <Item ID="I1" RNoPart="0010"><Qty>12.000</Qty><QU>m</QU>
        <Description><CompleteText>
          <DetailTxt>{DETAIL}</DetailTxt>
          <OutlineText><OutlTxt><TextOutlTxt><span>Rinne</span></TextOutlTxt></OutlTxt></OutlineText>
        </CompleteText></Description>
      </Item>
    </Itemlist></BoQBody>
  </BoQ></Award></GAEB>"""


def bid_item() -> tuple[object, Item]:
    bid = PhaseTransition.tender_to_bid(GAEBParser.parse_string(TENDER))
    item = next(iter(bid.iter_items()))
    assert item.long_text is not None
    return bid, item


def fields(xml: bytes) -> list[etree._Element]:
    root = etree.fromstring(xml)
    return [
        e for e in root.iter()
        if not callable(e.tag) and etree.QName(e).localname == "TextComplement"
    ]


def written(bid: object) -> bytes:
    xml, _ = GAEBWriter.to_bytes(bid, phase=ExchangePhase.X84)  # type: ignore[arg-type]
    return xml


def test_only_the_bidders_fields_go_into_a_bid() -> None:
    """Fails if the writer stops filtering on Kind — the issuer's echo."""
    bid, _ = bid_item()
    assert [f.get("Kind") for f in fields(written(bid))] == ["Bidder", "Bidder"]


def test_an_open_field_is_marked_empty() -> None:
    bid, _ = bid_item()
    open_field = fields(written(bid))[0]

    assert open_field.get("Empty") == "Yes"
    assert "".join(open_field.itertext()).strip() == ""


def test_an_answered_field_carries_the_answer_and_is_not_empty() -> None:
    """Fails if the tender's Empty="Yes" is carried over onto an answer."""
    bid, item = bid_item()
    item.long_text.fill_bidder("32", "Beton C30/37")  # type: ignore[union-attr]

    answered = fields(written(bid))[0]
    assert answered.get("Empty") is None
    assert answered.get("MarkLbl") == "32"
    assert "".join(answered.itertext()).strip() == "Beton C30/37"


def test_a_multi_line_answer_keeps_its_lines() -> None:
    bid, item = bid_item()
    item.long_text.fill_bidder("32", "Fabrikat A\nTyp 7")  # type: ignore[union-attr]

    body = fields(written(bid))[0].find("{*}ComplBody")
    assert body is not None
    assert [etree.QName(c).localname for c in body] == ["span", "br", "span"]


def test_a_numeric_field_writes_its_value() -> None:
    bid, item = bid_item()
    item.long_text.fill_bidder("33", "120")  # type: ignore[union-attr]

    typed = fields(written(bid))[1].find("{*}ComplBodyInt")
    assert typed is not None
    assert typed.get("Value") == "120"


def test_a_numeric_field_answered_in_words_has_no_value() -> None:
    """A wrong Value is worse than none."""
    bid, item = bid_item()
    item.long_text.fill_bidder("33", "etwa 120")  # type: ignore[union-attr]

    assert fields(written(bid))[1].find("{*}ComplBodyInt") is None


def test_an_answer_survives_a_round_trip() -> None:
    bid, item = bid_item()
    item.long_text.fill_bidder("32", "Beton C30/37")  # type: ignore[union-attr]
    item.long_text.fill_bidder("33", "120")  # type: ignore[union-attr]

    again = GAEBParser.parse_bytes(written(bid), filename="bid.X84")
    read = {f.mark: f for f in next(iter(again.iter_items())).long_text.complements}  # type: ignore[union-attr]
    assert read["32"].value == "Beton C30/37"
    assert read["33"].number == Decimal("120")
    assert all(f.kind == ComplementKind.BIDDER for f in read.values())


def test_writing_twice_gives_the_same_bytes() -> None:
    bid, item = bid_item()
    item.long_text.fill_bidder("32", "Beton C30/37")  # type: ignore[union-attr]
    assert written(bid) == written(bid)


def test_a_record_stored_before_fields_were_kept_still_writes_them() -> None:
    """Such a record has the fields only in its markup. Fails without the re-read."""
    bid, item = bid_item()
    item.long_text.complements = []  # type: ignore[union-attr]

    assert [f.get("Kind") for f in fields(written(bid))] == ["Bidder", "Bidder"]
