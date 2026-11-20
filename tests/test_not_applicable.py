"""Dropped positions (``<NotAppl>``, "Position entfällt") never count.

The X83, X84 and X85 schemas have no NotAppl: a dropped position is simply not
in a tender or bid. An invoice must not carry one (GAEB DA XML 3.3, §8.1.3.7).
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from pygaeb import ExchangePhase, GAEBDocument, GAEBParser, GAEBWriter, Item, SourceVersion
from pygaeb.builder import BoQBuilder
from pygaeb.parser.gaeb_parser import validate_xml
from tests.conftest import SAMPLE_V33_XML

_XSD_DIR = os.environ.get("PYGAEB_XSD_DIR")


def _contract(flag: str = "Yes") -> GAEBDocument:
    # The sample's three positions total 122319.00; the outer wall (57834.00) is dropped.
    xml = SAMPLE_V33_XML.replace(
        '<Item RNoPart="0020">', f'<Item RNoPart="0020">\n<NotAppl>{flag}</NotAppl>',
    )
    return GAEBParser.parse_bytes(xml.encode(), filename="contract.X86")


def _by_oz(doc: GAEBDocument) -> dict[str, Item]:
    return {i.full_oz: i for i in doc.iter_items() if isinstance(i, Item)}


def test_a_dropped_position_is_read_and_not_summed() -> None:
    doc = _contract()
    dropped = _by_oz(doc)["01.01.0020"]
    assert dropped.not_applicable
    assert not dropped.affects_total
    assert doc.grand_total == Decimal("53235.00") + Decimal("11250.00")


def test_notappl_no_is_an_ordinary_position() -> None:
    doc = _contract("No")
    assert not _by_oz(doc)["01.01.0020"].not_applicable
    assert doc.grand_total == Decimal("122319.00")


def test_a_contract_keeps_the_mark() -> None:
    data, _ = GAEBWriter.to_bytes(_contract(), phase=ExchangePhase.X86)
    again = GAEBParser.parse_bytes(data, filename="contract.X86")
    assert _by_oz(again)["01.01.0020"].not_applicable


@pytest.mark.parametrize("phase", [ExchangePhase.X83, ExchangePhase.X84, ExchangePhase.X89])
def test_tender_bid_and_invoice_leave_it_out(phase: ExchangePhase) -> None:
    data, warnings = GAEBWriter.to_bytes(_contract(), phase=phase)
    again = GAEBParser.parse_bytes(data, filename=f"out.{phase.value}")
    assert "01.01.0020" not in _by_oz(again)
    assert "01.01.0010" in _by_oz(again)
    assert any(w.startswith("not-applicable position not written for 1") for w in warnings)


@pytest.mark.skipif(
    not (_XSD_DIR and Path(_XSD_DIR).is_dir()),
    reason="set PYGAEB_XSD_DIR to the 2021-05 schema folder",
)
@pytest.mark.parametrize(
    "phase", [ExchangePhase.X81, ExchangePhase.X82, ExchangePhase.X83, ExchangePhase.X86],
)
def test_the_output_is_schema_valid(phase: ExchangePhase) -> None:
    builder = BoQBuilder(phase="X86", version="3.3")
    cat = builder.add_category("01", "Rohbau")
    cat.add_item("0010", "Mauerwerk", qty=10, unit="m2", unit_price=45)
    cat.add_item("0020", "Entfällt", qty=5, unit="m2", unit_price=50, not_applicable=True)
    data, _ = GAEBWriter.to_bytes(builder.build(), phase=phase)
    result = validate_xml(data, SourceVersion.DA_XML_33, phase, _XSD_DIR)
    assert result is not None
    assert result.valid, [e.message for e in result.errors]
