"""Tests for X82 Preisspiegel multi-bidder support and BidAnalysis.

Covers:
  - BidderPrice model
  - Item.bidder_prices field
  - BidAnalysis.from_x84_bids() — multi-bid comparison
  - BidAnalysis.from_x82() — Preisspiegel document parsing
  - Parser support for <BidderUP> elements
  - Writer round-trip for bidder_prices
  - Ranking, price_spread, lowest_bidder, items_priced_by_all
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

from pygaeb import (
    BidAnalysis,
    BidderPrice,
    ExchangePhase,
    GAEBParser,
    GAEBWriter,
    ItemType,
    SourceVersion,
)
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.item import Item

# ── Helpers ──────────────────────────────────────────────────────────


def _make_tender(items: list[Item] | None = None) -> GAEBDocument:
    if items is None:
        items = [
            Item(oz="01.0010", short_text="Mauerwerk KS",
                 qty=Decimal("100"), unit="m2",
                 item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="Beton C25/30",
                 qty=Decimal("50"), unit="m3",
                 item_type=ItemType.NORMAL),
        ]
    ctgy = BoQCtgy(rno="01", label="Rohbau", items=items)
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=ExchangePhase.X83,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(
            project_no="P-TENDER", currency="EUR",
            boq=BoQ(lots=[Lot(rno="1", label="Lot", body=BoQBody(categories=[ctgy]))]),
        ),
    )


def _make_bid(bidder: str, prices: dict[str, tuple[Decimal, Decimal]]) -> GAEBDocument:
    """Build an X84 bid document with given (unit_price, total_price) per OZ."""
    items = [
        Item(oz=oz, short_text=f"Item {oz}",
             qty=Decimal("100"), unit="m2",
             unit_price=up, total_price=tp,
             item_type=ItemType.NORMAL)
        for oz, (up, tp) in prices.items()
    ]
    ctgy = BoQCtgy(rno="01", label="Rohbau", items=items)
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=ExchangePhase.X84,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(
            project_no=f"BID-{bidder}", currency="EUR",
            boq=BoQ(lots=[Lot(rno="1", label="Lot", body=BoQBody(categories=[ctgy]))]),
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# BidderPrice Model
# ═══════════════════════════════════════════════════════════════════════


class TestBidderPriceModel:
    def test_default_fields(self) -> None:
        bp = BidderPrice()
        assert bp.bidder_name == ""
        assert bp.bidder_id is None
        assert bp.unit_price is None
        assert bp.total_price is None
        assert bp.rank is None

    def test_with_values(self) -> None:
        bp = BidderPrice(
            bidder_name="Acme Bau GmbH",
            bidder_id="ACME-001",
            unit_price=Decimal("45.50"),
            total_price=Decimal("4550.00"),
            rank=1,
        )
        assert bp.bidder_name == "Acme Bau GmbH"
        assert bp.unit_price == Decimal("45.50")
        assert bp.rank == 1

    def test_item_has_bidder_prices_field(self) -> None:
        item = Item(oz="01.0010")
        assert item.bidder_prices == []
        item.bidder_prices.append(BidderPrice(bidder_name="A"))
        assert len(item.bidder_prices) == 1


# ═══════════════════════════════════════════════════════════════════════
# BidAnalysis.from_x84_bids()
# ═══════════════════════════════════════════════════════════════════════


class TestBidAnalysisFromX84:
    def _three_bids(self) -> tuple[GAEBDocument, dict[str, GAEBDocument]]:
        tender = _make_tender()
        bids = {
            "Bidder A": _make_bid("A", {
                "01.0010": (Decimal("45.00"), Decimal("4500.00")),
                "01.0020": (Decimal("180.00"), Decimal("9000.00")),
            }),
            "Bidder B": _make_bid("B", {
                "01.0010": (Decimal("50.00"), Decimal("5000.00")),
                "01.0020": (Decimal("175.00"), Decimal("8750.00")),
            }),
            "Bidder C": _make_bid("C", {
                "01.0010": (Decimal("48.00"), Decimal("4800.00")),
                "01.0020": (Decimal("190.00"), Decimal("9500.00")),
            }),
        }
        return tender, bids

    def test_bidders_listed(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert set(analysis.bidders) == {"Bidder A", "Bidder B", "Bidder C"}

    def test_ranking_sorted_by_total(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        ranking = analysis.ranking()
        # Bidder A: 13500, Bidder B: 13750, Bidder C: 14300
        assert ranking[0][0] == "Bidder A"
        assert ranking[0][1] == Decimal("13500.00")
        assert ranking[1][0] == "Bidder B"
        assert ranking[1][1] == Decimal("13750.00")
        assert ranking[2][0] == "Bidder C"

    def test_lowest_bidder(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert analysis.lowest_bidder == "Bidder A"

    def test_grand_total_per_bidder(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert analysis.grand_total("Bidder A") == Decimal("13500.00")
        assert analysis.grand_total("Bidder B") == Decimal("13750.00")
        assert analysis.grand_total("Bidder C") == Decimal("14300.00")
        assert analysis.grand_total("Unknown") is None

    def test_price_spread(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        spread = analysis.price_spread("01.0010")
        assert spread is not None
        assert spread["min"] == Decimal("45.00")
        assert spread["max"] == Decimal("50.00")
        assert spread["spread"] == Decimal("5.00")
        assert spread["count"] == Decimal("3")

    def test_price_spread_unknown_oz(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert analysis.price_spread("99.9999") is None

    def test_get_bidder_price(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        bp = analysis.get_bidder_price("Bidder A", "01.0010")
        assert bp is not None
        assert bp.unit_price == Decimal("45.00")
        assert bp.bidder_name == "Bidder A"

    def test_get_bidder_price_unknown(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert analysis.get_bidder_price("Bidder Z", "01.0010") is None
        assert analysis.get_bidder_price("Bidder A", "99.9999") is None

    def test_ranks_assigned(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        bp_a = analysis.get_bidder_price("Bidder A", "01.0010")
        bp_b = analysis.get_bidder_price("Bidder B", "01.0010")
        bp_c = analysis.get_bidder_price("Bidder C", "01.0010")
        assert bp_a is not None and bp_a.rank == 1
        assert bp_b is not None and bp_b.rank == 2
        assert bp_c is not None and bp_c.rank == 3

    def test_items_priced_by_all(self) -> None:
        tender, bids = self._three_bids()
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        common = analysis.items_priced_by_all()
        assert sorted(common) == ["01.0010", "01.0020"]

    def test_items_priced_by_all_with_missing(self) -> None:
        tender = _make_tender()
        # Bidder A prices both, Bidder B prices only one
        bids = {
            "A": _make_bid("A", {
                "01.0010": (Decimal("10"), Decimal("1000")),
                "01.0020": (Decimal("20"), Decimal("1000")),
            }),
            "B": _make_bid("B", {
                "01.0010": (Decimal("11"), Decimal("1100")),
            }),
        }
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert analysis.items_priced_by_all() == ["01.0010"]

    def test_empty_bids(self) -> None:
        tender = _make_tender()
        analysis = BidAnalysis.from_x84_bids(tender, {})
        assert analysis.bidders == []
        assert analysis.lowest_bidder is None
        assert analysis.ranking() == []
        assert analysis.items_priced_by_all() == []


# ═══════════════════════════════════════════════════════════════════════
# BidAnalysis.from_x82()
# ═══════════════════════════════════════════════════════════════════════


class TestBidAnalysisFromX82:
    def test_from_x82_with_inline_bidders(self) -> None:
        items = [
            Item(
                oz="01.0010", short_text="Mauerwerk",
                qty=Decimal("100"), unit="m2",
                item_type=ItemType.NORMAL,
                bidder_prices=[
                    BidderPrice(bidder_name="A", unit_price=Decimal("45"),
                                total_price=Decimal("4500")),
                    BidderPrice(bidder_name="B", unit_price=Decimal("48"),
                                total_price=Decimal("4800")),
                ],
            ),
        ]
        doc = _make_tender(items=items)
        doc.exchange_phase = ExchangePhase.X82
        analysis = BidAnalysis.from_x82(doc)
        assert sorted(analysis.bidders) == ["A", "B"]
        assert analysis.lowest_bidder == "A"


# ═══════════════════════════════════════════════════════════════════════
# Parser & Writer Round-Trip
# ═══════════════════════════════════════════════════════════════════════


class TestBidderPricesRoundTrip:
    def test_parser_extracts_bidder_up(self, tmp_path: Path) -> None:
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA82/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P-X82</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Rohbau</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Mauerwerk</ShortText>
                        <Qty>100</Qty><QU>m2</QU>
                        <BidderUP>
                          <BidderName>Bidder A</BidderName>
                          <UP>45.00</UP><IT>4500.00</IT>
                        </BidderUP>
                        <BidderUP>
                          <BidderName>Bidder B</BidderName>
                          <UP>50.00</UP><IT>5000.00</IT>
                        </BidderUP>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        f = tmp_path / "preisspiegel.X82"
        f.write_text(xml, encoding="utf-8")
        doc = GAEBParser.parse(str(f))
        items = list(doc.iter_items())
        assert len(items) == 1
        assert len(items[0].bidder_prices) == 2
        assert items[0].bidder_prices[0].bidder_name == "Bidder A"
        assert items[0].bidder_prices[0].unit_price == Decimal("45.00")
        assert items[0].bidder_prices[1].bidder_name == "Bidder B"
        assert items[0].bidder_prices[1].total_price == Decimal("5000.00")

    def test_writer_round_trip(self, tmp_path: Path) -> None:
        items = [
            Item(
                oz="01.0010", short_text="Test",
                qty=Decimal("100"), unit="m2",
                item_type=ItemType.NORMAL,
                bidder_prices=[
                    BidderPrice(
                        bidder_name="Bidder A", bidder_id="A001",
                        unit_price=Decimal("45.00"),
                        total_price=Decimal("4500.00"),
                    ),
                    BidderPrice(
                        bidder_name="Bidder B",
                        unit_price=Decimal("50.00"),
                        total_price=Decimal("5000.00"),
                    ),
                ],
            ),
        ]
        doc = _make_tender(items=items)
        doc.exchange_phase = ExchangePhase.X82
        out = tmp_path / "out.X82"
        GAEBWriter.write(doc, out, phase=ExchangePhase.X82)
        doc2 = GAEBParser.parse(str(out))
        items2 = list(doc2.iter_items())
        assert len(items2[0].bidder_prices) == 2
        assert items2[0].bidder_prices[0].bidder_name == "Bidder A"
        assert items2[0].bidder_prices[0].bidder_id == "A001"
        assert items2[0].bidder_prices[0].unit_price == Decimal("45.00")
        assert items2[0].bidder_prices[1].bidder_name == "Bidder B"

    def test_parser_with_attribute_form(self, tmp_path: Path) -> None:
        """Some vendors use attributes instead of child elements."""
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA82/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Test</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Item</ShortText>
                        <Qty>10</Qty><QU>Stk</QU>
                        <BidderUP name="Vendor X">
                          <UP>100.00</UP><IT>1000.00</IT>
                        </BidderUP>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        f = tmp_path / "test.X82"
        f.write_text(xml, encoding="utf-8")
        doc = GAEBParser.parse(str(f))
        items = list(doc.iter_items())
        assert len(items[0].bidder_prices) == 1
        assert items[0].bidder_prices[0].bidder_name == "Vendor X"
        assert items[0].bidder_prices[0].unit_price == Decimal("100.00")


# ═══════════════════════════════════════════════════════════════════════
# End-to-End: Parse X84 bids → BidAnalysis
# ═══════════════════════════════════════════════════════════════════════


class TestEndToEndBidComparison:
    def test_parse_three_bids_and_analyze(self, tmp_path: Path) -> None:
        def make_bid_xml(bidder: str, up1: str, it1: str, up2: str, it2: str) -> str:
            return dedent(f"""\
                <?xml version="1.0" encoding="utf-8"?>
                <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA84/3.3">
                  <GAEBInfo><Version>3.3</Version></GAEBInfo>
                  <Award>
                    <AwardInfo><Prj>P-{bidder}</Prj><Cur>EUR</Cur></AwardInfo>
                    <BoQ><BoQBody>
                      <BoQCtgy RNoPart="01"><LblTx>Rohbau</LblTx>
                        <Itemlist>
                          <Item RNoPart="0010">
                            <ShortText>Mauerwerk</ShortText>
                            <Qty>100</Qty><QU>m2</QU>
                            <UP>{up1}</UP><IT>{it1}</IT>
                          </Item>
                          <Item RNoPart="0020">
                            <ShortText>Beton</ShortText>
                            <Qty>50</Qty><QU>m3</QU>
                            <UP>{up2}</UP><IT>{it2}</IT>
                          </Item>
                        </Itemlist>
                      </BoQCtgy>
                    </BoQBody></BoQ>
                  </Award>
                </GAEB>
            """)

        tender = _make_tender()

        bid_a_path = tmp_path / "bid_a.X84"
        bid_a_path.write_text(make_bid_xml("A", "45.00", "4500.00", "180.00", "9000.00"))

        bid_b_path = tmp_path / "bid_b.X84"
        bid_b_path.write_text(make_bid_xml("B", "50.00", "5000.00", "175.00", "8750.00"))

        bids = {
            "Bidder A": GAEBParser.parse(str(bid_a_path)),
            "Bidder B": GAEBParser.parse(str(bid_b_path)),
        }
        analysis = BidAnalysis.from_x84_bids(tender, bids)
        assert analysis.lowest_bidder == "Bidder A"  # 13500 vs 13750
        assert analysis.grand_total("Bidder A") == Decimal("13500.00")
        # Parser yields leaf OZ (just the RNoPart at item level)
        ozs = analysis.items_priced_by_all()
        assert len(ozs) == 2
        spread = analysis.price_spread(ozs[0])
        assert spread is not None
        assert spread["min"] == Decimal("45.00")
        assert spread["max"] == Decimal("50.00")
