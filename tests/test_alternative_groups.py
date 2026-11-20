"""Alternative groups (the Zuordnungszahl): the base counts, alternatives only when awarded.

GAEB DA XML 3.3 opens an Item or MarkupItem with ALNGroupNo and ALNSerNo: serial 0
is the base position (Grundposition), 1 to 9 the alternatives. From the award on,
Accepted records the decision: AltAccept on the alternative taken, BasReject on
the base it replaces. X83 and X85 carry no Accepted, X84 none of the three.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from lxml import etree
from pydantic import ValidationError

from pygaeb import (
    AlternativeDecision,
    AlternativeGroup,
    ExchangePhase,
    GAEBDocument,
    GAEBParser,
    GAEBWriter,
    Item,
    ItemType,
    Provis,
    SourceVersion,
    to_json_string,
)
from pygaeb.builder import BoQBuilder
from pygaeb.parser._xml_safety import SAFE_PARSER
from pygaeb.parser.gaeb_parser import validate_xml
from pygaeb.validation import validate_structure

_XSD_DIR = os.environ.get("PYGAEB_XSD_DIR")

ACCEPT = AlternativeDecision.ALTERNATIVE_ACCEPTED
REJECT = AlternativeDecision.BASE_REJECTED

# A contract for windows and doors. Group 1: plastic windows are the base, wood the
# alternative, not taken, with a markup that belongs to the wood. Group 2: the award
# took the aluminium door and rejected the steel one. What counts: 500 + 800 + 330.
CONTRACT = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
<GAEBInfo><Version>3.3</Version><ProgSystem>TestSuite</ProgSystem></GAEBInfo>
<Award>
<AwardInfo><Cur>EUR</Cur></AwardInfo>
<BoQ>
<BoQInfo>
  <Name>LV</Name>
  <BoQBkdn><BoQLevel Length="2"/><Item Length="4"/></BoQBkdn>
  <Totals><Total>1630.00</Total></Totals>
</BoQInfo>
<BoQBody>
<BoQCtgy RNoPart="01">
  <LblTx>Fenster und Tueren</LblTx>
  <BoQBody><Itemlist>
    <Item RNoPart="0010"><ShortText>Fensterbank</ShortText>
      <Qty>10</Qty><QU>m</QU><UP>50.00</UP><IT>500.00</IT></Item>
    <Item RNoPart="0020"><ALNGroupNo>1</ALNGroupNo><ALNSerNo>0</ALNSerNo>
      <ShortText>Fenster Kunststoff</ShortText>
      <Qty>4</Qty><QU>Stk</QU><UP>200.00</UP><IT>800.00</IT></Item>
    <Item RNoPart="0030"><ALNGroupNo>1</ALNGroupNo><ALNSerNo>1</ALNSerNo>
      <ShortText>Fenster Holz</ShortText>
      <Qty>4</Qty><QU>Stk</QU><UP>250.00</UP><IT>1000.00</IT></Item>
    <MarkupItem RNoPart="0040"><ALNGroupNo>1</ALNGroupNo><ALNSerNo>1</ALNSerNo>
      <ShortText>Zuschlag Holzschutz</ShortText><MarkupType>IdentAsMark</MarkupType>
      <ITMarkup>1000.00</ITMarkup><Markup>5</Markup><IT>50.00</IT></MarkupItem>
    <Item RNoPart="0050"><ALNGroupNo>2</ALNGroupNo><ALNSerNo>0</ALNSerNo>
      <Accepted>BasReject</Accepted><ShortText>Tuer Stahl</ShortText>
      <Qty>2</Qty><QU>Stk</QU><UP>300.00</UP><IT>600.00</IT></Item>
    <Item RNoPart="0060"><ALNGroupNo>2</ALNGroupNo><ALNSerNo>1</ALNSerNo>
      <Accepted>AltAccept</Accepted><ShortText>Tuer Aluminium</ShortText>
      <Qty>2</Qty><QU>Stk</QU><UP>165.00</UP><IT>330.00</IT></Item>
  </Itemlist></BoQBody>
  <Totals><Total>1630.00</Total></Totals>
</BoQCtgy>
</BoQBody>
</BoQ>
</Award>
</GAEB>
"""

#: The Zuordnungszahl each position of CONTRACT carries.
GROUPS = {
    "01.0010": None,
    "01.0020": AlternativeGroup(number=1, serial=0),
    "01.0030": AlternativeGroup(number=1, serial=1),
    "01.0040": AlternativeGroup(number=1, serial=1),
    "01.0050": AlternativeGroup(number=2, serial=0, decision=REJECT),
    "01.0060": AlternativeGroup(number=2, serial=1, decision=ACCEPT),
}


