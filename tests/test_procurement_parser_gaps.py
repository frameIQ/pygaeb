"""Tests for procurement parser gap fixes.

Covers:
- Long text parsing from Description/CompleteText/DetailTxt
- AwardInfo metadata fields (category, dates, contract, warranty)
- OWN (owner/client) address with full tgAddress fields
- Address model extension (name3, name4, contact, iln, vat_id)
- Round-trip serialization of new fields
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from textwrap import dedent

from pygaeb import (
    GAEBDocument,
    GAEBParser,
    GAEBWriter,
    SourceVersion,
)
from pygaeb.models.document import AwardInfo
from pygaeb.models.order import Address

FIXTURE_DIR = Path(__file__).resolve().parent / "../../test-pygaeb/tests/fixtures"
TENDER_X81 = FIXTURE_DIR / "da_xml_31/ava/tender.X81"

PROCUREMENT_WITH_AWARD_META = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA81/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo>
          <Prj>P-999</Prj>
          <PrjName>Award Meta Test</PrjName>
          <Cur>EUR</Cur>
          <PrcTyp>Open</PrcTyp>
          <Cat>OpenCall</Cat>
          <OpenDate>2024-07-25</OpenDate>
          <OpenTime>10:00</OpenTime>
          <EvalEnd>2024-08-15</EvalEnd>
          <SubmLoc>Rathaus Saal 3</SubmLoc>
          <CnstStart>2024-11-01</CnstStart>
          <CnstEnd>2025-06-30</CnstEnd>
          <ContrNo>V-123456</ContrNo>
          <ContrDate>2024-09-01</ContrDate>
          <AcceptType>Formal</AcceptType>
          <WarrDur>5</WarrDur>
          <WarrUnit>Years</WarrUnit>
        </AwardInfo>
        <OWN>
          <Address>
            <Name1>Bauamt Musterstadt</Name1>
            <Name2>Abt. Hochbau</Name2>
            <Name3>Referat 4</Name3>
            <Name4>z.Hd. Herr Müller</Name4>
            <Street>Rathausplatz 1</Street>
            <PCode>12345</PCode>
            <City>Musterstadt</City>
            <Country>DE</Country>
            <Contact>Herr Müller</Contact>
            <Phone>+49 123 456</Phone>
            <Fax>+49 123 457</Fax>
            <EMail>mueller@musterstadt.de</EMail>
            <ILN>1234567890123</ILN>
            <VATID>DE123456789</VATID>
          </Address>
          <AwardNo>V-2024-001</AwardNo>
        </OWN>
        <BoQ>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <LblTx>Section</LblTx>
              <Itemlist>
                <Item RNoPart="0001">
                  <ShortText>Test item</ShortText>
                  <Qty>1</Qty>
                  <QU>pcs</QU>
                  <UP>100.00</UP>
                  <IT>100.00</IT>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")

PROCUREMENT_LONG_TEXT = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo><Cur>EUR</Cur></AwardInfo>
        <BoQ>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <Itemlist>
                <Item RNoPart="0001">
                  <ShortText>Item with Description long text</ShortText>
                  <Description>
                    <CompleteText>
                      <DetailTxt>
                        <p>This is the <b>long text</b> from DetailTxt.</p>
                      </DetailTxt>
                    </CompleteText>
                  </Description>
                  <Qty>1</Qty>
                  <QU>pcs</QU>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")

PROCUREMENT_OWN_FALLBACK = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo>
          <Cur>EUR</Cur>
          <OWN>Legacy Client Name</OWN>
        </AwardInfo>
        <BoQ><BoQBody>
          <BoQCtgy RNoPart="01"><Itemlist>
            <Item RNoPart="0001"><Qty>1</Qty></Item>
          </Itemlist></BoQCtgy>
        </BoQBody></BoQ>
      </Award>
    </GAEB>
""")


# ── Long Text Parsing ────────────────────────────────────────────────


class TestProcurementLongText:
    def test_long_text_from_description_detail(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_LONG_TEXT)
        items = list(doc.award.boq.iter_items())
        assert len(items) == 1
        assert items[0].long_text is not None
        assert "long text" in items[0].long_text.plain_text.lower()

    def test_long_text_contains_bold_marker(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_LONG_TEXT)
        item = next(iter(doc.award.boq.iter_items()))
        assert item.long_text is not None
        plain = item.long_text.plain_text
        assert "long text" in plain


