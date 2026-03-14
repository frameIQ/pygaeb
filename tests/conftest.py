"""Shared fixtures for pyGAEB tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import ExchangePhase, ItemType, SourceVersion
from pygaeb.models.item import Item

SAMPLE_V33_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
    <ProgSystem>TestSuite</ProgSystem>
    <ProgSystemVersion>1.0</ProgSystemVersion>
    <Date>2026-03-14</Date>
  </GAEBInfo>
  <Award>
    <AwardInfo>
      <Prj>PRJ-001</Prj>
      <PrjName>Test Project</PrjName>
      <OWN>Test Client GmbH</OWN>
      <Cur>EUR</Cur>
    </AwardInfo>
    <BoQ>
      <BoQInfo>
        <Name>Main BoQ</Name>
        <BoQBkdn>
          <BoQLevel Length="2"/>
          <BoQLevel Length="2"/>
          <Item Length="4"/>
        </BoQBkdn>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Rohbau</LblTx>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <LblTx>Mauerwerk</LblTx>
              <Itemlist>
                <Item RNoPart="0010">
                  <ShortText>Mauerwerk Innenwand KS 240mm</ShortText>
                  <Qty>1170.000</Qty>
                  <QU>m2</QU>
                  <UP>45.50</UP>
                  <IT>53235.00</IT>
                </Item>
                <Item RNoPart="0020">
                  <ShortText>Mauerwerk Aussenwand KS 365mm</ShortText>
                  <Qty>850.500</Qty>
                  <QU>m2</QU>
                  <UP>68.00</UP>
                  <IT>57834.00</IT>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQCtgy>
        <BoQCtgy RNoPart="02">
          <LblTx>Ausbau</LblTx>
          <Itemlist>
            <Item RNoPart="0010">
              <ShortText>Innentuer Holz einflügelig</ShortText>
              <Qty>25</Qty>
              <QU>Stk</QU>
              <UP>450.00</UP>
              <IT>11250.00</IT>
            </Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
"""

SAMPLE_V20_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
  <GAEBInfo>
    <Version>2.0</Version>
    <Programmsystem>TestSuite</Programmsystem>
  </GAEBInfo>
  <Vergabe>
    <VergabeInfo>
      <Projekt>PRJ-002</Projekt>
      <ProjektName>Altbau Sanierung</ProjektName>
      <Waehrung>EUR</Waehrung>
    </VergabeInfo>
    <Leistungsverzeichnis>
      <LVInfo>
        <Name>Sanierungs-LV</Name>
      </LVInfo>
      <LVBereich>
        <LVGruppe RNoPart="01">
          <Bezeichnung>Abbrucharbeiten</Bezeichnung>
          <Positionsliste>
            <Position RNoPart="0010">
              <Kurztext>Abbruch Mauerwerk</Kurztext>
              <Menge>350.000</Menge>
              <Mengeneinheit>m3</Mengeneinheit>
              <Einheitspreis>25.00</Einheitspreis>
              <Gesamtbetrag>8750.00</Gesamtbetrag>
            </Position>
          </Positionsliste>
        </LVGruppe>
      </LVBereich>
    </Leistungsverzeichnis>
  </Vergabe>
</GAEB>
"""

MALFORMED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
  </GAEBInfo>
  <Award>
    <AwardInfo>
      <Cur>EUR</Cur>
    </AwardInfo>
    <BoQ>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Test & Category</LblTx>
          <Itemlist>
            <Item RNoPart="0010">
              <ShortText>Item with bare & ampersand</ShortText>
              <Qty>10</Qty>
              <QU>Stk</QU>
            </Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
"""


@pytest.fixture
def sample_v33_file(tmp_path: Path) -> Path:
    f = tmp_path / "tender.X83"
    f.write_text(SAMPLE_V33_XML, encoding="utf-8")
    return f


@pytest.fixture
def sample_v20_file(tmp_path: Path) -> Path:
    f = tmp_path / "old.D83"
    f.write_text(SAMPLE_V20_XML, encoding="utf-8")
    return f


@pytest.fixture
def malformed_file(tmp_path: Path) -> Path:
    f = tmp_path / "bad.X83"
    f.write_text(MALFORMED_XML, encoding="utf-8")
    return f


@pytest.fixture
def sample_document() -> GAEBDocument:
    """Create a fully-populated GAEBDocument for testing."""
    items = [
        Item(
            oz="01.01.0010",
            short_text="Mauerwerk Innenwand",
            qty=Decimal("1170.000"),
            unit="m2",
            unit_price=Decimal("45.50"),
            total_price=Decimal("53235.00"),
            item_type=ItemType.NORMAL,
            hierarchy_path=["Rohbau", "Mauerwerk"],
        ),
        Item(
            oz="01.01.0020",
            short_text="Mauerwerk Aussenwand",
            qty=Decimal("850.500"),
            unit="m2",
            unit_price=Decimal("68.00"),
            total_price=Decimal("57834.00"),
            item_type=ItemType.NORMAL,
            hierarchy_path=["Rohbau", "Mauerwerk"],
        ),
        Item(
            oz="02.01.0010",
            short_text="Innentuer Holz",
            qty=Decimal("25"),
            unit="Stk",
            unit_price=Decimal("450.00"),
            total_price=Decimal("11250.00"),
            item_type=ItemType.NORMAL,
            hierarchy_path=["Ausbau"],
        ),
    ]

    ctgy1 = BoQCtgy(rno="01", label="Mauerwerk", items=items[:2])
    ctgy2 = BoQCtgy(rno="02", label="Ausbau", items=[items[2]])
    body = BoQBody(categories=[ctgy1, ctgy2])
    lot = Lot(rno="1", label="Default", body=body)

    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=ExchangePhase.X83,
        gaeb_info=GAEBInfo(version="3.3", prog_system="pyGAEB"),
        award=AwardInfo(
            project_no="PRJ-001",
            project_name="Test Project",
            currency="EUR",
            boq=BoQ(lots=[lot]),
        ),
    )


@pytest.fixture
def multi_lot_document() -> GAEBDocument:
    """Create a GAEBDocument with multiple lots."""
    lot1_items = [
        Item(
            oz="01.0010",
            short_text="Erdarbeiten Aushub",
            qty=Decimal("500"),
            unit="m3",
            unit_price=Decimal("12.00"),
            total_price=Decimal("6000.00"),
            item_type=ItemType.NORMAL,
        ),
    ]
    lot2_items = [
        Item(
            oz="01.0010",
            short_text="Stahlbeton C25/30",
            qty=Decimal("80"),
            unit="m3",
            unit_price=Decimal("180.00"),
            total_price=Decimal("14400.00"),
            item_type=ItemType.NORMAL,
        ),
        Item(
            oz="01.0020",
            short_text="Eventualposition Pfahlgründung",
            qty=Decimal("1"),
            unit="psch",
            unit_price=Decimal("25000.00"),
            total_price=Decimal("25000.00"),
            item_type=ItemType.EVENTUAL,
        ),
    ]
    lot1 = Lot(
        rno="1", label="Los 1 - Erdarbeiten",
        body=BoQBody(categories=[BoQCtgy(rno="01", label="Erdarbeiten", items=lot1_items)]),
    )
    lot2 = Lot(
        rno="2", label="Los 2 - Betonarbeiten",
        body=BoQBody(categories=[BoQCtgy(rno="01", label="Beton", items=lot2_items)]),
    )
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=ExchangePhase.X83,
        award=AwardInfo(boq=BoQ(lots=[lot1, lot2])),
    )
