"""Tests for v1.4.1 schema-review findings fixes.

Covers:
  - Shared Catalog/CtlgAssign module
  - CtlgAssign parsing/writing across procurement, cost, quantity, and trade
  - Phase-specific procurement namespace
  - MarkupItem parsing/writing (X52)
"""

from __future__ import annotations

from decimal import Decimal
from textwrap import dedent

from pygaeb import (
    ExchangePhase,
    GAEBParser,
    GAEBWriter,
    ItemType,
    SourceVersion,
)
from pygaeb.models.catalog import Catalog, CtlgAssign

# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

PROCUREMENT_WITH_CTLG = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <Award>
    <AwardInfo>
      <Prj>P1</Prj>
      <Cur>EUR</Cur>
    </AwardInfo>
    <BoQ>
      <BoQInfo>
        <Name>TestBoQ</Name>
        <BoQBkdn><BoQLevel Length="2"/></BoQBkdn>
        <CtlgAssign>
          <CtlgID>DIN276</CtlgID>
          <CtlgCode>300</CtlgCode>
        </CtlgAssign>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Section 1</LblTx>
          <CtlgAssign>
            <CtlgID>DIN276</CtlgID>
            <CtlgCode>330</CtlgCode>
          </CtlgAssign>
          <Itemlist>
            <Item RNoPart="0010">
              <Qty>100</Qty>
              <QU>m2</QU>
              <UP>45.00</UP>
              <IT>4500.00</IT>
              <CtlgAssign>
                <CtlgID>DIN276</CtlgID>
                <CtlgCode>330.1</CtlgCode>
                <Quantity>50</Quantity>
              </CtlgAssign>
            </Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
""")

COST_WITH_CTLG = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA50/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <ElementalCosting>
    <DP>50</DP>
    <ECInfo><Name>Cost Test</Name></ECInfo>
    <ECBody>
      <ECCtgy>
        <EleNo>100</EleNo>
        <Descr>Foundation</Descr>
        <CtlgAssign>
          <CtlgID>DIN276</CtlgID>
          <CtlgCode>300</CtlgCode>
        </CtlgAssign>
        <ECBody>
          <CostElement>
            <EleNo>100.1</EleNo>
            <Descr>Concrete</Descr>
            <Qty>50</Qty>
            <QU>m3</QU>
            <UP>120.00</UP>
            <IT>6000.00</IT>
            <CtlgAssign>
              <CtlgID>DIN276</CtlgID>
              <CtlgCode>331</CtlgCode>
            </CtlgAssign>
          </CostElement>
        </ECBody>
      </ECCtgy>
    </ECBody>
  </ElementalCosting>
</GAEB>
""")

MARKUP_ITEM_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <Award>
    <AwardInfo><Cur>EUR</Cur></AwardInfo>
    <BoQ>
      <BoQInfo>
        <Name>BoQ with Markup</Name>
        <BoQBkdn><BoQLevel Length="2"/></BoQBkdn>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Section</LblTx>
          <Itemlist>
            <Item RNoPart="0010">
              <Qty>10</Qty>
              <QU>Stk</QU>
              <UP>100.00</UP>
              <IT>1000.00</IT>
            </Item>
            <Item RNoPart="0020">
              <Qty>5</Qty>
              <QU>m</QU>
              <UP>50.00</UP>
              <IT>250.00</IT>
            </Item>
            <MarkupItem RNoPart="9000">
              <ShortText>Overhead</ShortText>
              <MarkupType>ListInSubQty</MarkupType>
              <Markup>10.50</Markup>
              <ITMarkup>125.00</ITMarkup>
              <DiscountPcnt>2.00</DiscountPcnt>
              <MarkupSubQty>
                <RefRNoPart>0010</RefRNoPart>
                <SubQty>10</SubQty>
              </MarkupSubQty>
              <MarkupSubQty>
                <RefRNoPart>0020</RefRNoPart>
                <SubQty>5</SubQty>
              </MarkupSubQty>
            </MarkupItem>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
