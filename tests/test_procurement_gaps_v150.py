"""Tests for procurement gaps addressed in v1.5.0.

Covers:
- Totals (BoQInfo, BoQCtgy, Lot level) parsing and writing
- VATPart (multiple VAT rates) parsing and writing
- Item-level VAT parsing and writing
- PrjInfo field completeness parsing and writing
- Procurement item attachments (URI + embedded image)
- Round-trip integrity
- Default-empty regression on new fields
"""

from __future__ import annotations

from decimal import Decimal
from textwrap import dedent

from pygaeb import (
    ExchangePhase,
    GAEBDocument,
    GAEBParser,
    GAEBWriter,
    SourceVersion,
)
from pygaeb.api.document_api import DocumentAPI
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, BoQInfo, Lot, Totals, VATPart
from pygaeb.models.document import AwardInfo
from pygaeb.models.item import Item

# ── XML Fixtures ─────────────────────────────────────────────────────

PROCUREMENT_WITH_TOTALS = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>TestSuite</ProgSystem>
      </GAEBInfo>
      <PrjInfo>
        <NamePrj>Test Project</NamePrj>
        <PrjID>A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4</PrjID>
        <LblPrj>Test Label</LblPrj>
        <Descrip>A sample project description</Descrip>
        <Cur>EUR</Cur>
        <CurLbl>Euro</CurLbl>
        <BidCommPerm>Yes</BidCommPerm>
        <AlterBidPerm>Yes</AlterBidPerm>
        <UPFracDig>3</UPFracDig>
        <CtlgAssign>
          <CtlgID>DIN276</CtlgID>
          <CtlgCode>300</CtlgCode>
        </CtlgAssign>
      </PrjInfo>
      <Award>
        <AwardInfo>
          <Prj>PRJ-001</Prj>
          <PrjName>Test Project</PrjName>
          <Cur>EUR</Cur>
        </AwardInfo>
        <BoQ>
          <BoQInfo>
            <Name>Main BoQ</Name>
            <BoQBkdn>
              <BoQLevel Length="2"/>
              <Item Length="4"/>
            </BoQBkdn>
            <Totals>
              <Total>10000.00</Total>
              <DiscountPcnt>5.000000</DiscountPcnt>
              <DiscountAmt>500.00</DiscountAmt>
              <TotAfterDisc>9500.00</TotAfterDisc>
              <VAT>19.00</VAT>
              <TotalNet>9500.00</TotalNet>
              <TotalNetUpComp>
                <UpComp1>5000.00</UpComp1>
                <UpComp2>4500.00</UpComp2>
              </TotalNetUpComp>
              <VATPart VATPcnt="19.00">
                <TotalNetPart>8000.00</TotalNetPart>
                <VATAmount>1520.00</VATAmount>
              </VATPart>
              <VATPart VATPcnt="7.00">
                <TotalNetPart>1500.00</TotalNetPart>
                <VATAmount>105.00</VATAmount>
              </VATPart>
              <VATAmount>1625.00</VATAmount>
              <TotalGross>11125.00</TotalGross>
            </Totals>
          </BoQInfo>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <LblTx>Section A</LblTx>
              <Totals>
                <Total>5000.00</Total>
                <TotalNet>4750.00</TotalNet>
                <TotalGross>5652.50</TotalGross>
              </Totals>
              <Itemlist>
                <Item RNoPart="0001">
                  <Qty>10.000</Qty>
                  <QU>m2</QU>
                  <UP>500.000</UP>
                  <IT>5000.00</IT>
                  <VAT>19.00</VAT>
                </Item>
              </Itemlist>
            </BoQCtgy>
            <BoQCtgy RNoPart="02">
              <LblTx>Section B</LblTx>
              <Itemlist>
                <Item RNoPart="0001">
                  <Qty>20.000</Qty>
                  <QU>m</QU>
                  <UP>250.000</UP>
                  <IT>5000.00</IT>
                  <VAT>7.00</VAT>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")

