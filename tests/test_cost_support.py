"""Tests for GAEB cost & calculation phase support (X50, X51, X52)."""

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
from pygaeb.models.boq import CostType
from pygaeb.models.cost import (
    BoQItemRef,
    CategoryElement,
    CostElement,
    CostProperty,
    DimensionElement,
    ECBody,
    ECCtgy,
    ECInfo,
    ElementalCosting,
    RefGroup,
)
from pygaeb.models.item import CostApproach, Item


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

X50_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA50/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
    <ProgSystem>TestSys</ProgSystem>
    <Date>2026-03-01</Date>
  </GAEBInfo>
  <ElementalCosting>
    <DP>50.1</DP>
    <ECInfo>
      <Name>Project Alpha Cost Plan</Name>
      <LblEC>Alpha EC</LblEC>
      <ECType>cost estimate</ECType>
      <ECMethod>cost by elements</ECMethod>
      <Date>2026-03-01</Date>
      <Cur>EUR</Cur>
      <CurLbl>Euro</CurLbl>
      <DateOfPrice>2026-01-01</DateOfPrice>
      <ECBkdn>
        <Type>Level1</Type>
        <LblOutline>Main Group</LblOutline>
        <Length>3</Length>
        <Num>Yes</Num>
      </ECBkdn>
      <ECBkdn>
        <Type>Level2</Type>
        <LblOutline>Sub Group</LblOutline>
        <Length>2</Length>
      </ECBkdn>
      <ConsortiumMember>
        <Description>Lead Partner</Description>
        <Address>
          <Name>Bauplan GmbH</Name>
          <Street>Architektenweg 5</Street>
          <PCode>10115</PCode>
          <City>Berlin</City>
          <Country>DE</Country>
        </Address>
      </ConsortiumMember>
      <Totals>
        <TotalNet>250000.00</TotalNet>
        <TotalGross>297500.00</TotalGross>
      </Totals>
    </ECInfo>
    <ECBody>
      <ECCtgy>
        <EleNo>300</EleNo>
        <Descr>Building construction costs</Descr>
        <Portion>0.70</Portion>
        <Totals>
          <TotalNet>175000.00</TotalNet>
        </Totals>
        <ECBody>
          <CostElement>
            <EleNo>310</EleNo>
            <Descr>Foundation work</Descr>
            <CatID>CAT-001</CatID>
            <Qty>150.00</Qty>
            <QU>m3</QU>
            <UP>120.00</UP>
            <IT>18000.00</IT>
            <Markup>1.05</Markup>
            <BillElement>Yes</BillElement>
            <Property>
              <Name>Floor Area</Name>
              <LblProp>GF</LblProp>
              <ArithmeticQuantityApproach>L * B * H</ArithmeticQuantityApproach>
              <ValueQuantityApproach>150.00</ValueQuantityApproach>
              <QU>m3</QU>
              <Type>manual value</Type>
              <CAD_ID>abc-123-def</CAD_ID>
            </Property>
            <RefGroup>
              <Title>BoQ References</Title>
              <BoQItemRef IDRef="item-001" Type="direct">
                <Portion>1.0</Portion>
              </BoQItemRef>
            </RefGroup>
            <CostElement>
              <EleNo>310.1</EleNo>
              <Descr>Concrete pouring</Descr>
              <Qty>100.00</Qty>
              <QU>m3</QU>
              <UP>80.00</UP>
              <IT>8000.00</IT>
              <UPFrom>70.00</UPFrom>
              <UPAvg>80.00</UPAvg>
              <UPTo>95.00</UPTo>
            </CostElement>
          </CostElement>
          <CostElement>
            <EleNo>320</EleNo>
            <Descr>Wall construction</Descr>
            <Qty>200.00</Qty>
            <QU>m2</QU>
            <UP>85.00</UP>
            <IT>17000.00</IT>
          </CostElement>
          <DimensionElement>
            <EleNo>DIM-001</EleNo>
            <Descr>Ground floor area</Descr>
            <Qty>500.00</Qty>
            <QU>m2</QU>
            <Markup>1.00</Markup>
          </DimensionElement>
          <CategoryElement>
            <EleNo>CAT-STRUCT</EleNo>
            <Descr>Structural Works</Descr>
            <CatID>cat-struct</CatID>
            <Markup>1.10</Markup>
          </CategoryElement>
        </ECBody>
      </ECCtgy>
      <ECCtgy>
        <EleNo>400</EleNo>
        <Descr>Technical installations</Descr>
        <Portion>0.30</Portion>
        <ECBody>
          <CostElement>
            <EleNo>410</EleNo>
            <Descr>HVAC system</Descr>
            <Qty>1.00</Qty>
            <QU>LS</QU>
            <UP>75000.00</UP>
            <IT>75000.00</IT>
          </CostElement>
        </ECBody>
      </ECCtgy>
    </ECBody>
  </ElementalCosting>