""")


# ===================================================================
# Shared Catalog module
# ===================================================================


class TestSharedCatalogModule:
    def test_ctlg_assign_from_shared(self):
        ca = CtlgAssign(ctlg_id="DIN276", ctlg_code="300", quantity=Decimal("1"))
        assert ca.ctlg_id == "DIN276"
        assert ca.quantity == Decimal("1")

    def test_catalog_from_shared(self):
        cat = Catalog(ctlg_id="C1", ctlg_type="DIN276", ctlg_name="Cost groups")
        assert cat.ctlg_type == "DIN276"

    def test_imports_from_top_level(self):
        from pygaeb import Catalog as TopCat
        from pygaeb import CtlgAssign as TopCA
        assert TopCat is Catalog
        assert TopCA is CtlgAssign

    def test_quantity_reexports(self):
        from pygaeb.models.quantity import Catalog as QtyCat
        from pygaeb.models.quantity import CtlgAssign as QtyCA
        assert QtyCat is Catalog
        assert QtyCA is CtlgAssign


# ===================================================================
# CtlgAssign parsing — procurement
# ===================================================================


class TestCtlgAssignProcurement:
    def test_parse_ctlg_on_boq_info(self, tmp_path):
        f = tmp_path / "ctlg.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        info = doc.award.boq.boq_info
        assert info is not None
        assert len(info.ctlg_assigns) == 1
        assert info.ctlg_assigns[0].ctlg_id == "DIN276"
        assert info.ctlg_assigns[0].ctlg_code == "300"

    def test_parse_ctlg_on_boq_ctgy(self, tmp_path):
        f = tmp_path / "ctlg.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        ctgy = doc.award.boq.lots[0].body.categories[0]
        assert len(ctgy.ctlg_assigns) == 1
        assert ctgy.ctlg_assigns[0].ctlg_code == "330"

    def test_parse_ctlg_on_item(self, tmp_path):
        f = tmp_path / "ctlg.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        items = list(doc.award.boq.iter_items())
        assert len(items) == 1
        item = items[0]
        assert len(item.ctlg_assigns) == 1
        assert item.ctlg_assigns[0].ctlg_code == "330.1"
        assert item.ctlg_assigns[0].quantity == Decimal("50")

    def test_roundtrip_ctlg_procurement(self, tmp_path):
        f = tmp_path / "ctlg.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)

        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        assert b"<CtlgAssign>" in xml_bytes
        assert b"<CtlgID>DIN276</CtlgID>" in xml_bytes
        assert b"<CtlgCode>330.1</CtlgCode>" in xml_bytes

        out = tmp_path / "out.X86"
        out.write_bytes(xml_bytes)
        doc2 = GAEBParser.parse(out)
        item2 = next(iter(doc2.award.boq.iter_items()))
        assert item2.ctlg_assigns[0].ctlg_code == "330.1"


# ===================================================================
# CtlgAssign parsing — cost
# ===================================================================


class TestCtlgAssignCost:
    def test_parse_ctlg_on_ec_ctgy(self, tmp_path):
        f = tmp_path / "cost.X50"
        f.write_text(COST_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        ec = doc.elemental_costing
        assert ec is not None
        ctgy = ec.body.categories[0]
        assert len(ctgy.ctlg_assigns) == 1
        assert ctgy.ctlg_assigns[0].ctlg_code == "300"

    def test_parse_ctlg_on_cost_element(self, tmp_path):
        f = tmp_path / "cost.X50"
        f.write_text(COST_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        ec = doc.elemental_costing
        assert ec is not None
        ce = next(iter(ec.iter_items()))
        assert len(ce.ctlg_assigns) == 1
        assert ce.ctlg_assigns[0].ctlg_code == "331"


# ===================================================================
# Phase-specific procurement namespace
# ===================================================================


class TestProcurementNamespace:
    def test_x83_namespace(self, tmp_path):
        f = tmp_path / "test.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        xml_bytes, _ = GAEBWriter.to_bytes(
            doc, phase=ExchangePhase.X83,
        )
        assert b"DA83/3.3" in xml_bytes

    def test_x84_namespace(self, tmp_path):
        f = tmp_path / "test.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        xml_bytes, _ = GAEBWriter.to_bytes(
            doc, phase=ExchangePhase.X84,
        )
        assert b"DA84/3.3" in xml_bytes

    def test_x86_namespace(self, tmp_path):
        f = tmp_path / "test.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        assert b"DA86/3.3" in xml_bytes

    def test_v30_ignores_phase(self, tmp_path):
        f = tmp_path / "test.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        xml_bytes, _ = GAEBWriter.to_bytes(
            doc,
            phase=ExchangePhase.X83,
            target_version=SourceVersion.DA_XML_30,
        )
        assert b"200407" in xml_bytes

    def test_v32_phase_specific(self, tmp_path):
        f = tmp_path / "test.X86"
        f.write_text(PROCUREMENT_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        xml_bytes, _ = GAEBWriter.to_bytes(
            doc,
            phase=ExchangePhase.X84,
            target_version=SourceVersion.DA_XML_32,
        )
        assert b"DA84/3.2" in xml_bytes


# ===================================================================
# MarkupItem parsing and writing
# ===================================================================


class TestMarkupItem:
    def test_parse_markup_item(self, tmp_path):
        f = tmp_path / "markup.X86"
        f.write_text(MARKUP_ITEM_XML, encoding="utf-8")
        doc = GAEBParser.parse(f)
        items = list(doc.award.boq.iter_items())
        assert len(items) == 3

        normal_items = [i for i in items if i.item_type != ItemType.MARKUP]
        markup_items = [i for i in items if i.item_type == ItemType.MARKUP]
        assert len(normal_items) == 2
        assert len(markup_items) == 1

        mu = markup_items[0]
        assert mu.oz == "9000"
        assert mu.short_text == "Overhead"
        assert mu.markup_type == "ListInSubQty"
        assert mu.unit_price == Decimal("10.50")
        assert mu.total_price == Decimal("125.00")
        assert mu.discount_pct == Decimal("2.00")

    def test_parse_markup_sub_qtys(self, tmp_path):
        f = tmp_path / "markup.X86"
        f.write_text(MARKUP_ITEM_XML, encoding="utf-8")
        doc = GAEBParser.parse(f)
        items = list(doc.award.boq.iter_items())
        mu = next(i for i in items if i.item_type == ItemType.MARKUP)

        assert len(mu.markup_sub_qtys) == 2
        assert mu.markup_sub_qtys[0].ref_rno == "0010"
        assert mu.markup_sub_qtys[0].sub_qty == Decimal("10")
        assert mu.markup_sub_qtys[1].ref_rno == "0020"
        assert mu.markup_sub_qtys[1].sub_qty == Decimal("5")

    def test_markup_roundtrip(self, tmp_path):
        f = tmp_path / "markup.X86"
        f.write_text(MARKUP_ITEM_XML, encoding="utf-8")
        doc = GAEBParser.parse(f)

        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        assert b"<MarkupItem" in xml_bytes
        assert b"<MarkupType>ListInSubQty</MarkupType>" in xml_bytes
        assert b"<ITMarkup>" in xml_bytes
        assert b"<RefRNoPart>0010</RefRNoPart>" in xml_bytes

        out = tmp_path / "out.X86"
        out.write_bytes(xml_bytes)
        doc2 = GAEBParser.parse(out)
        items2 = list(doc2.award.boq.iter_items())
        mu2 = next(i for i in items2 if i.item_type == ItemType.MARKUP)
        assert mu2.markup_type == "ListInSubQty"
        assert len(mu2.markup_sub_qtys) == 2
        assert mu2.total_price == Decimal("125.00")

    def test_markup_item_type_flag(self, tmp_path):
        f = tmp_path / "markup.X86"
        f.write_text(MARKUP_ITEM_XML, encoding="utf-8")
        doc = GAEBParser.parse(f)
        items = list(doc.award.boq.iter_items())
        mu = next(i for i in items if i.item_type == ItemType.MARKUP)
        assert mu.item_type == ItemType.MARKUP
        assert mu.item_type.affects_total is False


# ===================================================================
# MarkupSubQty model
# ===================================================================


class TestMarkupSubQtyModel:
    def test_defaults(self):
        from pygaeb.models.item import MarkupSubQty
        m = MarkupSubQty()
        assert m.ref_rno == ""
        assert m.sub_qty is None

    def test_with_values(self):
        from pygaeb.models.item import MarkupSubQty
        m = MarkupSubQty(ref_rno="0010", sub_qty=Decimal("42"))
        assert m.ref_rno == "0010"
        assert m.sub_qty == Decimal("42")


# ===================================================================
# Regression: existing tests still pass with new fields
# ===================================================================


class TestNoRegressionOnNewFields:
    def test_item_ctlg_assigns_default_empty(self):
        from pygaeb.models.item import Item
        item = Item()
        assert item.ctlg_assigns == []
        assert item.markup_type is None
        assert item.markup_sub_qtys == []

    def test_boq_ctgy_ctlg_assigns_default_empty(self):
        from pygaeb.models.boq import BoQCtgy
        ctgy = BoQCtgy()
        assert ctgy.ctlg_assigns == []

    def test_boq_info_ctlg_assigns_default_empty(self):
        from pygaeb.models.boq import BoQInfo
        info = BoQInfo()
        assert info.ctlg_assigns == []

    def test_cost_element_ctlg_assigns_default_empty(self):
        from pygaeb.models.cost import CostElement
        ce = CostElement()
        assert ce.ctlg_assigns == []

    def test_ec_ctgy_ctlg_assigns_default_empty(self):
        from pygaeb.models.cost import ECCtgy
        ctgy = ECCtgy()
        assert ctgy.ctlg_assigns == []

    def test_order_item_ctlg_assigns_default_empty(self):
        from pygaeb.models.order import OrderItem
        oi = OrderItem()
        assert oi.ctlg_assigns == []

    def test_trade_order_ctlg_assigns_default_empty(self):
        from pygaeb.models.order import TradeOrder
        to = TradeOrder()
        assert to.ctlg_assigns == []

    def test_order_info_ctlg_assigns_default_empty(self):
        from pygaeb.models.order import OrderInfo
        oi = OrderInfo()
        assert oi.ctlg_assigns == []


# ===================================================================
# CtlgAssign parsing — trade
# ===================================================================

TRADE_WITH_CTLG = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA93/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <Order>
    <DP>93</DP>
    <OrderInfo>
      <OrderNo>ORD-001</OrderNo>
      <Cur>EUR</Cur>
      <CtlgAssign>
        <CtlgID>BIM</CtlgID>
        <CtlgCode>PRJ-BIM-001</CtlgCode>
      </CtlgAssign>
    </OrderInfo>
    <SupplierInfo>
      <Address><Name>Supplier GmbH</Name></Address>
    </SupplierInfo>
    <OrderItem>
      <ArtNo>MAT-100</ArtNo>
      <Qty>50</Qty>
      <QU>Stk</QU>
      <NetPrice>25.00</NetPrice>
      <CtlgAssign>
        <CtlgID>BIM</CtlgID>
        <CtlgCode>ELEM-A1</CtlgCode>
      </CtlgAssign>
      <CtlgAssign>
        <CtlgID>DIN276</CtlgID>
        <CtlgCode>330</CtlgCode>
      </CtlgAssign>
    </OrderItem>
    <OrderItem>
      <ArtNo>MAT-200</ArtNo>
      <Qty>10</Qty>
      <QU>m</QU>
      <NetPrice>12.50</NetPrice>
    </OrderItem>
    <CtlgAssign>
      <CtlgID>DIN276</CtlgID>
      <CtlgCode>300</CtlgCode>
    </CtlgAssign>
  </Order>
</GAEB>
""")