ITEM_WITH_ATTACHMENTS = dedent("""\
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
                  <ShortText>Item with attachments</ShortText>
                  <Description>
                    <CompleteText>
                      <DetailTxt>
                        <attachment>https://example.com/plan.pdf</attachment>
                        <Text><p>
                          <image Type="image/png" Name="photo.png">iVBORw0KGgo=</image>
                        </p></Text>
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


# ── Totals Tests ─────────────────────────────────────────────────────


class TestTotalsParsingBoQInfo:
    def _parse(self) -> GAEBDocument:
        return GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)

    def test_boq_info_totals_parsed(self) -> None:
        doc = self._parse()
        t = doc.award.boq.boq_info.totals
        assert t is not None

    def test_total(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert t.total == Decimal("10000.00")

    def test_discount_fields(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert t.discount_pcnt == Decimal("5.000000")
        assert t.discount_amt == Decimal("500.00")
        assert t.tot_after_disc == Decimal("9500.00")

    def test_vat_rate(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert t.vat == Decimal("19.00")

    def test_total_net(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert t.total_net == Decimal("9500.00")

    def test_total_net_up_comp(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert len(t.total_net_up_comp) == 2
        assert t.total_net_up_comp[0] == Decimal("5000.00")
        assert t.total_net_up_comp[1] == Decimal("4500.00")

    def test_vat_parts(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert len(t.vat_parts) == 2
        vp19 = t.vat_parts[0]
        assert vp19.vat_pcnt == Decimal("19.00")
        assert vp19.total_net_part == Decimal("8000.00")
        assert vp19.vat_amount == Decimal("1520.00")
        vp7 = t.vat_parts[1]
        assert vp7.vat_pcnt == Decimal("7.00")
        assert vp7.total_net_part == Decimal("1500.00")
        assert vp7.vat_amount == Decimal("105.00")

    def test_vat_amount(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert t.vat_amount == Decimal("1625.00")

    def test_total_gross(self) -> None:
        t = self._parse().award.boq.boq_info.totals
        assert t.total_gross == Decimal("11125.00")


class TestTotalsParsingBoQCtgy:
    def _parse(self) -> GAEBDocument:
        return GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)

    def test_ctgy_with_totals(self) -> None:
        doc = self._parse()
        ctgy = doc.award.boq.lots[0].body.categories[0]
        assert ctgy.totals is not None
        assert ctgy.totals.total == Decimal("5000.00")
        assert ctgy.totals.total_net == Decimal("4750.00")
        assert ctgy.totals.total_gross == Decimal("5652.50")

    def test_ctgy_without_totals(self) -> None:
        doc = self._parse()
        ctgy = doc.award.boq.lots[0].body.categories[1]
        assert ctgy.totals is None


class TestTotalsWriteRoundTrip:
    def test_boq_info_totals_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse_string(xml_bytes.decode("utf-8"))

        t = doc2.award.boq.boq_info.totals
        assert t is not None
        assert t.total == Decimal("10000.00")
        assert t.discount_pcnt == Decimal("5.000000")
        assert t.vat == Decimal("19.00")
        assert t.total_net == Decimal("9500.00")
        assert len(t.vat_parts) == 2
        assert t.vat_amount == Decimal("1625.00")
        assert t.total_gross == Decimal("11125.00")

    def test_ctgy_totals_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse_string(xml_bytes.decode("utf-8"))

        ctgy = doc2.award.boq.lots[0].body.categories[0]
        assert ctgy.totals is not None
        assert ctgy.totals.total == Decimal("5000.00")

    def test_totals_model_direct(self) -> None:
        """Build a Totals model from scratch and verify writing."""
        totals = Totals(
            total=Decimal("1000"),
            total_lsum=Decimal("1000"),
            vat=Decimal("19"),
            total_gross=Decimal("1190"),
        )
        doc = GAEBDocument(
            exchange_phase=ExchangePhase.X86,
            award=AwardInfo(
                project_name="Direct Test",
                boq=BoQ(
                    boq_info=BoQInfo(name="B1", totals=totals),
                    lots=[Lot(rno="1", label="L1", body=BoQBody())],
                ),
            ),
        )
        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        content = xml_bytes.decode("utf-8")
        assert "<TotalLSUM>1000</TotalLSUM>" in content
        assert "<TotalGross>1190</TotalGross>" in content


# ── Item-level VAT Tests ─────────────────────────────────────────────


class TestItemVAT:
    def test_item_vat_parsed(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        items = list(doc.award.boq.iter_items())
        assert items[0].vat == Decimal("19.00")
        assert items[1].vat == Decimal("7.00")

    def test_item_vat_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse_string(xml_bytes.decode("utf-8"))
        items = list(doc2.award.boq.iter_items())
        assert items[0].vat == Decimal("19.00")
        assert items[1].vat == Decimal("7.00")

    def test_item_vat_default_none(self) -> None:
        item = Item(oz="001")
        assert item.vat is None


# ── PrjInfo Tests ────────────────────────────────────────────────────


class TestPrjInfoParsing:
    def _parse(self) -> GAEBDocument:
        return GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)

    def test_prj_id(self) -> None:
        award = self._parse().award
        assert award.prj_id == "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"

    def test_lbl_prj(self) -> None:
        assert self._parse().award.lbl_prj == "Test Label"

    def test_description(self) -> None:
        assert self._parse().award.description == "A sample project description"

    def test_currency_label(self) -> None:
        assert self._parse().award.currency_label == "Euro"

    def test_bid_comm_perm(self) -> None:
        assert self._parse().award.bid_comm_perm is True

    def test_alter_bid_perm(self) -> None:
        assert self._parse().award.alter_bid_perm is True

    def test_up_frac_dig(self) -> None:
        assert self._parse().award.up_frac_dig == 3

    def test_ctlg_assigns(self) -> None:
        assigns = self._parse().award.ctlg_assigns
        assert len(assigns) == 1
        assert assigns[0].ctlg_id == "DIN276"
        assert assigns[0].ctlg_code == "300"


class TestPrjInfoWriteRoundTrip:
    def test_prjinfo_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        content = xml_bytes.decode("utf-8")

        assert "<PrjInfo>" in content
        assert "<NamePrj>Test Project</NamePrj>" in content
        assert "<PrjID>A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4</PrjID>" in content
        assert "<LblPrj>Test Label</LblPrj>" in content
        assert "<Descrip>A sample project description</Descrip>" in content
        assert "<CurLbl>Euro</CurLbl>" in content
        assert "<BidCommPerm>Yes</BidCommPerm>" in content
        assert "<AlterBidPerm>Yes</AlterBidPerm>" in content
        assert "<UPFracDig>3</UPFracDig>" in content

    def test_prjinfo_reparse(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        xml_bytes, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse_string(xml_bytes.decode("utf-8"))

        assert doc2.award.prj_id == "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
        assert doc2.award.lbl_prj == "Test Label"
        assert doc2.award.description == "A sample project description"
        assert doc2.award.currency_label == "Euro"
        assert doc2.award.bid_comm_perm is True
        assert doc2.award.alter_bid_perm is True
        assert doc2.award.up_frac_dig == 3

    def test_prjinfo_defaults_no_element(self) -> None:
        """AwardInfo with no PrjInfo data should not emit a <PrjInfo> element."""
        doc = GAEBDocument(
            award=AwardInfo(currency="EUR"),
        )
        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        assert b"<PrjInfo>" not in xml_bytes


# ── Attachment Tests ─────────────────────────────────────────────────


class TestProcurementAttachments:
    def test_uri_attachment_parsed(self) -> None:
        doc = GAEBParser.parse_string(ITEM_WITH_ATTACHMENTS)
        items = list(doc.award.boq.iter_items())
        assert len(items) == 1
        uri_attachments = [a for a in items[0].attachments if a.data == b""]
        assert len(uri_attachments) == 1
        assert uri_attachments[0].filename == "https://example.com/plan.pdf"

    def test_embedded_image_parsed(self) -> None:
        doc = GAEBParser.parse_string(ITEM_WITH_ATTACHMENTS)
        items = list(doc.award.boq.iter_items())
        img_attachments = [a for a in items[0].attachments if a.data != b""]
        assert len(img_attachments) == 1
        assert img_attachments[0].filename == "photo.png"
        assert img_attachments[0].mime_type == "image/png"
        assert len(img_attachments[0].data) > 0

    def test_no_attachments_default(self) -> None:
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01">
                    <Itemlist>
                      <Item RNoPart="0001">
                        <ShortText>No attachments</ShortText>
                        <Qty>1</Qty>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml)
        items = list(doc.award.boq.iter_items())
        assert items[0].attachments == []


# ── DocumentAPI Summary Tests ────────────────────────────────────────


class TestDocumentAPISummary:
    def test_summary_includes_totals(self) -> None:
        doc = GAEBParser.parse_string(PROCUREMENT_WITH_TOTALS)
        api = DocumentAPI(doc)
        s = api.summary()
        assert s["total_net"] == "9500.00"
        assert s["total_gross"] == "11125.00"
        assert s["vat_rate"] == "19.00"
        assert s["vat_amount"] == "1625.00"
        assert s["up_frac_dig"] == 3


# ── Default-empty Regression Tests ───────────────────────────────────


class TestNoRegressionOnNewFields:
    def test_item_vat_default(self) -> None:
        item = Item()
        assert item.vat is None

    def test_boq_info_totals_default(self) -> None:
        info = BoQInfo()
        assert info.totals is None

    def test_boq_ctgy_totals_default(self) -> None:
        ctgy = BoQCtgy()
        assert ctgy.totals is None

    def test_lot_totals_default(self) -> None:
        lot = Lot()
        assert lot.totals is None

    def test_award_prjinfo_defaults(self) -> None:
        award = AwardInfo()
        assert award.prj_id is None
        assert award.lbl_prj is None
        assert award.description is None
        assert award.currency_label is None
        assert award.bid_comm_perm is False
        assert award.alter_bid_perm is False
        assert award.up_frac_dig is None
        assert award.ctlg_assigns == []

    def test_totals_model_defaults(self) -> None:
        t = Totals()
        assert t.total is None
        assert t.discount_pcnt is None
        assert t.vat is None
        assert t.total_net is None
        assert t.total_gross is None
        assert t.vat_parts == []
        assert t.total_net_up_comp == []

    def test_vat_part_model(self) -> None:
        vp = VATPart(vat_pcnt=Decimal("19"), total_net_part=Decimal("100"))
        assert vp.vat_pcnt == Decimal("19")
        assert vp.total_net_part == Decimal("100")
        assert vp.vat_amount is None


# ── Lot-level Totals Tests ───────────────────────────────────────────


class TestLotTotals:
    def test_lot_totals_write_roundtrip(self) -> None:
        """Build a multi-lot doc with lot-level totals and verify round-trip."""
        lot1 = Lot(
            rno="1", label="Lot A",
            body=BoQBody(),
            totals=Totals(total=Decimal("5000"), total_gross=Decimal("5950")),
        )
        lot2 = Lot(
            rno="2", label="Lot B",
            body=BoQBody(),
            totals=Totals(total=Decimal("3000"), total_gross=Decimal("3570")),
        )
        doc = GAEBDocument(
            exchange_phase=ExchangePhase.X86,
            award=AwardInfo(
                project_name="Multi-Lot",
                boq=BoQ(
                    boq_info=BoQInfo(name="ML"),
                    lots=[lot1, lot2],
                ),
            ),
        )
        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        content = xml_bytes.decode("utf-8")
        assert "<TotalGross>5950</TotalGross>" in content
        assert "<TotalGross>3570</TotalGross>" in content
