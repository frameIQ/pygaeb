"""Tests for GAEB trade phase parsing (X93-X97), models, and round-trip."""

from __future__ import annotations

from decimal import Decimal
from textwrap import dedent

from pygaeb import (
    DocumentKind,
    ExchangePhase,
    GAEBDocument,
    GAEBParser,
    GAEBWriter,
    SourceVersion,
)
from pygaeb.api.document_api import DocumentAPI
from pygaeb.models.order import (
    OrderItem,
    TradeOrder,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TRADE_X96_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA96/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
    <ProgSystem>TestSys</ProgSystem>
    <Date>2026-01-15</Date>
  </GAEBInfo>
  <PrjInfo>
    <NamePrj>Trade Test Project</NamePrj>
    <Cur>CHF</Cur>
  </PrjInfo>
  <Order>
    <DP>96</DP>
    <OrderInfo>
      <OrderNo>PO-2026-001</OrderNo>
      <Cur>CHF</Cur>
      <OrderDate>2026-01-15</OrderDate>
    </OrderInfo>
    <SupplierInfo>
      <Address>
        <Name>ACME Building Supplies</Name>
        <Street>Industrial Rd 42</Street>
        <PCode>8001</PCode>
        <City>Zurich</City>
        <Country>CH</Country>
        <EMail>sales@acme.ch</EMail>
      </Address>
    </SupplierInfo>
    <CustomerInfo>
      <Address>
        <Name>BuildCo AG</Name>
        <City>Bern</City>
      </Address>
    </CustomerInfo>
    <OrderItem>
      <EAN>4001234567890</EAN>
      <ArtNo>PIPE-DN100</ArtNo>
      <Qty>50</Qty>
      <QU>m</QU>
      <Description>
        <CompleteText>
          <OutlineText>
            <OutlTxt>
              <TextOutlTxt>PE Pipe DN100 SDR11</TextOutlTxt>
            </OutlTxt>
          </OutlineText>
        </CompleteText>
      </Description>
      <OfferPrice>12.50</OfferPrice>
      <NetPrice>10.80</NetPrice>
      <ModeOfShipment>truck</ModeOfShipment>
      <DeliveryDate>2026-02-01</DeliveryDate>
    </OrderItem>
    <OrderItem>
      <ArtNo>FITTING-T100</ArtNo>
      <SupplierArtNo>SP-T100-V2</SupplierArtNo>
      <Qty>20</Qty>
      <QU>pcs</QU>
      <Description>
        <CompleteText>
          <OutlineText>
            <OutlTxt>
              <TextOutlTxt>T-Fitting DN100</TextOutlTxt>
            </OutlTxt>
          </OutlineText>
        </CompleteText>
      </Description>
      <OfferPrice>45.00</OfferPrice>
      <NetPrice>38.50</NetPrice>
    </OrderItem>
    <OrderItem>
      <ArtNo>CEMENT-25KG</ArtNo>
      <Qty>100</Qty>
      <QU>bag</QU>
      <Description>
        <CompleteText>
          <OutlineText>
            <OutlTxt>
              <TextOutlTxt>Portland Cement 25kg</TextOutlTxt>
            </OutlTxt>
          </OutlineText>
        </CompleteText>
      </Description>
      <NetPrice>8.90</NetPrice>
      <Service>yes</Service>
    </OrderItem>
  </Order>
</GAEB>
""")

TRADE_X93_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA93/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
  </GAEBInfo>
  <Order>
    <DP>93</DP>
    <OrderItem>
      <ArtNo>VALVE-50</ArtNo>
      <Qty>10</Qty>
      <QU>pcs</QU>
      <Description>
        <CompleteText>
          <OutlineText>
            <OutlTxt>
              <TextOutlTxt>Ball Valve DN50</TextOutlTxt>
            </OutlTxt>
          </OutlineText>
        </CompleteText>
      </Description>
    </OrderItem>
  </Order>
</GAEB>
""")

TRADE_X94_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA94/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
  </GAEBInfo>
  <Order>
    <DP>94</DP>
    <OrderItem>
      <ArtNo>BRICK-STD</ArtNo>
      <Qty>5000</Qty>
      <QU>pcs</QU>
      <Description>
        <CompleteText>
          <OutlineText>
            <OutlTxt>
              <TextOutlTxt>Standard Brick 240x115x71</TextOutlTxt>
            </OutlTxt>
          </OutlineText>
        </CompleteText>
      </Description>
      <OfferPrice>0.45</OfferPrice>
    </OrderItem>
  </Order>