</GAEB>
""")

X52_XML = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA52/3.3">
  <GAEBInfo>
    <Version>3.3</Version>
    <ProgSystem>TestSys</ProgSystem>
    <Date>2026-03-01</Date>
  </GAEBInfo>
  <Award>
    <AwardInfo>
      <Prj>P-2026-052</Prj>
      <PrjName>Calculation Approaches Test</PrjName>
      <Cur>EUR</Cur>
    </AwardInfo>
    <BoQ>
      <BoQInfo>
        <Name>Main BoQ</Name>
        <CostType>
          <Name>Material</Name>
          <Label>Mat.</Label>
        </CostType>
        <CostType>
          <Name>Labor</Name>
          <Label>Lab.</Label>
        </CostType>
      </BoQInfo>
      <BoQBody>
        <BoQCtgy RNoPart="01">
          <LblTx>Section A</LblTx>
          <Itemlist>
            <Item RNoPart="01.01">
              <ShortText>Concrete C25/30</ShortText>
              <Qty>50.00</Qty>
              <QU>m3</QU>
              <UP>120.00</UP>
              <IT>6000.00</IT>
              <UPComp1>45.00</UPComp1>
              <UPComp2>30.00</UPComp2>
              <UPComp3>25.00</UPComp3>
              <UPComp4>10.00</UPComp4>
              <UPComp5>5.00</UPComp5>
              <UPComp6>5.00</UPComp6>
              <DiscountPcnt>2.5</DiscountPcnt>
              <CostApproach>
                <CostType>Material</CostType>
                <Amount>75.00</Amount>
                <Remark>Concrete mix</Remark>
              </CostApproach>
              <CostApproach>
                <CostType>Labor</CostType>
                <Amount>45.00</Amount>
              </CostApproach>
            </Item>
            <Item RNoPart="01.02">
              <ShortText>Reinforcement steel</ShortText>
              <Qty>2000.00</Qty>
              <QU>kg</QU>
              <UP>1.50</UP>
              <IT>3000.00</IT>
              <UPComp1>1.00</UPComp1>
              <UPComp2>0.50</UPComp2>
            </Item>
          </Itemlist>
        </BoQCtgy>
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>
""")


# ===========================================================================
# X50/X51 Elemental Costing Tests
# ===========================================================================