def _contract(xml: str = CONTRACT) -> GAEBDocument:
    return GAEBParser.parse_bytes(xml.encode(), filename="contract.X86")


def _built() -> GAEBDocument:
    """CONTRACT made with the builder, without declared totals."""
    builder = BoQBuilder(phase="X86", version="3.3")
    cat = builder.add_category("01", "Fenster und Tueren")
    cat.add_item("0010", "Fensterbank", qty=10, unit="m", unit_price=50)
    cat.add_item("0020", "Fenster Kunststoff", qty=4, unit="Stk", unit_price=200,
                 alternative_group=GROUPS["01.0020"])
    cat.add_item("0030", "Fenster Holz", qty=4, unit="Stk", unit_price=250,
                 alternative_group=GROUPS["01.0030"])
    cat.add_item("0040", "Zuschlag Holzschutz", item_type=ItemType.MARKUP, unit_price=5,
                 total_price=50, markup_base=1000, markup_type="IdentAsMark",
                 alternative_group=GROUPS["01.0040"])
    cat.add_item("0050", "Tuer Stahl", qty=2, unit="Stk", unit_price=300,
                 alternative_group=GROUPS["01.0050"])
    cat.add_item("0060", "Tuer Aluminium", qty=2, unit="Stk", unit_price=165,
                 alternative_group=GROUPS["01.0060"])
    return builder.build()


def _by_oz(doc: GAEBDocument) -> dict[str, Item]:
    return {i.full_oz: i for i in doc.iter_items() if isinstance(i, Item)}


def _written(
    doc: GAEBDocument, phase: ExchangePhase, **kwargs: Any,
) -> tuple[etree._Element, list[str]]:
    data, warnings = GAEBWriter.to_bytes(doc, phase=phase, **kwargs)
    return etree.fromstring(data, SAFE_PARSER), warnings


def _element(root: etree._Element, tag: str, rno: str) -> etree._Element:
    for el in root.iter():
        if isinstance(el.tag, str) and etree.QName(el).localname == tag \
                and el.get("RNoPart") == rno:
            return el
    raise AssertionError(f"no <{tag} RNoPart={rno!r}> in the output")


def _children(el: etree._Element) -> list[tuple[str, str]]:
    return [
        (etree.QName(child).localname, (child.text or "").strip())
        for child in el if isinstance(child.tag, str)
    ]


def _local_names(root: etree._Element) -> set[str]:
    return {etree.QName(el).localname for el in root.iter() if isinstance(el.tag, str)}


class TestCounting:
    @pytest.mark.parametrize(("serial", "decision", "counts"), [
        (0, None, True),        # the base counts
        (0, REJECT, False),     # ... until the award replaces it
        (1, None, False),       # an alternative is priced, not summed
        (1, ACCEPT, True),      # ... until the award takes it
        (0, ACCEPT, True),      # a decision on the wrong role changes nothing
        (1, REJECT, False),
    ])
    def test_the_group_decides(
        self, serial: int, decision: AlternativeDecision | None, counts: bool,
    ) -> None:
        group = AlternativeGroup(number=1, serial=serial, decision=decision)
        item = Item(oz="0010", total_price=Decimal("100.00"), alternative_group=group)
        assert item.affects_total is counts

    def test_a_dropped_position_never_counts(self) -> None:
        item = Item(oz="0010", not_applicable=True,
                    alternative_group=AlternativeGroup(number=1, serial=0))
        assert not item.affects_total

    def test_a_bedarfsposition_in_a_group_still_follows_provis(self) -> None:
        item = Item(oz="0010", item_type=ItemType.EVENTUAL, provis=Provis.WITHOUT_TOTAL,
                    alternative_group=AlternativeGroup(number=1, serial=0))
        assert not item.affects_total

    def test_a_markup_of_an_alternative_counts_only_with_it(self) -> None:
        markup = Item(oz="0040", item_type=ItemType.MARKUP,
                      alternative_group=AlternativeGroup(number=1, serial=1))
        assert not markup.affects_total
        assert markup.model_copy(update={
            "alternative_group": AlternativeGroup(number=1, serial=1, decision=ACCEPT),
        }).affects_total

    def test_the_type_follows_the_group(self) -> None:
        base = Item(oz="0010", alternative_group=AlternativeGroup(number=1, serial=0))
        alternative = Item(oz="0020", alternative_group=AlternativeGroup(number=1, serial=2))
        lump_sum = Item(oz="0030", item_type=ItemType.LUMP_SUM,
                        alternative_group=AlternativeGroup(number=1, serial=3))
        assert base.item_type is ItemType.BASE_SURCHARGE
        assert alternative.item_type is ItemType.ALTERNATIVE
        assert lump_sum.item_type is ItemType.LUMP_SUM

    def test_without_a_group_a_base_position_counts_and_an_alternative_not(self) -> None:
        assert Item(oz="0010", item_type=ItemType.BASE_SURCHARGE).affects_total
        assert not Item(oz="0020", item_type=ItemType.ALTERNATIVE).affects_total

    @pytest.mark.parametrize(("number", "serial"), [(1000, 0), (1, 10), (-1, 0)])
    def test_the_schema_ranges_hold(self, number: int, serial: int) -> None:
        with pytest.raises(ValidationError):
            AlternativeGroup(number=number, serial=serial)