class TestCtlgAssignTrade:
    def test_parse_ctlg_on_order(self, tmp_path):
        f = tmp_path / "trade.X93"
        f.write_text(TRADE_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        assert doc.order is not None
        assert len(doc.order.ctlg_assigns) == 1
        assert doc.order.ctlg_assigns[0].ctlg_id == "DIN276"
        assert doc.order.ctlg_assigns[0].ctlg_code == "300"

    def test_parse_ctlg_on_order_info(self, tmp_path):
        f = tmp_path / "trade.X93"
        f.write_text(TRADE_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        assert doc.order is not None
        assert doc.order.order_info is not None
        assert len(doc.order.order_info.ctlg_assigns) == 1
        assert doc.order.order_info.ctlg_assigns[0].ctlg_id == "BIM"

    def test_parse_ctlg_on_order_item(self, tmp_path):
        f = tmp_path / "trade.X93"
        f.write_text(TRADE_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)
        assert doc.order is not None
        items = list(doc.order.iter_items())
        assert len(items) == 2
        assert len(items[0].ctlg_assigns) == 2
        assert items[0].ctlg_assigns[0].ctlg_id == "BIM"
        assert items[0].ctlg_assigns[0].ctlg_code == "ELEM-A1"
        assert items[0].ctlg_assigns[1].ctlg_id == "DIN276"
        assert len(items[1].ctlg_assigns) == 0

    def test_roundtrip_ctlg_trade(self, tmp_path):
        f = tmp_path / "trade.X93"
        f.write_text(TRADE_WITH_CTLG, encoding="utf-8")
        doc = GAEBParser.parse(f)

        xml_bytes, _ = GAEBWriter.to_bytes(
            doc, phase=ExchangePhase.X93,
        )
        assert b"<CtlgAssign>" in xml_bytes
        assert b"<CtlgID>BIM</CtlgID>" in xml_bytes
        assert b"<CtlgCode>ELEM-A1</CtlgCode>" in xml_bytes
        assert b"<CtlgCode>300</CtlgCode>" in xml_bytes

        out = tmp_path / "out.X93"
        out.write_bytes(xml_bytes)
        doc2 = GAEBParser.parse(out)
        assert doc2.order is not None

        assert len(doc2.order.ctlg_assigns) == 1
        assert doc2.order.ctlg_assigns[0].ctlg_code == "300"

        assert doc2.order.order_info is not None
        assert len(doc2.order.order_info.ctlg_assigns) == 1
        assert doc2.order.order_info.ctlg_assigns[0].ctlg_id == "BIM"

        items2 = list(doc2.order.iter_items())
        assert len(items2[0].ctlg_assigns) == 2
        assert items2[0].ctlg_assigns[0].ctlg_code == "ELEM-A1"
