"""``<UPBkdn>`` — the issuer's demand that a unit price be broken down.

The element says *this position's price must be shown as its components*. In German
public procurement that is what feeds EFB 223 (Aufgliederung der Einheitspreise),
and an incomplete or inconsistent EFB submission normally means the bid is excluded
— so a bidder has to be able to see which positions carry it.

The parser read ``UPComp1..6`` but never the flag that asks for them, and the
writer dropped it, so it did not survive a round trip either.

Its place in the schema is not free: it sits after the position-type markers and
before ``MarkupIt``/``CONo``. Put elsewhere in the Item, the official XSD rejects
the document.
"""

from __future__ import annotations

from pygaeb import GAEBParser, GAEBWriter
from pygaeb.models.enums import ExchangePhase

_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
  <GAEBInfo><Version>3.3</Version><Date>2026-09-24</Date>
    <ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ>
    <BoQInfo><Name>LV</Name>
      <BoQBkdn><Item Length="4"/></BoQBkdn></BoQInfo>
    <BoQBody><Itemlist>
      <Item RNoPart="0010">{flag}<Qty>1.000</Qty><QU>m2</QU>
        <Description><CompleteText><DetailTxt><Text><p><span>Text</span></p></Text>
        </DetailTxt></CompleteText></Description>
      </Item>
    </Itemlist></BoQBody>
  </BoQ></Award></GAEB>"""


def _item(flag: str = ""):
    doc = GAEBParser().parse_string(_DOC.format(flag=flag))
    return next(iter(doc.award.boq.iter_items()))


def _document(flag: str = ""):
    return GAEBParser().parse_string(_DOC.format(flag=flag))


def test_the_flag_is_read() -> None:
    assert _item("<UPBkdn>Yes</UPBkdn>").up_breakdown_required is True


def test_a_position_without_the_flag_does_not_require_a_breakdown() -> None:
    assert _item().up_breakdown_required is False


def test_an_explicit_no_is_not_a_demand() -> None:
    assert _item("<UPBkdn>No</UPBkdn>").up_breakdown_required is False


def test_the_flag_survives_a_write() -> None:
    """Dropped on write, the demand disappears the first time a document is edited."""
    xml, _ = GAEBWriter.to_bytes(_document("<UPBkdn>Yes</UPBkdn>"))

    assert b"<UPBkdn>Yes</UPBkdn>" in xml

    reparsed = GAEBParser().parse_string(xml.decode("utf-8"))
    assert next(iter(reparsed.award.boq.iter_items())).up_breakdown_required is True


def test_it_is_written_before_the_quantity() -> None:
    """The schema puts it after the type markers and before MarkupIt/CONo.

    Emitted anywhere else in the Item, the official XSD refuses the document, so
    the position is part of the contract rather than a detail of formatting.
    """
    xml, _ = GAEBWriter.to_bytes(_document("<UPBkdn>Yes</UPBkdn>"))
    text = xml.decode("utf-8")

    assert text.index("<UPBkdn>") < text.index("<Qty>")


def test_a_bid_does_not_restate_the_demand() -> None:
    """X84 has no UPBkdn element — the tender asked; the bid answers with prices."""
    doc = _document("<UPBkdn>Yes</UPBkdn>")

    xml, warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X84)

    assert b"UPBkdn" not in xml
    assert any("UPBkdn" in warning for warning in warnings)


def test_nothing_is_written_for_a_position_that_does_not_need_one() -> None:
    xml, _ = GAEBWriter.to_bytes(_document())

    assert b"UPBkdn" not in xml
