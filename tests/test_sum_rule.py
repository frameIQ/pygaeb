"""Which positions enter the sums: Bedarfspositionen mit GB and markup amounts do.

The rule was checked against the BVBS Prüfdateien: in ``ava/award.X86`` the declared
category totals match only when both count.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest

from pygaeb import GAEBParser, GAEBWriter, SourceVersion
from pygaeb.models.enums import ItemType, Provis
from pygaeb.models.item import Item
from pygaeb.validation.totals_validator import validate_totals

FIXTURES = Path(__file__).parent / "fixtures"

INTERLEAVED_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <Award>
    <AwardInfo><Cur>EUR</Cur></AwardInfo>
    <BoQ>
      <BoQInfo><Name>Interleaved</Name><BoQBkdn><BoQLevel Length="2"/></BoQBkdn></BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Section</LblTx>
          <Itemlist>
            <Item RNoPart="0010"><Qty>10</Qty><QU>Stk</QU><UP>100.00</UP><IT>1000.00</IT></Item>
            <MarkupItem RNoPart="0020">
              <MarkupType>AllInCat</MarkupType>
              <ITMarkup>1000.00</ITMarkup><Markup>5.00</Markup><IT>50.00</IT>
            </MarkupItem>
            <Item RNoPart="0030"><Qty>5</Qty><QU>m</QU><UP>50.00</UP><IT>250.00</IT></Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
""")


@pytest.mark.parametrize(
    ("item_type", "provis", "counts"),
    [
        (ItemType.NORMAL, None, True),
        (ItemType.LUMP_SUM, None, True),
        (ItemType.EVENTUAL, Provis.WITH_TOTAL, True),
        (ItemType.EVENTUAL, Provis.WITHOUT_TOTAL, False),
        (ItemType.EVENTUAL, None, False),
        (ItemType.ALTERNATIVE, None, False),
        (ItemType.TEXT_ONLY, None, False),
        (ItemType.MARKUP, None, True),
    ],
)
def test_which_positions_count(item_type: ItemType, provis: Provis | None, counts: bool) -> None:
    assert Item(oz="0010", item_type=item_type, provis=provis).affects_total is counts


def test_sums_match_the_totals_the_file_declares() -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    ctgy = doc.award.boq.lots[0].body.categories[0]

    # 1000 normal + 100 Bedarfsposition mit GB + 500 lump sum + 55 normal + 100 markup.
    assert ctgy.totals is not None
    assert ctgy.subtotal == ctgy.totals.total == Decimal("1755.00")
    assert doc.grand_total == Decimal("1755.00")
    assert not [r for r in validate_totals(doc) if "mismatch" in r.message.lower()]


def test_markups_read_their_base_rate_and_own_amount() -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    markup = next(i for i in doc.iter_items() if i.item_type is ItemType.MARKUP)

    assert markup.markup_base == Decimal("1000.00")
    assert markup.unit_price == Decimal("10.00")
    assert markup.total_price == Decimal("100.00")
    assert markup.computed_total == Decimal("100.00")


def test_markup_base_and_amount_survive_a_round_trip(tmp_path: Path) -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    xml, _ = GAEBWriter.to_bytes(doc)
    out = tmp_path / "round.X86"
    out.write_bytes(xml)

    markup = next(i for i in GAEBParser.parse(out).iter_items() if i.item_type is ItemType.MARKUP)
    assert b"<ITMarkup>1000.00</ITMarkup>" in xml
    assert b"<IT>100.00</IT>" in xml
    assert (markup.markup_base, markup.unit_price, markup.total_price) == (
        Decimal("1000.00"), Decimal("10.00"), Decimal("100.00"),
    )


def test_markups_need_no_quantity_in_phases_that_require_one() -> None:
    xml = (FIXTURES / "synthetic_33.X86").read_text(encoding="utf-8")
    doc = GAEBParser.parse_string(xml.replace("DA86/3.3", "DA83/3.3").replace(
        "<DP>86</DP>", "<DP>83</DP>"))

    assert doc.exchange_phase.value == "X83"
    assert not [r for r in doc.validation_results if "Quantity expected" in r.message]


@pytest.mark.parametrize("version", [SourceVersion.DA_XML_20, SourceVersion.DA_XML_21])
def test_bedarfsposition_mit_gb_survives_da_xml_2x(version: SourceVersion) -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    xml, _ = GAEBWriter.to_bytes(doc, target_version=version)

    back = GAEBParser.parse_string(xml.decode("utf-8"))
    eventual = next(i for i in back.iter_items() if i.item_type is ItemType.EVENTUAL)
    assert eventual.provis is Provis.WITH_TOTAL
    assert back.grand_total == Decimal("1755.00")


def test_comments_inside_an_itemlist_are_skipped() -> None:
    xml = INTERLEAVED_XML.replace("<MarkupItem", "<!-- iTWO -->\n<?pi x?>\n<MarkupItem")

    assert [i.oz for i in GAEBParser.parse_string(xml).iter_items()] == ["0010", "0020", "0030"]


def test_items_and_markups_keep_their_document_order(tmp_path: Path) -> None:
    doc = GAEBParser.parse_string(INTERLEAVED_XML)
    assert [i.oz for i in doc.iter_items()] == ["0010", "0020", "0030"]

    xml, _ = GAEBWriter.to_bytes(doc)
    out = tmp_path / "round.X86"
    out.write_bytes(xml)
    assert [i.oz for i in GAEBParser.parse(out).iter_items()] == ["0010", "0020", "0030"]
    assert doc.grand_total == Decimal("1300.00")
