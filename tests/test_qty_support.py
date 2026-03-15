"""Tests for GAEB quantity determination phase support (X31)."""

from __future__ import annotations

from decimal import Decimal
from textwrap import dedent

from pygaeb import (
    DocumentKind,
    ExchangePhase,
    GAEBDocument,
    GAEBParser,
    GAEBWriter,
)
from pygaeb.api.document_api import DocumentAPI
from pygaeb.models.enums import BkdnType
from pygaeb.models.quantity import (
    Catalog,
    CtlgAssign,
    PrjInfoQD,
    QDetermItem,
    QtyAttachment,
    QtyBoQ,
    QtyBoQBody,
    QtyBoQCtgy,
    QtyDetermination,
    QtyItem,
)

X31_XML = dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>TestSystem</ProgSystem>
        <Date>2024-01-15</Date>
      </GAEBInfo>
      <QtyDeterm>
        <PrjInfo>
          <RefPrjName>Highway Bridge Project</RefPrjName>
          <RefPrjID>PRJ-2024-001</RefPrjID>
        </PrjInfo>
        <QtyDetermInfo>
          <MethodDescription>REB23003-2009</MethodDescription>
          <OrdDescr>Contract 42</OrdDescr>
          <ProjDescr>Bridge Expansion</ProjDescr>
          <ServiceProvisionStartDate>2024-02-01</ServiceProvisionStartDate>
          <ServiceProvisionEndDate>2024-06-30</ServiceProvisionEndDate>
          <Creator>
            <Address>
              <Name>Surveyor Inc.</Name>
              <City>Berlin</City>
            </Address>
          </Creator>
          <Profiler>
            <Address>
              <Name>QA Corp.</Name>
              <City>Munich</City>
            </Address>
          </Profiler>
          <CtlgAssign>
            <CtlgID>CAT1</CtlgID>
            <CtlgCode>300</CtlgCode>
          </CtlgAssign>
        </QtyDetermInfo>
        <DP>31</DP>
        <OWN>
          <Address>
            <Name>City of Berlin</Name>
            <Street>Main St. 1</Street>
            <PCode>10115</PCode>
            <City>Berlin</City>
          </Address>
        </OWN>
        <CTR>
          <Address>
            <Name>BuildCorp GmbH</Name>
            <City>Hamburg</City>
          </Address>
        </CTR>
        <BoQ ID="B1">
          <RefBoQName>Tender BoQ 2024</RefBoQName>
          <RefBoQID>BOQ-GUID-001</RefBoQID>
          <BoQBkdn>
            <Type>BoQLevel</Type>
            <Length>2</Length>
          </BoQBkdn>
          <BoQBkdn>
            <Type>Item</Type>
            <Length>4</Length>
          </BoQBkdn>
          <Ctlg>
            <CtlgID>CAT1</CtlgID>
            <CtlgType>cost group DIN 276 2018-12</CtlgType>
            <CtlgName>DIN 276</CtlgName>
            <CtlgAssignType>Unique</CtlgAssignType>
          </Ctlg>
          <Ctlg>
            <CtlgID>CAT2</CtlgID>
            <CtlgType>BIM</CtlgType>
            <CtlgName>BIM Reference</CtlgName>
          </Ctlg>
          <BoQBody>
            <BoQCtgy ID="C01" RNoPart="01">
              <CtlgAssign>
                <CtlgID>CAT1</CtlgID>
                <CtlgCode>300</CtlgCode>
              </CtlgAssign>
              <BoQBody>
                <BoQCtgy ID="C0101" RNoPart="01">
                  <Itemlist>
                    <Item ID="I010100010" RNoPart="0010" RNoIndex="A">
                      <QtyDeterm>
                        <Qty>125.500</Qty>
                        <QDetermItem>
                          <QTakeoff Row="11 12.500   10.040.Fundament A"/>
                          <CtlgAssign>
                            <CtlgID>CAT2</CtlgID>
                            <CtlgCode>GUID-BIM-001</CtlgCode>
                          </CtlgAssign>
                        </QDetermItem>
                        <QDetermItem>
                          <QTakeoff Row="11 13.000   10.040.Fundament B"/>
                        </QDetermItem>
                      </QtyDeterm>
                      <CtlgAssign>
                        <CtlgID>CAT1</CtlgID>
                        <CtlgCode>300.1</CtlgCode>
                        <Quantity>100</Quantity>
                      </CtlgAssign>
                    </Item>
                    <Item ID="I010100020" RNoPart="0020">
                      <QtyDeterm>
                        <Qty>42.000</Qty>
                        <QDetermItem>
                          <QTakeoff Row="11  6.000    7.000.Stuetze C1"/>
                        </QDetermItem>
                      </QtyDeterm>
                    </Item>
                  </Itemlist>
                </BoQCtgy>
              </BoQBody>
            </BoQCtgy>
            <BoQCtgy ID="C02" RNoPart="02">
              <Itemlist>
                <Item ID="I020010" RNoPart="0010">
                  <QtyDeterm>
                    <Qty>88.250</Qty>
                  </QtyDeterm>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
          <CtlgAssign>
            <CtlgID>CAT1</CtlgID>
            <CtlgCode>300</CtlgCode>
          </CtlgAssign>
          <CtlgAttachment>
            <Attachment>
              <Name>photo1</Name>
              <Text>Foundation photo</Text>
              <Descrip>Photo of foundation excavation</Descrip>
              <Type>jpeg</Type>
              <Data>dGVzdGltYWdl</Data>
            </Attachment>
            <Attachment>
              <Name>plan1</Name>
              <Text>Site plan</Text>
              <Type>pdf</Type>
              <Data>cGRmZGF0YQ==</Data>
            </Attachment>
          </CtlgAttachment>
        </BoQ>
      </QtyDeterm>
    </GAEB>