</GAEB>
""")


# ---------------------------------------------------------------------------
# Test: parsing
# ---------------------------------------------------------------------------

class TestTradeParserX96:
    def _parse(self, keep_xml: bool = False) -> GAEBDocument:
        return GAEBParser.parse_string(TRADE_X96_XML, "order.X96", keep_xml=keep_xml)

    def test_document_kind(self) -> None:
        doc = self._parse()
        assert doc.document_kind == DocumentKind.TRADE
        assert doc.is_trade is True
        assert doc.is_procurement is False

    def test_exchange_phase(self) -> None:
        doc = self._parse()
        assert doc.exchange_phase == ExchangePhase.X96

    def test_source_version(self) -> None:
        doc = self._parse()
        assert doc.source_version == SourceVersion.DA_XML_33

    def test_gaeb_info(self) -> None:
        doc = self._parse()
        assert doc.gaeb_info.version == "3.3"
        assert doc.gaeb_info.prog_system == "TestSys"

    def test_order_populated(self) -> None:
        doc = self._parse()
        assert doc.order is not None
        assert isinstance(doc.order, TradeOrder)
        assert doc.order.dp == "96"

    def test_order_info(self) -> None:
        doc = self._parse()
        oi = doc.order.order_info
        assert oi is not None
        assert oi.order_no == "PO-2026-001"
        assert oi.currency == "CHF"
        assert oi.order_date is not None
        assert oi.order_date.year == 2026

    def test_supplier_info(self) -> None:
        doc = self._parse()
        si = doc.order.supplier_info
        assert si is not None
        assert si.address.name == "ACME Building Supplies"
        assert si.address.city == "Zurich"
        assert si.address.email == "sales@acme.ch"

    def test_customer_info(self) -> None:
        doc = self._parse()
        ci = doc.order.customer_info
        assert ci is not None
        assert ci.address.name == "BuildCo AG"

    def test_item_count(self) -> None:
        doc = self._parse()
        assert doc.item_count == 3
        assert doc.order.item_count == 3

    def test_iter_items(self) -> None:
        doc = self._parse()
        items = list(doc.iter_items())
        assert len(items) == 3
        assert all(isinstance(i, OrderItem) for i in items)

    def test_first_item_fields(self) -> None:
        doc = self._parse()
        item = doc.order.items[0]
        assert item.ean == "4001234567890"
        assert item.art_no == "PIPE-DN100"
        assert item.short_text == "PE Pipe DN100 SDR11"
        assert item.qty == Decimal("50")
        assert item.unit == "m"
        assert item.offer_price == Decimal("12.50")
        assert item.net_price == Decimal("10.80")
        assert item.mode_of_shipment == "truck"
        assert item.delivery_date is not None
        assert item.delivery_date.month == 2

    def test_second_item_supplier_art_no(self) -> None:
        doc = self._parse()
        item = doc.order.items[1]
        assert item.supplier_art_no == "SP-T100-V2"

    def test_service_flag(self) -> None:
        doc = self._parse()
        item = doc.order.items[2]
        assert item.is_service is True

    def test_display_price(self) -> None:
        doc = self._parse()
        assert doc.order.items[0].display_price == Decimal("10.80")
        assert doc.order.items[2].display_price == Decimal("8.90")

    def test_grand_total(self) -> None:
        doc = self._parse()
        expected = (
            Decimal("10.80") * Decimal("50")
            + Decimal("38.50") * Decimal("20")
            + Decimal("8.90") * Decimal("100")
        )
        assert doc.grand_total == expected

    def test_keep_xml(self) -> None:
        doc = self._parse(keep_xml=True)
        assert doc.xml_root is not None
        assert doc.order.source_element is not None
        assert doc.order.items[0].source_element is not None


class TestTradeParserX93:
    def test_parse_x93(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X93_XML, "inquiry.X93")
        assert doc.document_kind == DocumentKind.TRADE
        assert doc.exchange_phase == ExchangePhase.X93
        assert doc.item_count == 1
        item = doc.order.items[0]
        assert item.art_no == "VALVE-50"
        assert item.short_text == "Ball Valve DN50"
        assert item.offer_price is None
        assert item.net_price is None


class TestTradeParserX94:
    def test_parse_x94(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X94_XML, "offer.X94")
        assert doc.document_kind == DocumentKind.TRADE
        assert doc.exchange_phase == ExchangePhase.X94
        item = doc.order.items[0]
        assert item.offer_price == Decimal("0.45")
        assert item.qty == Decimal("5000")


# ---------------------------------------------------------------------------
# Test: models
# ---------------------------------------------------------------------------

class TestOrderItemModel:
    def test_long_text_plain_empty(self) -> None:
        item = OrderItem(short_text="test")
        assert item.long_text_plain == ""

    def test_repr(self) -> None:
        item = OrderItem(art_no="ABC-123", short_text="Pipe", net_price=Decimal("42"))
        r = repr(item)
        assert "ABC-123" in r
        assert "Pipe" in r
        assert "42" in r


class TestTradeOrderModel:
    def test_empty_order(self) -> None:
        order = TradeOrder()
        assert order.item_count == 0
        assert order.grand_total == Decimal("0")
        assert list(order.iter_items()) == []

    def test_repr(self) -> None:
        order = TradeOrder(dp="96", items=[OrderItem(), OrderItem()])
        assert "dp='96'" in repr(order)
        assert "items=2" in repr(order)


# ---------------------------------------------------------------------------
# Test: enums
# ---------------------------------------------------------------------------

class TestTradeEnums:
    def test_trade_phases_exist(self) -> None:
        assert ExchangePhase.X93.value == "X93"
        assert ExchangePhase.X94.value == "X94"
        assert ExchangePhase.X96.value == "X96"
        assert ExchangePhase.X97.value == "X97"

    def test_is_trade_property(self) -> None:
        assert ExchangePhase.X93.is_trade is True
        assert ExchangePhase.X96.is_trade is True
        assert ExchangePhase.X83.is_trade is False
        assert ExchangePhase.D83.is_trade is False

    def test_document_kind_enum(self) -> None:
        assert DocumentKind.PROCUREMENT.value == "procurement"
        assert DocumentKind.TRADE.value == "trade"


# ---------------------------------------------------------------------------
# Test: GAEBDocument with trade
# ---------------------------------------------------------------------------

class TestGAEBDocumentTrade:
    def test_procurement_defaults(self) -> None:
        doc = GAEBDocument()
        assert doc.is_procurement is True
        assert doc.is_trade is False
        assert doc.document_kind == DocumentKind.PROCUREMENT

    def test_trade_document(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        assert doc.is_trade is True
        assert doc.order is not None

    def test_repr_includes_kind(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        r = repr(doc)
        assert "trade" in r
        assert "items=3" in r


# ---------------------------------------------------------------------------
# Test: DocumentAPI with trade
# ---------------------------------------------------------------------------

class TestDocumentAPITrade:
    def test_api_is_trade(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        api = DocumentAPI(doc)
        assert api.is_trade is True
        assert api.document_kind == DocumentKind.TRADE

    def test_api_iter_items(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        api = DocumentAPI(doc)
        items = list(api.iter_items())
        assert len(items) == 3

    def test_api_get_order_item(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        api = DocumentAPI(doc)
        item = api.get_order_item("PIPE-DN100")
        assert item is not None
        assert item.ean == "4001234567890"

    def test_api_filter_by_classification(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        api = DocumentAPI(doc)
        unclassified = api.filter_items(has_classification=False)
        assert len(unclassified) == 3

    def test_api_summary(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        api = DocumentAPI(doc)
        s = api.summary()
        assert s["document_kind"] == "trade"
        assert s["total_items"] == 3
        assert s["has_supplier_info"] is True

    def test_api_order_property(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        api = DocumentAPI(doc)
        assert api.order is not None
        assert api.order.dp == "96"


# ---------------------------------------------------------------------------
# Test: writer round-trip
# ---------------------------------------------------------------------------

class TestTradeWriter:
    def test_write_trade_to_bytes(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        xml_bytes, _warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X96)
        xml_str = xml_bytes.decode("utf-8")

        assert "<Order>" in xml_str
        assert "<OrderItem>" in xml_str
        assert "<ArtNo>PIPE-DN100</ArtNo>" in xml_str
        assert "<NetPrice>10.80</NetPrice>" in xml_str
        assert "DA96/3.3" in xml_str

    def test_round_trip(self) -> None:
        doc1 = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        xml_bytes, _ = GAEBWriter.to_bytes(doc1, phase=ExchangePhase.X96)
        doc2 = GAEBParser.parse_bytes(xml_bytes, "order.X96")

        assert doc2.is_trade
        assert doc2.item_count == 3
        assert doc2.order.items[0].art_no == "PIPE-DN100"
        assert doc2.order.items[0].net_price == Decimal("10.80")
        assert doc2.order.items[1].short_text == "T-Fitting DN100"


# ---------------------------------------------------------------------------
# Test: version detector for trade namespaces
# ---------------------------------------------------------------------------

class TestVersionDetectorTrade:
    def test_x93_namespace_detection(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X93_XML, "inquiry.X93")
        assert doc.exchange_phase == ExchangePhase.X93
        assert doc.source_version == SourceVersion.DA_XML_33

    def test_x96_namespace_detection(self) -> None:
        doc = GAEBParser.parse_string(TRADE_X96_XML, "order.X96")
        assert doc.exchange_phase == ExchangePhase.X96
        assert doc.source_version == SourceVersion.DA_XML_33