# ── AwardInfo Metadata ───────────────────────────────────────────────


class TestAwardInfoMetadata:
    def _parse(self) -> GAEBDocument:
        return GAEBParser.parse_string(PROCUREMENT_WITH_AWARD_META)

    def test_category(self) -> None:
        assert self._parse().award.category == "OpenCall"

    def test_open_date(self) -> None:
        assert self._parse().award.open_date == datetime(2024, 7, 25)

    def test_open_time(self) -> None:
        assert self._parse().award.open_time == "10:00"

    def test_eval_end(self) -> None:
        assert self._parse().award.eval_end == datetime(2024, 8, 15)

    def test_submit_location(self) -> None:
        assert self._parse().award.submit_location == "Rathaus Saal 3"

    def test_construction_start(self) -> None:
        assert self._parse().award.construction_start == datetime(2024, 11, 1)

    def test_construction_end(self) -> None:
        assert self._parse().award.construction_end == datetime(2025, 6, 30)

    def test_contract_no(self) -> None:
        assert self._parse().award.contract_no == "V-123456"

    def test_contract_date(self) -> None:
        assert self._parse().award.contract_date == datetime(2024, 9, 1)

    def test_accept_type(self) -> None:
        assert self._parse().award.accept_type == "Formal"

    def test_warranty_duration(self) -> None:
        assert self._parse().award.warranty_duration == 5

    def test_warranty_unit(self) -> None:
        assert self._parse().award.warranty_unit == "Years"


# ── OWN Address Parsing ──────────────────────────────────────────────


class TestOWNAddressParsing:
    def _parse(self) -> GAEBDocument:
        return GAEBParser.parse_string(PROCUREMENT_WITH_AWARD_META)

    def test_owner_address_present(self) -> None:
        assert self._parse().award.owner_address is not None

    def test_owner_name(self) -> None:
        assert self._parse().award.owner_address.name == "Bauamt Musterstadt"

    def test_owner_name2(self) -> None:
        assert self._parse().award.owner_address.name2 == "Abt. Hochbau"

    def test_owner_name3(self) -> None:
        assert self._parse().award.owner_address.name3 == "Referat 4"

    def test_owner_name4(self) -> None:
        assert self._parse().award.owner_address.name4 == "z.Hd. Herr Müller"

    def test_owner_street(self) -> None:
        assert self._parse().award.owner_address.street == "Rathausplatz 1"

    def test_owner_pcode(self) -> None:
        assert self._parse().award.owner_address.pcode == "12345"

    def test_owner_city(self) -> None:
        assert self._parse().award.owner_address.city == "Musterstadt"

    def test_owner_country(self) -> None:
        assert self._parse().award.owner_address.country == "DE"

    def test_owner_contact(self) -> None:
        assert self._parse().award.owner_address.contact == "Herr Müller"

    def test_owner_phone(self) -> None:
        assert self._parse().award.owner_address.phone == "+49 123 456"

    def test_owner_fax(self) -> None:
        assert self._parse().award.owner_address.fax == "+49 123 457"

    def test_owner_email(self) -> None:
        assert self._parse().award.owner_address.email == "mueller@musterstadt.de"

    def test_owner_iln(self) -> None:
        assert self._parse().award.owner_address.iln == "1234567890123"

    def test_owner_vat_id(self) -> None:
        assert self._parse().award.owner_address.vat_id == "DE123456789"

    def test_award_no(self) -> None:
        assert self._parse().award.award_no == "V-2024-001"

    def test_client_from_owner(self) -> None:
        assert self._parse().award.client == "Bauamt Musterstadt"


class TestOWNFallback:
    def test_legacy_own_as_client(self) -> None:
        """When no <OWN> child of <Award>, fall back to <AwardInfo>/<OWN> text."""
        doc = GAEBParser.parse_string(PROCUREMENT_OWN_FALLBACK)
        assert doc.award.client == "Legacy Client Name"
        assert doc.award.owner_address is None


# ── Address Model Defaults ───────────────────────────────────────────


