"""What the writer cannot carry is reported as dropped, never lost silently.

"dropped" is the word ``ConversionReport`` counts toward ``has_data_loss``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from lxml import etree

from pygaeb import ExchangePhase, GAEBParser, GAEBWriter
from pygaeb.models.boq import Totals
from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.cost import CostElement, ECBody, ECInfo, ElementalCosting
from pygaeb.models.item import RichText
from pygaeb.models.order import OrderItem, TradeOrder
from pygaeb.writer.gaeb_writer import _add_totals, _cost_losses, _trade_losses
from tests.test_trade_parser import TRADE_X96_XML


def _written_totals(totals: Totals) -> tuple[dict[str, str], list[str]]:
    parent = etree.Element("BoQInfo")
    warnings: list[str] = []
    _add_totals(parent, totals, warnings)
    return {etree.QName(c).localname: c.text or "" for c in parent[0]}, warnings


class TestDiscounts:
    """The schema takes a discount only with its discounted total; derive it."""

    def test_percentage_discount_gets_its_discounted_total(self) -> None:
        written, warnings = _written_totals(
            Totals(total=Decimal("1000.00"), discount_pcnt=Decimal("3")),
        )
        assert Decimal(written["DiscountPcnt"]) == Decimal("3")
        assert Decimal(written["TotAfterDisc"]) == Decimal("970.00")
        assert warnings == []

    def test_amount_discount_gets_its_discounted_total(self) -> None:
        written, _ = _written_totals(Totals(total=Decimal("1000.00"), discount_amt=Decimal("50")))
        assert Decimal(written["DiscountAmt"]) == Decimal("50")
        assert Decimal(written["TotAfterDisc"]) == Decimal("950.00")

    def test_rounding_is_half_up_to_the_cent(self) -> None:
        # 100.05 x 0.90 = 90.045: half-up gives 90.05, half-even would give 90.04.
        written, _ = _written_totals(Totals(total=Decimal("100.05"), discount_pcnt=Decimal("10")))
        assert Decimal(written["TotAfterDisc"]) == Decimal("90.05")

    def test_a_stated_discounted_total_is_kept(self) -> None:
        written, _ = _written_totals(
            Totals(total=Decimal("1000.00"), discount_pcnt=Decimal("3"),
                   tot_after_disc=Decimal("969.99")),
        )
        assert Decimal(written["TotAfterDisc"]) == Decimal("969.99")

    def test_discount_without_a_total_is_reported(self) -> None:
        written, warnings = _written_totals(Totals(discount_pcnt=Decimal("3")))
        assert "DiscountPcnt" not in written
        assert any("discount dropped" in w for w in warnings)


class TestTradeLosses:
    def test_a_parsed_order_reports_what_it_cannot_write(self) -> None:
        doc = GAEBParser.parse_bytes(TRADE_X96_XML.encode(), filename="order.X96")
        _, warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X96)
        assert any(w.startswith("Service dropped for 1 order item(s)") for w in warnings)

    def test_every_unwritten_field_is_named(self) -> None:
        order = TradeOrder(items=[OrderItem(
            item_id="A-1", short_text="Schrauben", long_text=RichText.from_plain("lang"),
            item_chara="x", item_type_tag="y", delivery_chara="z", is_service=True,
        )])
        lines = _trade_losses(order)
        for what in ("long text", "ItemChara", "ItemType", "DeliveryChara", "Service"):
            assert any(line.startswith(f"{what} dropped for 1 order item(s)") for line in lines)


class TestCostLosses:
    def test_every_unwritten_field_is_named(self) -> None:
        ec = ElementalCosting(
            ec_info=ECInfo(date_of_information=datetime(2026, 1, 1)),
            body=ECBody(cost_elements=[CostElement(
                ele_no="310", short_text="Baugrube", long_text=RichText.from_plain("lang"),
                ctlg_assigns=[CtlgAssign(ctlg_id="DIN276", ctlg_code="310")],
            )]),
        )
        lines = _cost_losses(ec)
        assert any(line.startswith("DateOfInformation dropped") for line in lines)
        assert any(line.startswith("CtlgAssign dropped for 1 cost element(s)") for line in lines)
        assert any(line.startswith("long text dropped for 1 cost element(s)") for line in lines)

    def test_nothing_reported_when_nothing_is_lost(self) -> None:
        ec = ElementalCosting(body=ECBody(cost_elements=[CostElement(ele_no="310")]))
        assert _cost_losses(ec) == []