class TestReading:
    def test_the_zuordnungszahl_is_read(self) -> None:
        found = {oz: item.alternative_group for oz, item in _by_oz(_contract()).items()}
        assert found == GROUPS

    def test_positions_get_their_type(self) -> None:
        types = {oz: item.item_type for oz, item in _by_oz(_contract()).items()}
        assert types == {
            "01.0010": ItemType.NORMAL,
            "01.0020": ItemType.BASE_SURCHARGE,
            "01.0030": ItemType.ALTERNATIVE,
            "01.0040": ItemType.MARKUP,
            "01.0050": ItemType.BASE_SURCHARGE,
            "01.0060": ItemType.ALTERNATIVE,
        }

    def test_only_the_base_and_the_accepted_alternative_count(self) -> None:
        doc = _contract()
        counting = sorted(oz for oz, item in _by_oz(doc).items() if item.affects_total)
        assert counting == ["01.0010", "01.0020", "01.0060"]
        assert doc.grand_total == Decimal("1630.00")

    def test_the_declared_totals_reproduce(self) -> None:
        messages = [r.message for r in _contract().validation_results]
        assert not [m for m in messages if "mismatch" in m or "Alternative group" in m]

    def test_an_invalid_zuordnungszahl_is_reported_and_ignored(self) -> None:
        doc = _contract(CONTRACT.replace(
            'RNoPart="0030"><ALNGroupNo>1</ALNGroupNo><ALNSerNo>1</ALNSerNo>',
            'RNoPart="0030"><ALNGroupNo>1</ALNGroupNo><ALNSerNo>12</ALNSerNo>',
        ))
        item = _by_oz(doc)["01.0030"]
        assert item.alternative_group is None
        assert item.affects_total  # read as an ordinary position, and said so
        assert any("Item 01.0030: Zuordnungszahl not valid" in r.message
                   for r in doc.validation_results)

    def test_an_alternative_area_is_reported(self) -> None:
        doc = _contract(CONTRACT.replace(
            "<LblTx>Fenster und Tueren</LblTx>",
            "<LblTx>Fenster und Tueren</LblTx><ALNBGroupNo>3</ALNBGroupNo>"
            "<ALNBSerNo>1</ALNBSerNo>",
        ))
        assert any("base/alternative areas (ALNBGroupNo) are not supported yet" in r.message
                   for r in doc.validation_results)