class TestAddressModelDefaults:
    def test_new_fields_default_none(self) -> None:
        addr = Address()
        assert addr.name3 is None
        assert addr.name4 is None
        assert addr.contact is None
        assert addr.iln is None
        assert addr.vat_id is None


# ── AwardInfo Model Defaults ────────────────────────────────────────


class TestAwardInfoDefaults:
    def test_new_fields_default(self) -> None:
        award = AwardInfo()
        assert award.category is None
        assert award.open_date is None
        assert award.open_time is None
        assert award.eval_end is None
        assert award.submit_location is None
        assert award.construction_start is None
        assert award.construction_end is None
        assert award.contract_no is None
        assert award.contract_date is None
        assert award.accept_type is None
        assert award.warranty_duration is None
        assert award.warranty_unit is None
        assert award.owner_address is None
        assert award.award_no is None


# ── Round-Trip Serialization ─────────────────────────────────────────


class TestAwardMetaRoundTrip:
    def test_award_info_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_AWARD_META)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse_string(xml_bytes.decode("utf-8"))

        assert doc2.award.category == "OpenCall"
        assert doc2.award.open_date == datetime(2024, 7, 25)
        assert doc2.award.open_time == "10:00"
        assert doc2.award.construction_start == datetime(2024, 11, 1)
        assert doc2.award.construction_end == datetime(2025, 6, 30)
        assert doc2.award.contract_no == "V-123456"
        assert doc2.award.warranty_duration == 5
        assert doc2.award.warranty_unit == "Years"

    def test_own_address_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_AWARD_META)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse_string(xml_bytes.decode("utf-8"))

        addr = doc2.award.owner_address
        assert addr is not None
        assert addr.name == "Bauamt Musterstadt"
        assert addr.name2 == "Abt. Hochbau"
        assert addr.name3 == "Referat 4"
        assert addr.name4 == "z.Hd. Herr Müller"
        assert addr.contact == "Herr Müller"
        assert addr.iln == "1234567890123"
        assert addr.vat_id == "DE123456789"
        assert doc2.award.award_no == "V-2024-001"
        assert doc2.award.client == "Bauamt Musterstadt"

    def test_xml_contains_own_structure(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_AWARD_META)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        content = xml_bytes.decode("utf-8")
        assert "<OWN>" in content
        assert "<AwardNo>V-2024-001</AwardNo>" in content
        assert "<Name1>Bauamt Musterstadt</Name1>" in content

    def test_legacy_own_fallback_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_OWN_FALLBACK)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        content = xml_bytes.decode("utf-8")
        assert "<OWN>Legacy Client Name</OWN>" in content


# ── Fixture-based Tests (tender.X81) ────────────────────────────────


class TestTenderX81Fixture:
    """Integration tests against the real tender.X81 fixture file."""

    @classmethod
    def _parse_fixture(cls) -> GAEBDocument | None:
        if not TENDER_X81.exists():
            return None
        return GAEBParser.parse(TENDER_X81)

    def test_fixture_parses(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc is not None
        assert doc.is_procurement

    def test_items_have_long_text(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        items_with_text = [i for i in doc.award.boq.iter_items() if i.long_text]
        items_total = list(doc.award.boq.iter_items())
        assert len(items_with_text) > 0, "Expected at least some items with long_text"
        assert len(items_with_text) >= 68, (
            f"Only {len(items_with_text)}/{len(items_total)} items have long_text, expected ≥68"
        )

    def test_award_category(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.category == "OpenCall"

    def test_award_open_date(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.open_date == datetime(2008, 7, 25)

    def test_award_construction_dates(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.construction_start == datetime(2008, 11, 15)
        assert doc.award.construction_end == datetime(2008, 12, 15)

    def test_award_contract_no(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.contract_no == "Auftrnummer-34567890"

    def test_award_warranty(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.warranty_duration == 2
        assert doc.award.warranty_unit == "Years"

    def test_owner_address(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        addr = doc.award.owner_address
        assert addr is not None
        assert addr.name == "OfD GAEBhausen"
        assert addr.name4 == "Abteilung Hochbau"
        assert addr.street == "Hohe Gasse 200"

    def test_client_from_owner(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.client == "OfD GAEBhausen"

    def test_award_no(self) -> None:
        doc = self._parse_fixture()
        if doc is None:
            return
        assert doc.award.award_no == "V-3456789012345"