class TestCostModels:
    """Test cost model construction and properties."""

    def test_cost_element_basic(self) -> None:
        ce = CostElement(
            ele_no="310",
            short_text="Foundation work",
            qty=Decimal("150"),
            unit="m3",
            unit_price=Decimal("120"),
            item_total=Decimal("18000"),
        )
        assert ce.ele_no == "310"
        assert ce.short_text == "Foundation work"
        assert ce.display_price == Decimal("18000")
        assert ce.long_text_plain == ""

    def test_cost_element_computed_display_price(self) -> None:
        ce = CostElement(
            qty=Decimal("10"),
            unit_price=Decimal("5"),
        )
        assert ce.display_price == Decimal("50")

    def test_cost_element_recursive_children(self) -> None:
        child = CostElement(ele_no="310.1", item_total=Decimal("100"))
        parent = CostElement(ele_no="310", item_total=Decimal("500"), children=[child])
        flat = list(parent.iter_cost_elements())
        assert len(flat) == 2
        assert flat[0].ele_no == "310"
        assert flat[1].ele_no == "310.1"

    def test_cost_element_repr(self) -> None:
        ce = CostElement(ele_no="310", short_text="Test", item_total=Decimal("100"))
        assert "310" in repr(ce)
        assert "Test" in repr(ce)
        assert "100" in repr(ce)

    def test_ec_body_iteration(self) -> None:
        body = ECBody(
            cost_elements=[
                CostElement(ele_no="A", children=[CostElement(ele_no="A.1")]),
                CostElement(ele_no="B"),
            ],
            categories=[
                ECCtgy(
                    ele_no="300",
                    body=ECBody(cost_elements=[CostElement(ele_no="C")]),
                ),
            ],
        )
        elements = list(body.iter_cost_elements())
        ele_nos = [e.ele_no for e in elements]
        assert ele_nos == ["A", "A.1", "B", "C"]

    def test_elemental_costing_iter_items(self) -> None:
        ec = ElementalCosting(
            dp="50.1",
            body=ECBody(
                cost_elements=[CostElement(ele_no="100")],
                categories=[
                    ECCtgy(
                        ele_no="200",
                        body=ECBody(cost_elements=[CostElement(ele_no="200.1")]),
                    )
                ],
            ),
        )
        items = list(ec.iter_items())
        assert len(items) == 2
        assert ec.item_count == 2

    def test_elemental_costing_grand_total(self) -> None:
        ec = ElementalCosting(
            body=ECBody(
                cost_elements=[
                    CostElement(item_total=Decimal("1000")),
                    CostElement(
                        is_bill_element=True,
                        qty=Decimal("10"),
                        unit_price=Decimal("50"),
                    ),
                ],
            ),
        )
        assert ec.grand_total == Decimal("1500")

    def test_elemental_costing_hierarchy(self) -> None:
        ec = ElementalCosting(
            body=ECBody(
                categories=[
                    ECCtgy(
                        ele_no="300",
                        description="Building",
                        body=ECBody(
                            categories=[
                                ECCtgy(ele_no="310", description="Foundation"),
                            ],
                        ),
                    ),
                ],
            ),
        )
        hierarchy = list(ec.iter_hierarchy())
        assert len(hierarchy) == 2
        assert hierarchy[0] == (0, "Building", ec.body.categories[0])
        assert hierarchy[1][0] == 1
        assert hierarchy[1][1] == "Foundation"

    def test_cost_property_bim(self) -> None:
        prop = CostProperty(
            name="Floor Area",
            cad_id="abc-123",
            arithmetic_qty_approach="L * B",
            value_qty_approach=Decimal("150"),
        )
        assert prop.cad_id == "abc-123"
        assert prop.arithmetic_qty_approach == "L * B"

    def test_ref_group(self) -> None:
        rg = RefGroup(
            title="BoQ Refs",
            boq_item_refs=[BoQItemRef(id_ref="item-1", portion=Decimal("1"))],
        )
        assert len(rg.boq_item_refs) == 1
        assert rg.boq_item_refs[0].id_ref == "item-1"


