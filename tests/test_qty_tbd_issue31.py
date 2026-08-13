"""Regression tests for issue #31.

`<QtyTBD>` marks a quantity that is still to be determined, so a missing `<Qty>`
is deliberate rather than absent data. It was neither parsed nor written, which
made those items indistinguishable from items that simply carry no quantity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
      <Item RNoPart="0010">{inner}<QU>m³</QU></Item>
    </Itemlist></BoQBody>
  </BoQ></Award></GAEB>"""


def _item(inner: str):
    doc = GAEBParser().parse_string(_DOC.format(inner=inner))
    return next(iter(doc.award.boq.iter_items()))


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        ("<QtyTBD>Yes</QtyTBD>", True),
        ("<QtyTBD>yes</QtyTBD>", True),
        ("<QtyTBD>true</QtyTBD>", True),
        ("<QtyTBD>1</QtyTBD>", True),
        ("<QtyTBD>No</QtyTBD>", False),
        ("<QtyTBD></QtyTBD>", False),
        ("<Qty>10.000</Qty>", False),
        ("", False),
    ],
)
def test_qty_tbd_parsed(inner, expected):
    assert _item(inner).qty_tbd is expected


def test_qty_tbd_distinguishes_from_plain_missing_quantity():
    tbd = _item("<QtyTBD>Yes</QtyTBD>")
    absent = _item("")
    assert tbd.qty is None and absent.qty is None
    assert tbd.qty_tbd is True
    assert absent.qty_tbd is False


def test_default_is_false():
    from pygaeb.models.item import Item

    assert Item().qty_tbd is False


# --- writer -----------------------------------------------------------------


def _write(doc) -> str:
    return GAEBWriter().to_bytes(doc, target_version=SourceVersion.DA_XML_32)[0].decode()


def test_writer_emits_flag():
    doc = GAEBParser().parse_string(_DOC.format(inner="<QtyTBD>Yes</QtyTBD>"))
    assert "<QtyTBD>Yes</QtyTBD>" in _write(doc)


def test_writer_omits_flag_when_false():
    doc = GAEBParser().parse_string(_DOC.format(inner="<Qty>10.000</Qty>"))
    assert "QtyTBD" not in _write(doc)


def test_round_trip_preserves_flag():
    doc = GAEBParser().parse_string(_DOC.format(inner="<QtyTBD>Yes</QtyTBD>"))
    again = GAEBParser().parse_string(_write(doc))
    item = next(iter(again.award.boq.iter_items()))
    assert item.qty_tbd is True
    assert item.qty is None


# --- against the fixture ----------------------------------------------------


def test_fixture_flags_exactly_the_two_tbd_items():
    doc = GAEBParser().parse(str(FIXTURE))
    items = list(doc.award.boq.iter_items())

    tbd = [i for i in items if i.qty_tbd]
    assert len(tbd) == 2
    assert all(i.qty is None for i in tbd)
    assert {i.short_text for i in tbd} == {"Bodenaushub", "Bodenabfuhr"}

    assert all(i.qty is not None for i in items if not i.qty_tbd)


def test_fixture_round_trip_keeps_both_flags():
    doc = GAEBParser().parse(str(FIXTURE))
    xml = _write(doc)
    assert xml.count("<QtyTBD>Yes</QtyTBD>") == 2

    again = GAEBParser().parse_string(xml)
    assert sum(1 for i in again.award.boq.iter_items() if i.qty_tbd) == 2