""")


# ======================================================================
# Model tests
# ======================================================================


class TestQtyModels:
    def test_qty_item_repr(self):
        item = QtyItem(oz="01.0010", qty=Decimal("42"), determ_items=[QDetermItem()])
        r = repr(item)
        assert "01.0010" in r
        assert "42" in r
        assert "rows=1" in r

    def test_qty_item_no_qty(self):
        item = QtyItem(oz="01.0020")
        assert item.qty is None
        assert item.determ_items == []

    def test_qty_boq_ctgy_iter(self):
        child = QtyBoQCtgy(rno="01", items=[QtyItem(oz="01.0010")])
        parent = QtyBoQCtgy(rno="00", subcategories=[child])
        items = list(parent.iter_items())
        assert len(items) == 1
        assert items[0].oz == "01.0010"

    def test_qty_boq_body_iter(self):
        body = QtyBoQBody(
            categories=[
                QtyBoQCtgy(rno="01", items=[QtyItem(oz="01.0010")]),
                QtyBoQCtgy(rno="02", items=[QtyItem(oz="02.0010")]),
            ]
        )
        items = list(body.iter_items())
        assert len(items) == 2

    def test_qty_boq_get_item(self):
        boq = QtyBoQ(
            body=QtyBoQBody(
                categories=[
                    QtyBoQCtgy(
                        rno="01",
                        items=[
                            QtyItem(oz="01.0010", qty=Decimal("10")),
                            QtyItem(oz="01.0020", qty=Decimal("20")),
                        ],
                    ),
                ]
            )
        )
        assert boq.get_item("01.0010") is not None
        assert boq.get_item("01.0020") is not None
        assert boq.get_item("99.9999") is None

    def test_qty_boq_hierarchy(self):
        boq = QtyBoQ(
            body=QtyBoQBody(
                categories=[
                    QtyBoQCtgy(
                        rno="01",
                        subcategories=[QtyBoQCtgy(rno="01a")],
                    ),
                ]
            )
        )
        hierarchy = list(boq.iter_hierarchy())
        assert len(hierarchy) == 2
        assert hierarchy[0][0] == 0
        assert hierarchy[0][1] == "01"
        assert hierarchy[1][0] == 1
        assert hierarchy[1][1] == "01a"

    def test_qty_determination_grand_total_zero(self):
        qd = QtyDetermination()
        assert qd.grand_total == Decimal("0")

    def test_qty_determination_item_count(self):
        qd = QtyDetermination(
            boq=QtyBoQ(
                body=QtyBoQBody(
                    categories=[
                        QtyBoQCtgy(rno="01", items=[QtyItem(), QtyItem()]),
                    ]
                )
            )
        )
        assert qd.item_count == 2

    def test_qty_attachment_mime(self):
        att = QtyAttachment(name="photo1", file_type="jpeg", data=b"test")
        assert att.mime_type == "image/jpeg"
        assert att.size_bytes == 4

    def test_qty_attachment_base64(self):
        att = QtyAttachment(name="plan", file_type="pdf", data=b"pdfdata")
        assert att.data_base64 == "cGRmZGF0YQ=="

    def test_qty_attachment_empty(self):
        att = QtyAttachment()
        assert att.data_base64 == ""
        assert att.mime_type == "application/octet-stream"

    def test_ctlg_assign_with_quantity(self):
        ca = CtlgAssign(ctlg_id="C1", ctlg_code="300", quantity=Decimal("50"))
        assert ca.quantity == Decimal("50")

    def test_catalog(self):
        cat = Catalog(
            ctlg_id="C1", ctlg_type="BIM", ctlg_name="BIM Ref", assign_type="Unique",
        )
        assert cat.ctlg_type == "BIM"

    def test_prj_info_qd(self):
        pi = PrjInfoQD(ref_prj_name="Test", ref_prj_id="P1")
        assert pi.ref_prj_name == "Test"


# ======================================================================
# Parser tests
# ======================================================================


class TestQtyParser:
    def _parse(self, keep_xml: bool = False) -> GAEBDocument:
        return GAEBParser.parse_string(X31_XML, filename="test.X31", keep_xml=keep_xml)

    def test_document_kind(self):
        doc = self._parse()
        assert doc.document_kind == DocumentKind.QUANTITY
        assert doc.is_quantity

    def test_exchange_phase(self):
        doc = self._parse()
        assert doc.exchange_phase == ExchangePhase.X31

    def test_gaeb_info(self):
        doc = self._parse()
        assert doc.gaeb_info.version == "3.3"
        assert doc.gaeb_info.prog_system == "TestSystem"

    def test_prj_info(self):
        doc = self._parse()
        assert doc.qty_determination is not None
        assert doc.qty_determination.prj_info is not None
        assert doc.qty_determination.prj_info.ref_prj_name == "Highway Bridge Project"
        assert doc.qty_determination.prj_info.ref_prj_id == "PRJ-2024-001"

    def test_qty_determ_info(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert qd.info.method == "REB23003-2009"
        assert qd.info.order_descr == "Contract 42"
        assert qd.info.project_descr == "Bridge Expansion"
        assert qd.info.service_start is not None
        assert qd.info.service_start.year == 2024
        assert qd.info.service_start.month == 2
        assert qd.info.service_end is not None
        assert qd.info.service_end.month == 6

    def test_creator_profiler(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert qd.info.creator is not None
        assert qd.info.creator.name == "Surveyor Inc."
        assert qd.info.creator.city == "Berlin"
        assert qd.info.profiler is not None
        assert qd.info.profiler.name == "QA Corp."

    def test_info_ctlg_assign(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert len(qd.info.ctlg_assigns) == 1
        assert qd.info.ctlg_assigns[0].ctlg_id == "CAT1"

    def test_dp(self):
        doc = self._parse()
        assert doc.qty_determination is not None
        assert doc.qty_determination.dp == "31"

    def test_owner_contractor(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert qd.owner is not None
        assert qd.owner.name == "City of Berlin"
        assert qd.owner.street == "Main St. 1"
        assert qd.owner.pcode == "10115"
        assert qd.contractor is not None
        assert qd.contractor.name == "BuildCorp GmbH"

    def test_boq_refs(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert qd.boq.ref_boq_name == "Tender BoQ 2024"
        assert qd.boq.ref_boq_id == "BOQ-GUID-001"

    def test_boq_bkdn(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert len(qd.boq.bkdn) == 2
        assert qd.boq.bkdn[0].bkdn_type == BkdnType.BOQ_LEVEL
        assert qd.boq.bkdn[0].length == 2
        assert qd.boq.bkdn[1].bkdn_type == BkdnType.ITEM
        assert qd.boq.bkdn[1].length == 4

    def test_catalogs(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert len(qd.boq.catalogs) == 2
        assert qd.boq.catalogs[0].ctlg_id == "CAT1"
        assert qd.boq.catalogs[0].ctlg_type == "cost group DIN 276 2018-12"
        assert qd.boq.catalogs[0].assign_type == "Unique"
        assert qd.boq.catalogs[1].ctlg_type == "BIM"

    def test_categories(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        cats = qd.boq.body.categories
        assert len(cats) == 2
        assert cats[0].rno == "01"
        assert cats[1].rno == "02"

    def test_nested_category(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        outer = qd.boq.body.categories[0]
        assert len(outer.subcategories) == 1
        inner = outer.subcategories[0]
        assert inner.rno == "01"
        assert len(inner.items) == 2

    def test_item_count(self):
        doc = self._parse()
        assert doc.item_count == 3

    def test_iter_items(self):
        doc = self._parse()
        items = list(doc.iter_items())
        assert len(items) == 3

    def test_item_oz_resolved(self):
        doc = self._parse()
        items = list(doc.iter_items())
        ozs = [i.oz for i in items]
        assert "01.01.0010.A" in ozs
        assert "01.01.0020" in ozs
        assert "02.0010" in ozs

    def test_item_qty(self):
        doc = self._parse()
        items = list(doc.iter_items())
        first = next(i for i in items if "0010.A" in i.oz)
        assert first.qty == Decimal("125.500")

    def test_determ_items(self):
        doc = self._parse()
        items = list(doc.iter_items())
        first = next(i for i in items if "0010.A" in i.oz)
        assert len(first.determ_items) == 2
        assert "Fundament A" in first.determ_items[0].takeoff_row.raw
        assert "Fundament B" in first.determ_items[1].takeoff_row.raw

    def test_determ_item_ctlg_assign(self):
        doc = self._parse()
        items = list(doc.iter_items())
        first = next(i for i in items if "0010.A" in i.oz)
        assert len(first.determ_items[0].ctlg_assigns) == 1
        assert first.determ_items[0].ctlg_assigns[0].ctlg_code == "GUID-BIM-001"

    def test_item_ctlg_assign_with_quantity(self):
        doc = self._parse()
        items = list(doc.iter_items())
        first = next(i for i in items if "0010.A" in i.oz)
        assert len(first.ctlg_assigns) == 1
        assert first.ctlg_assigns[0].quantity == Decimal("100")

    def test_boq_ctlg_assign(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert len(qd.boq.ctlg_assigns) == 1

    def test_ctgy_ctlg_assign(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        outer = qd.boq.body.categories[0]
        assert len(outer.ctlg_assigns) == 1
        assert outer.ctlg_assigns[0].ctlg_code == "300"

    def test_attachments(self):
        doc = self._parse()
        qd = doc.qty_determination
        assert qd is not None
        assert len(qd.boq.attachments) == 2

        photo = qd.boq.attachments[0]
        assert photo.name == "photo1"
        assert photo.text == "Foundation photo"
        assert photo.description == "Photo of foundation excavation"
        assert photo.file_type == "jpeg"
        assert photo.data == b"testimage"
        assert photo.mime_type == "image/jpeg"

        plan = qd.boq.attachments[1]
        assert plan.name == "plan1"
        assert plan.file_type == "pdf"
        assert plan.data == b"pdfdata"

    def test_grand_total_zero(self):
        doc = self._parse()
        assert doc.grand_total == Decimal("0")

    def test_keep_xml(self):
        doc = self._parse(keep_xml=True)
        assert doc.xml_root is not None
        items = list(doc.iter_items())
        for item in items:
            assert item.source_element is not None

    def test_item_no_qty_determ(self):
        xml = dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA31/3.3">
              <GAEBInfo><Version>3.3</Version><Date>2024-01-01</Date></GAEBInfo>
              <QtyDeterm>
                <QtyDetermInfo>
                  <MethodDescription>REB23003-2009</MethodDescription>
                </QtyDetermInfo>
                <DP>31</DP>
                <BoQ ID="B1">
                  <BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn>
                  <BoQBody>
                    <Itemlist>
                      <Item ID="I1" RNoPart="0010"/>
                    </Itemlist>
                  </BoQBody>
                </BoQ>
              </QtyDeterm>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="test.X31")
        items = list(doc.iter_items())
        assert len(items) == 1
        assert items[0].qty is None
        assert items[0].determ_items == []


# ======================================================================
# DocumentAPI tests
# ======================================================================


class TestQtyDocumentAPI:
    def _api(self) -> DocumentAPI:
        doc = GAEBParser.parse_string(X31_XML, filename="test.X31")
        return DocumentAPI(doc)

    def test_is_quantity(self):
        api = self._api()
        assert api.is_quantity
        assert not api.is_procurement
        assert not api.is_trade
        assert not api.is_cost
        assert api.document_kind == DocumentKind.QUANTITY

    def test_qty_determination_accessor(self):
        api = self._api()
        assert api.qty_determination is not None
        assert api.qty_determination.info.method == "REB23003-2009"

    def test_iter_items(self):
        api = self._api()
        items = list(api.iter_items())
        assert len(items) == 3

    def test_get_qty_item(self):
        api = self._api()
        item = api.get_qty_item("01.01.0010.A")
        assert item is not None
        assert item.qty == Decimal("125.500")

    def test_get_qty_item_not_found(self):
        api = self._api()
        assert api.get_qty_item("99.9999") is None

    def test_iter_hierarchy(self):
        api = self._api()
        hierarchy = list(api.iter_hierarchy())
        assert len(hierarchy) >= 2

    def test_summary(self):
        api = self._api()
        s = api.summary()
        assert s["document_kind"] == "quantity"
        assert s["total_items"] == 3
        assert s["method"] == "REB23003-2009"
        assert s["ref_boq_name"] == "Tender BoQ 2024"
        assert s["catalogs"] == 2
        assert s["attachments"] == 2
        assert s["grand_total"] == "0"

    def test_filter_items_predicate(self):
        api = self._api()
        items = api.filter_items(predicate=lambda i: i.qty is not None and i.qty > 100)
        assert len(items) == 1
        assert items[0].qty == Decimal("125.500")

    def test_custom_tag_with_keep_xml(self):
        doc = GAEBParser.parse_string(X31_XML, filename="test.X31", keep_xml=True)
        api = DocumentAPI(doc)
        items = list(api.iter_items())
        for item in items:
            assert item.source_element is not None


# ======================================================================
# Writer tests
# ======================================================================


class TestQtyWriter:
    def _roundtrip(self, tmp_path) -> GAEBDocument:
        doc = GAEBParser.parse_string(X31_XML, filename="test.X31")
        out = tmp_path / "out.X31"
        GAEBWriter.write(doc, out, phase=ExchangePhase.X31)
        return GAEBParser.parse(out)

    def test_roundtrip_item_count(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        assert doc2.item_count == 3

    def test_roundtrip_kind(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        assert doc2.document_kind == DocumentKind.QUANTITY

    def test_roundtrip_prj_info(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        assert doc2.qty_determination is not None
        assert doc2.qty_determination.prj_info is not None
        assert doc2.qty_determination.prj_info.ref_prj_name == "Highway Bridge Project"

    def test_roundtrip_info(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        assert doc2.qty_determination is not None
        assert doc2.qty_determination.info.method == "REB23003-2009"
        assert doc2.qty_determination.info.order_descr == "Contract 42"

    def test_roundtrip_owner(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert qd.owner is not None
        assert qd.owner.name == "City of Berlin"

    def test_roundtrip_boq_refs(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert qd.boq.ref_boq_name == "Tender BoQ 2024"
        assert qd.boq.ref_boq_id == "BOQ-GUID-001"

    def test_roundtrip_catalogs(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert len(qd.boq.catalogs) == 2
        assert qd.boq.catalogs[0].ctlg_type == "cost group DIN 276 2018-12"

    def test_roundtrip_qty(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        items = list(doc2.iter_items())
        first = next(i for i in items if i.qty == Decimal("125.500"))
        assert first is not None

    def test_roundtrip_takeoff_rows(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        items = list(doc2.iter_items())
        first = next(i for i in items if i.qty == Decimal("125.500"))
        assert len(first.determ_items) == 2
        assert "Fundament A" in first.determ_items[0].takeoff_row.raw

    def test_roundtrip_attachments(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert len(qd.boq.attachments) == 2
        assert qd.boq.attachments[0].name == "photo1"
        assert qd.boq.attachments[0].data == b"testimage"

    def test_roundtrip_bkdn(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert len(qd.boq.bkdn) == 2

    def test_to_bytes(self):
        doc = GAEBParser.parse_string(X31_XML, filename="test.X31")
        xml_bytes, _warnings = GAEBWriter.to_bytes(
            doc, phase=ExchangePhase.X31,
        )
        assert b"QtyDeterm" in xml_bytes
        assert b"DA31" in xml_bytes

    def test_roundtrip_ctlg_assigns(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert len(qd.boq.ctlg_assigns) == 1

    def test_roundtrip_creator_profiler(self, tmp_path):
        doc2 = self._roundtrip(tmp_path)
        qd = doc2.qty_determination
        assert qd is not None
        assert qd.info.creator is not None
        assert qd.info.creator.name == "Surveyor Inc."
        assert qd.info.profiler is not None
        assert qd.info.profiler.name == "QA Corp."


# ======================================================================
# Enum tests
# ======================================================================


class TestQtyEnums:
    def test_exchange_phase_x31(self):
        assert ExchangePhase.X31.value == "X31"

    def test_is_quantity(self):
        assert ExchangePhase.X31.is_quantity
        assert not ExchangePhase.X83.is_quantity
        assert not ExchangePhase.X93.is_quantity
        assert not ExchangePhase.X50.is_quantity

    def test_document_kind_quantity(self):
        assert DocumentKind.QUANTITY.value == "quantity"

    def test_d31_normalized(self):
        assert ExchangePhase.D31.normalized() == ExchangePhase.X31


# ======================================================================
# Document discriminator tests
# ======================================================================


class TestDocumentDiscriminators:
    def test_quantity_doc(self):
        doc = GAEBDocument(qty_determination=QtyDetermination())
        assert doc.document_kind == DocumentKind.QUANTITY
        assert doc.is_quantity
        assert not doc.is_procurement
        assert not doc.is_trade
        assert not doc.is_cost

    def test_procurement_doc(self):
        doc = GAEBDocument()
        assert doc.document_kind == DocumentKind.PROCUREMENT
        assert doc.is_procurement
        assert not doc.is_quantity

    def test_memory_estimate_qty(self):
        att = QtyAttachment(name="img", file_type="png", data=b"x" * 1024)
        qd = QtyDetermination(
            boq=QtyBoQ(
                body=QtyBoQBody(
                    categories=[QtyBoQCtgy(rno="01", items=[QtyItem()])]
                ),
                attachments=[att],
            )
        )
        doc = GAEBDocument(qty_determination=qd)
        mb = doc.memory_estimate_mb
        assert mb > 0