class TestCostParser:
    """Test parsing of X50/X51 cost documents."""

    def test_parse_x50_basic(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        assert doc.source_version == SourceVersion.DA_XML_33
        assert doc.exchange_phase == ExchangePhase.X50
        assert doc.document_kind == DocumentKind.COST
        assert doc.is_cost is True
        assert doc.is_procurement is False
        assert doc.is_trade is False

    def test_parse_x50_elemental_costing(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        assert ec.dp == "50.1"

    def test_parse_x50_ec_info(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        info = ec.ec_info
        assert info.name == "Project Alpha Cost Plan"
        assert info.label == "Alpha EC"
        assert info.ec_type == "cost estimate"
        assert info.ec_method == "cost by elements"
        assert info.currency == "EUR"
        assert info.currency_label == "Euro"
        assert info.date is not None
        assert info.date_of_price is not None
        assert info.totals_net == Decimal("250000.00")
        assert info.totals_gross == Decimal("297500.00")

    def test_parse_x50_breakdowns(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        bkdns = ec.ec_info.breakdowns
        assert len(bkdns) == 2
        assert bkdns[0].bkdn_type == "Level1"
        assert bkdns[0].label == "Main Group"
        assert bkdns[0].length == 3
        assert bkdns[0].is_numeric is True
        assert bkdns[1].is_numeric is False

    def test_parse_x50_consortium_members(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        members = ec.ec_info.consortium_members
        assert len(members) == 1
        assert members[0].description == "Lead Partner"
        assert members[0].name == "Bauplan GmbH"
        assert members[0].city == "Berlin"

    def test_parse_x50_categories(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        cats = ec.body.categories
        assert len(cats) == 2
        assert cats[0].ele_no == "300"
        assert cats[0].description == "Building construction costs"
        assert cats[0].portion == Decimal("0.70")
        assert cats[0].totals_net == Decimal("175000.00")

    def test_parse_x50_cost_elements(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        cat300 = ec.body.categories[0]
        assert cat300.body is not None
        elements = cat300.body.cost_elements
        assert len(elements) == 2
        ce310 = elements[0]
        assert ce310.ele_no == "310"
        assert ce310.short_text == "Foundation work"
        assert ce310.cat_id == "CAT-001"
        assert ce310.qty == Decimal("150.00")
        assert ce310.unit == "m3"
        assert ce310.unit_price == Decimal("120.00")
        assert ce310.item_total == Decimal("18000.00")
        assert ce310.markup == Decimal("1.05")
        assert ce310.is_bill_element is True

    def test_parse_x50_nested_cost_elements(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        ce310 = ec.body.categories[0].body.cost_elements[0]  # type: ignore[union-attr]
        assert len(ce310.children) == 1
        child = ce310.children[0]
        assert child.ele_no == "310.1"
        assert child.short_text == "Concrete pouring"
        assert child.up_from == Decimal("70.00")
        assert child.up_avg == Decimal("80.00")
        assert child.up_to == Decimal("95.00")

    def test_parse_x50_properties(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        ce310 = ec.body.categories[0].body.cost_elements[0]  # type: ignore[union-attr]
        assert len(ce310.properties) == 1
        prop = ce310.properties[0]
        assert prop.name == "Floor Area"
        assert prop.label == "GF"
        assert prop.arithmetic_qty_approach == "L * B * H"
        assert prop.value_qty_approach == Decimal("150.00")
        assert prop.unit == "m3"
        assert prop.prop_type == "manual value"
        assert prop.cad_id == "abc-123-def"

    def test_parse_x50_ref_groups(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        ce310 = ec.body.categories[0].body.cost_elements[0]  # type: ignore[union-attr]
        assert len(ce310.ref_groups) == 1
        rg = ce310.ref_groups[0]
        assert rg.title == "BoQ References"
        assert len(rg.boq_item_refs) == 1
        assert rg.boq_item_refs[0].id_ref == "item-001"
        assert rg.boq_item_refs[0].ref_type == "direct"
        assert rg.boq_item_refs[0].portion == Decimal("1.0")

    def test_parse_x50_dimension_element(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        body = ec.body.categories[0].body
        assert body is not None
        assert len(body.dimension_elements) == 1
        de = body.dimension_elements[0]
        assert de.ele_no == "DIM-001"
        assert de.description == "Ground floor area"
        assert de.qty == Decimal("500.00")
        assert de.unit == "m2"

    def test_parse_x50_category_element(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        ec = doc.elemental_costing
        assert ec is not None
        body = ec.body.categories[0].body
        assert body is not None
        assert len(body.category_elements) == 1
        cat = body.category_elements[0]
        assert cat.ele_no == "CAT-STRUCT"
        assert cat.description == "Structural Works"
        assert cat.markup == Decimal("1.10")

    def test_x50_iter_items_universal(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        items = list(doc.iter_items())
        assert len(items) == 4
        assert all(isinstance(i, CostElement) for i in items)

    def test_x50_item_count(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        assert doc.item_count == 4

    def test_x50_grand_total(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        total = doc.grand_total
        assert total > Decimal("0")

    def test_x50_memory_estimate(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        assert doc.memory_estimate_mb > 0

    def test_x50_keep_xml(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50", keep_xml=True)
        assert doc.xml_root is not None
        ec = doc.elemental_costing
        assert ec is not None
        assert ec.source_element is not None
        for ce in ec.iter_items():
            assert ce.source_element is not None

    def test_x50_repr(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        r = repr(doc)
        assert "cost" in r
        assert "X50" in r


class TestCostDocumentAPI:
    """Test DocumentAPI with cost documents."""

    def test_api_is_cost(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        assert api.is_cost is True
        assert api.is_procurement is False
        assert api.is_trade is False
        assert api.document_kind == DocumentKind.COST

    def test_api_elemental_costing(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        assert api.elemental_costing is not None
        assert api.elemental_costing.dp == "50.1"

    def test_api_iter_items(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        items = list(api.iter_items())
        assert len(items) == 4

    def test_api_get_cost_element(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        ce = api.get_cost_element("310")
        assert ce is not None
        assert ce.short_text == "Foundation work"
        assert api.get_cost_element("nonexistent") is None

    def test_api_iter_hierarchy(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        hierarchy = list(api.iter_hierarchy())
        assert len(hierarchy) >= 2

    def test_api_filter_min_total(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        expensive = api.filter_items(min_total=Decimal("10000"))
        assert all(
            isinstance(i, CostElement)
            and i.display_price is not None
            and i.display_price >= Decimal("10000")
            for i in expensive
        )

    def test_api_summary(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        api = DocumentAPI(doc)
        s = api.summary()
        assert s["document_kind"] == "cost"
        assert s["total_items"] == 4
        assert s["ec_type"] == "cost estimate"
        assert s["ec_method"] == "cost by elements"
        assert "has_bim_references" in s

    def test_api_custom_tag_cost(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50", keep_xml=True)
        api = DocumentAPI(doc)
        for ce in api.iter_items():
            api.custom_tag(ce, "NonExistent")


class TestCostWriter:
    """Test writing cost documents."""

    def test_write_x50_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _warnings = GAEBWriter.to_bytes(
            doc,
            phase=ExchangePhase.X50,
            target_version=SourceVersion.DA_XML_33,
        )
        xml_str = xml_bytes.decode("utf-8")
        assert "ElementalCosting" in xml_str
        assert "ECInfo" in xml_str
        assert "ECBody" in xml_str
        assert "ECCtgy" in xml_str
        assert "CostElement" in xml_str

    def test_write_x50_cost_element_fields(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X50)
        xml_str = xml_bytes.decode("utf-8")
        assert "<EleNo>310</EleNo>" in xml_str
        assert "<Descr>Foundation work</Descr>" in xml_str
        assert "<UP>120.00</UP>" in xml_str
        assert "<IT>18000.00</IT>" in xml_str
        assert "<Markup>1.05</Markup>" in xml_str
        assert "<BillElement>Yes</BillElement>" in xml_str

    def test_write_x50_property(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X50)
        xml_str = xml_bytes.decode("utf-8")
        assert "<Property>" in xml_str
        assert "ArithmeticQuantityApproach" in xml_str
        assert "<CAD_ID>abc-123-def</CAD_ID>" in xml_str

    def test_write_x50_ref_group(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X50)
        xml_str = xml_bytes.decode("utf-8")
        assert "<RefGroup>" in xml_str
        assert 'IDRef="item-001"' in xml_str

    def test_write_x50_dimension_element(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X50)
        xml_str = xml_bytes.decode("utf-8")
        assert "<DimensionElement>" in xml_str
        assert "<EleNo>DIM-001</EleNo>" in xml_str

    def test_write_x50_category_element(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X50)
        xml_str = xml_bytes.decode("utf-8")
        assert "<CategoryElement>" in xml_str
        assert "<EleNo>CAT-STRUCT</EleNo>" in xml_str

    def test_write_x50_ec_info(self) -> None:
        doc = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X50)
        xml_str = xml_bytes.decode("utf-8")
        assert "<ECType>cost estimate</ECType>" in xml_str
        assert "<ECMethod>cost by elements</ECMethod>" in xml_str
        assert "<ECBkdn>" in xml_str
        assert "<ConsortiumMember>" in xml_str
        assert "<TotalNet>250000.00</TotalNet>" in xml_str

    def test_write_x50_reparse(self) -> None:
        doc1 = GAEBParser.parse_string(X50_XML, filename="test.X50")
        xml_bytes, _ = GAEBWriter.to_bytes(doc1, phase=ExchangePhase.X50)
        doc2 = GAEBParser.parse_string(
            xml_bytes.decode("utf-8"), filename="round.X50",
        )
        assert doc2.is_cost
        assert doc2.elemental_costing is not None
        assert doc2.item_count == doc1.item_count


# ===========================================================================
# X52 Calculation Approaches Tests
# ===========================================================================


class TestX52Models:
    """Test X52 cost approach models."""

    def test_cost_approach_model(self) -> None:
        ca = CostApproach(
            cost_type="Material",
            amount=Decimal("75.00"),
            remark="Concrete mix",
        )
        assert ca.cost_type == "Material"
        assert ca.amount == Decimal("75.00")
        assert ca.remark == "Concrete mix"

    def test_cost_type_model(self) -> None:
        ct = CostType(name="Material", label="Mat.")
        assert ct.name == "Material"
        assert ct.label == "Mat."

    def test_item_cost_approaches(self) -> None:
        item = Item(
            oz="01.01",
            cost_approaches=[
                CostApproach(cost_type="Material", amount=Decimal("50")),
                CostApproach(cost_type="Labor", amount=Decimal("30")),
            ],
            up_components=[Decimal("40"), Decimal("30"), Decimal("20")],
            discount_pct=Decimal("5.0"),
        )
        assert len(item.cost_approaches) == 2
        assert len(item.up_components) == 3
        assert item.discount_pct == Decimal("5.0")


class TestX52Parser:
    """Test parsing X52 documents."""

    def test_parse_x52_basic(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        assert doc.source_version == SourceVersion.DA_XML_33
        assert doc.exchange_phase == ExchangePhase.X52
        assert doc.document_kind == DocumentKind.PROCUREMENT
        assert doc.is_procurement is True

    def test_parse_x52_cost_types(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        info = doc.award.boq.boq_info
        assert info is not None
        assert len(info.cost_types) == 2
        assert info.cost_types[0].name == "Material"
        assert info.cost_types[0].label == "Mat."
        assert info.cost_types[1].name == "Labor"

    def test_parse_x52_cost_approaches(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        items = list(doc.iter_items())
        assert len(items) == 2

        item1 = items[0]
        assert isinstance(item1, Item)
        assert len(item1.cost_approaches) == 2
        assert item1.cost_approaches[0].cost_type == "Material"
        assert item1.cost_approaches[0].amount == Decimal("75.00")
        assert item1.cost_approaches[0].remark == "Concrete mix"
        assert item1.cost_approaches[1].cost_type == "Labor"
        assert item1.cost_approaches[1].amount == Decimal("45.00")

    def test_parse_x52_up_components(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        items = list(doc.iter_items())
        item1 = items[0]
        assert isinstance(item1, Item)
        assert len(item1.up_components) == 6
        assert item1.up_components[0] == Decimal("45.00")
        assert item1.up_components[5] == Decimal("5.00")

        item2 = items[1]
        assert isinstance(item2, Item)
        assert len(item2.up_components) == 2
        assert item2.up_components[0] == Decimal("1.00")

    def test_parse_x52_discount(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        items = list(doc.iter_items())
        item1 = items[0]
        assert isinstance(item1, Item)
        assert item1.discount_pct == Decimal("2.5")

        item2 = items[1]
        assert isinstance(item2, Item)
        assert item2.discount_pct is None


class TestX52Writer:
    """Test writing X52 documents."""

    def test_write_x52_cost_approaches(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X52)
        xml_str = xml_bytes.decode("utf-8")
        assert "<CostApproach>" in xml_str
        assert "<CostType>Material</CostType>" in xml_str
        assert "<Amount>75.00</Amount>" in xml_str

    def test_write_x52_up_components(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X52)
        xml_str = xml_bytes.decode("utf-8")
        assert "<UPComp1>45.00</UPComp1>" in xml_str
        assert "<UPComp6>5.00</UPComp6>" in xml_str

    def test_write_x52_discount(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X52)
        xml_str = xml_bytes.decode("utf-8")
        assert "<DiscountPcnt>2.5</DiscountPcnt>" in xml_str

    def test_write_x52_cost_types(self) -> None:
        doc = GAEBParser.parse_string(X52_XML, filename="test.X52")
        xml_bytes, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X52)
        xml_str = xml_bytes.decode("utf-8")
        assert "<CostType>" in xml_str
        assert "<Name>Material</Name>" in xml_str

    def test_write_x52_roundtrip(self) -> None:
        doc1 = GAEBParser.parse_string(X52_XML, filename="test.X52")
        xml_bytes, _ = GAEBWriter.to_bytes(doc1, phase=ExchangePhase.X52)
        doc2 = GAEBParser.parse_string(
            xml_bytes.decode("utf-8"), filename="round.X52",
        )
        assert doc2.is_procurement
        assert doc2.item_count == doc1.item_count
        items2 = list(doc2.iter_items())
        assert isinstance(items2[0], Item)
        assert len(items2[0].cost_approaches) == 2
        assert len(items2[0].up_components) == 6


# ===========================================================================
# Enum Tests
# ===========================================================================


class TestCostEnums:
    """Test enum additions for cost phases."""

    def test_exchange_phase_x50(self) -> None:
        assert ExchangePhase.X50.value == "X50"
        assert ExchangePhase.X50.is_cost is True
        assert ExchangePhase.X50.is_trade is False

    def test_exchange_phase_x51(self) -> None:
        assert ExchangePhase.X51.value == "X51"
        assert ExchangePhase.X51.is_cost is True

    def test_exchange_phase_x52(self) -> None:
        assert ExchangePhase.X52.value == "X52"
        assert ExchangePhase.X52.is_cost is False
        assert ExchangePhase.X52.is_trade is False

    def test_document_kind_cost(self) -> None:
        assert DocumentKind.COST.value == "cost"

    def test_procurement_phases_not_cost(self) -> None:
        assert ExchangePhase.X83.is_cost is False

    def test_trade_phases_not_cost(self) -> None:
        assert ExchangePhase.X96.is_cost is False


# ===========================================================================
# GAEBDocument discriminator tests
# ===========================================================================


class TestDocumentDiscriminators:
    """Test that GAEBDocument correctly discriminates cost documents."""

    def test_cost_document_discriminator(self) -> None:
        doc = GAEBDocument(elemental_costing=ElementalCosting(dp="50.1"))
        assert doc.document_kind == DocumentKind.COST
        assert doc.is_cost is True
        assert doc.is_procurement is False
        assert doc.is_trade is False

    def test_procurement_document_discriminator(self) -> None:
        doc = GAEBDocument()
        assert doc.document_kind == DocumentKind.PROCUREMENT
        assert doc.is_procurement is True
        assert doc.is_cost is False