class TestWriting:
    def test_a_contract_opens_each_position_with_it(self) -> None:
        root, warnings = _written(_contract(), ExchangePhase.X86)
        assert _children(_element(root, "Item", "0060"))[:3] == [
            ("ALNGroupNo", "2"), ("ALNSerNo", "1"), ("Accepted", "AltAccept"),
        ]
        assert _children(_element(root, "Item", "0020"))[:2] == [
            ("ALNGroupNo", "1"), ("ALNSerNo", "0"),
        ]
        assert _children(_element(root, "MarkupItem", "0040"))[:2] == [
            ("ALNGroupNo", "1"), ("ALNSerNo", "1"),
        ]
        # The real elements replace pyGAEB's own markers, and with them the warning.
        assert not _local_names(root) & {"AlternativeItem", "SurchargeItem"}
        assert not [w for w in warnings if "pyGAEB-internal" in w]

    def test_a_round_trip_keeps_groups_and_totals(self) -> None:
        data, _ = GAEBWriter.to_bytes(_contract(), phase=ExchangePhase.X86)
        again = GAEBParser.parse_bytes(data, filename="again.X86")
        assert {oz: i.alternative_group for oz, i in _by_oz(again).items()} == GROUPS
        assert again.grand_total == Decimal("1630.00")

    def test_json_keeps_them(self) -> None:
        again = GAEBDocument.model_validate_json(to_json_string(_contract()))
        assert {oz: i.alternative_group for oz, i in _by_oz(again).items()} == GROUPS

    def test_a_tender_has_no_decision_yet(self) -> None:
        root, warnings = _written(_contract(), ExchangePhase.X83)
        assert _children(_element(root, "Item", "0060"))[:2] == [
            ("ALNGroupNo", "2"), ("ALNSerNo", "1"),
        ]
        assert "Accepted" not in _local_names(root)
        assert any(w.startswith("Accepted not written for 2 element(s)") for w in warnings)

    def test_a_bid_inherits_it_and_leaves_alternatives_out_of_its_totals(self) -> None:
        root, warnings = _written(_built(), ExchangePhase.X84)
        assert not _local_names(root) & {"ALNGroupNo", "ALNSerNo", "Accepted"}
        assert any(w.startswith("Zuordnungszahl (ALNGroupNo, ALNSerNo) not written for 5")
                   for w in warnings)
        totals = _element(root, "BoQCtgy", "01").find("{*}Totals")
        assert totals is not None
        assert totals.findtext("{*}Total") == "1630.00"

    def test_older_versions_report_it_dropped_and_keep_the_old_marker(self) -> None:
        data, warnings = GAEBWriter.to_bytes(
            _contract(), phase=ExchangePhase.X86, target_version=SourceVersion.DA_XML_32,
        )
        assert any(w.startswith("alternative_group dropped for 5 element(s)") for w in warnings)
        again = _by_oz(GAEBParser.parse_bytes(data, filename="old.X86"))
        assert again["01.0030"].item_type is ItemType.ALTERNATIVE
        assert not again["01.0030"].affects_total

    def test_2x_reports_it_dropped(self) -> None:
        _, warnings = GAEBWriter.to_bytes(
            _contract(), phase=ExchangePhase.X86, target_version=SourceVersion.DA_XML_21,
        )
        assert any(w.startswith("alternative_group dropped for 5 element(s)") for w in warnings)


def _findings(*groups: AlternativeGroup) -> list[str]:
    builder = BoQBuilder(phase="X86", version="3.3")
    cat = builder.add_category("01", "Fenster")
    for n, group in enumerate(groups, start=1):
        cat.add_item(f"{n * 10:04d}", f"Position {n}", qty=1, unit="Stk", unit_price=100,
                     alternative_group=group)
    return [r.message for r in validate_structure(builder.build())]


class TestValidation:
    def test_a_consistent_award_has_no_findings(self) -> None:
        assert _findings(*(g for g in GROUPS.values() if g is not None)) == []

    def test_an_accepted_alternative_with_a_base_still_counting(self) -> None:
        found = _findings(AlternativeGroup(number=1, serial=0),
                          AlternativeGroup(number=1, serial=1, decision=ACCEPT))
        assert any("is not rejected (BasReject), so both count" in m for m in found)

    def test_a_rejected_base_with_nothing_accepted(self) -> None:
        found = _findings(AlternativeGroup(number=1, serial=0, decision=REJECT),
                          AlternativeGroup(number=1, serial=1))
        assert any("adds nothing to the total" in m for m in found)

    def test_two_accepted_alternatives(self) -> None:
        found = _findings(AlternativeGroup(number=1, serial=0, decision=REJECT),
                          AlternativeGroup(number=1, serial=1, decision=ACCEPT),
                          AlternativeGroup(number=1, serial=2, decision=ACCEPT))
        assert any("more than one alternative is accepted (1, 2)" in m for m in found)

    def test_alternatives_without_a_base(self) -> None:
        found = _findings(AlternativeGroup(number=4, serial=1))
        assert any("Alternative group 4 has alternatives but no base position" in m
                   for m in found)

    def test_a_decision_on_the_wrong_role(self) -> None:
        found = _findings(AlternativeGroup(number=1, serial=0, decision=ACCEPT),
                          AlternativeGroup(number=1, serial=1))
        assert any("AltAccept accepts an alternative, but this is the base position" in m
                   for m in found)


@pytest.mark.skipif(
    not (_XSD_DIR and Path(_XSD_DIR).is_dir()),
    reason="set PYGAEB_XSD_DIR to the 2021-05 schema folder",
)
@pytest.mark.parametrize("phase", [
    ExchangePhase.X81, ExchangePhase.X82, ExchangePhase.X83, ExchangePhase.X84,
    ExchangePhase.X85, ExchangePhase.X86,
])
def test_the_output_is_schema_valid(phase: ExchangePhase) -> None:
    data, _ = GAEBWriter.to_bytes(_built(), phase=phase)
    result = validate_xml(data, SourceVersion.DA_XML_33, phase, _XSD_DIR)
    assert result is not None
    assert result.valid, [e.message for e in result.errors]
