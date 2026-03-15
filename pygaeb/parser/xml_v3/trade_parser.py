"""Trade phase parser (X93-X97) — reads <Order> / <OrderItem> structure.

Inherits shared XML helpers from BaseV3Parser but replaces the Award/BoQ
parsing with flat order-item parsing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from pygaeb.models.document import GAEBDocument
from pygaeb.models.order import (
    Address,
    CustomerInfo,
    DeliveryPlaceInfo,
    InvoiceInfo,
    OrderInfo,
    OrderItem,
    PlannerInfo,
    SupplierInfo,
    TradeOrder,
)
from pygaeb.parser.recovery import parse_xml_safe
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser
from pygaeb.parser.xml_v3.richtext_parser import parse_plaintext, parse_richtext

logger = logging.getLogger("pygaeb.parser")


class TradeParser(BaseV3Parser):
    """Parser for GAEB trade phases (X93, X94, X96, X97).

    These phases use ``<Order>`` instead of ``<Award>`` and contain a flat
    list of ``<OrderItem>`` elements instead of a BoQ hierarchy.
    """

    def parse(self, path: Path, text: str) -> GAEBDocument:
        root, recovery_warnings = parse_xml_safe(text, str(path))

        self._ns = self._detect_namespace(root)
        if self._ns:
            self._ns_prefix = f"{{{self._ns}}}"

        doc = GAEBDocument(
            source_version=self.route.version,
            exchange_phase=self.route.exchange_phase,
            source_file=str(path),
            raw_namespace=self._ns,
        )
        doc.validation_results.extend(recovery_warnings)

        doc.gaeb_info = self._parse_gaeb_info(root)
        doc.order = self._parse_order(root, doc)

        if self._keep_xml:
            doc.xml_root = root

        return doc

    # ------------------------------------------------------------------
    # Order parsing
    # ------------------------------------------------------------------

    def _parse_order(self, root: etree._Element, doc: GAEBDocument) -> TradeOrder:
        order = TradeOrder()

        order_el = self._find(root, "Order")
        if order_el is None:
            doc.add_warning("No Order element found")
            return order

        dp = self._text(order_el, "DP")
        if dp:
            order.dp = dp

        order_info_el = self._find(order_el, "OrderInfo")
        if order_info_el is not None:
            order.order_info = self._parse_order_info(order_info_el)

        supplier_el = self._find(order_el, "SupplierInfo")
        if supplier_el is not None:
            order.supplier_info = SupplierInfo(
                address=self._parse_address(supplier_el),
            )

        customer_el = self._find(order_el, "CustomerInfo")
        if customer_el is not None:
            order.customer_info = CustomerInfo(
                address=self._parse_address(customer_el),
            )

        delivery_el = self._find(order_el, "DeliveryPlaceInfo")
        if delivery_el is not None:
            order.delivery_place_info = DeliveryPlaceInfo(
                address=self._parse_address(delivery_el),
            )

        planner_el = self._find(order_el, "PlannerInfo")
        if planner_el is not None:
            order.planner_info = PlannerInfo(
                address=self._parse_address(planner_el),
            )

        invoice_el = self._find(order_el, "InvoiceInfo")
        if invoice_el is not None:
            order.invoice_info = InvoiceInfo(
                address=self._parse_address(invoice_el),
            )

        for item_el in self._findall(order_el, "OrderItem"):
            item = self._parse_order_item(item_el, doc)
            order.items.append(item)

        if self._keep_xml:
            order.source_element = order_el

        # Also try PrjInfo for currency
        prj_info_el = self._find(root, "PrjInfo")
        if (
            prj_info_el is not None
            and order.order_info is not None
            and order.order_info.currency == "EUR"
        ):
            cur = self._text(prj_info_el, "Cur")
            if cur:
                order.order_info.currency = cur

        return order

    def _parse_order_info(self, el: etree._Element) -> OrderInfo:
        info = OrderInfo()
        info.order_no = self._text(el, "OrderNo", "Prj")
        info.reference = self._text(el, "Ref", "Reference")

        cur = self._text(el, "Cur")
        if cur:
            info.currency = cur

        date_str = self._text(el, "OrderDate", "Date")
        if date_str:
            info.order_date = _parse_date(date_str)

        del_str = self._text(el, "DeliveryDate")
        if del_str:
            info.delivery_date = _parse_date(del_str)

        return info

    def _parse_order_item(
        self, item_el: etree._Element, doc: GAEBDocument,
    ) -> OrderItem:
        item = OrderItem()
        item.item_id = item_el.get("ID", "") or item_el.get("RNoPart", "")

        # Text (shared tgDescription structure)
        st = self._text(item_el, "ShortText")
        if not st:
            st = self._extract_outline_text(item_el)
        item.short_text = st or ""

        long_text_el = self._find(item_el, "LongText", "Textblock")
        if long_text_el is not None:
            html_content = etree.tostring(
                long_text_el, encoding="unicode", method="html",
            )
            item.long_text = parse_richtext(html_content)

        if not item.long_text:
            desc_el = self._find(item_el, "Description")
            if desc_el is not None:
                detail_el = self._find(desc_el, "CompleteText", "DetailTxt")
                if detail_el is not None:
                    html = etree.tostring(
                        detail_el, encoding="unicode", method="html",
                    )
                    item.long_text = parse_richtext(html)

        if not item.long_text:
            lt_str = self._text(item_el, "LongText")
            if lt_str:
                item.long_text = parse_plaintext(lt_str)

        # Quantities
        qty_str = self._text(item_el, "Qty")
        if qty_str:
            item.qty = _parse_decimal(qty_str)

        item.unit = self._text(item_el, "QU")

        # Identification
        ean_str = self._text(item_el, "EAN")
        if ean_str:
            item.ean = ean_str

        item.art_no = self._text(item_el, "ArtNo")
        item.art_no_id = self._text(item_el, "ArtNoID")
        item.supplier_art_no = self._text(item_el, "SupplierArtNo")
        item.supplier_art_no_id = self._text(item_el, "SupplierArtNoID")
        item.customer_art_no = self._text(item_el, "CustomerArtNo")
        item.catalog_art_no = self._text(item_el, "CatalogArtNo")
        item.catalog_no = self._text(item_el, "CatalogNo")

        # Pricing
        op = self._text(item_el, "OfferPrice")
        if op:
            item.offer_price = _parse_decimal(op)

        np = self._text(item_el, "NetPrice")
        if np:
            item.net_price = _parse_decimal(np)

        pb = self._text(item_el, "PriceBasis")
        if pb:
            item.price_basis = _parse_decimal(pb)

        item.aqu = self._text(item_el, "AQU")

        # Flags
        item.item_chara = self._text(item_el, "ItemChara")
        item.item_type_tag = self._text(item_el, "ItemType")
        item.delivery_chara = self._text(item_el, "DeliveryChara")

        svc = self._text(item_el, "Service")
        if svc and svc.lower() in ("yes", "true", "1"):
            item.is_service = True

        # Logistics
        dd = self._text(item_el, "DeliveryDate")
        if dd:
            item.delivery_date = _parse_date(dd)

        item.mode_of_shipment = self._text(item_el, "ModeOfShipment")

        if self._keep_xml:
            item.source_element = item_el

        return item

    # ------------------------------------------------------------------
    # Address parsing (shared across info sections)
    # ------------------------------------------------------------------

    def _parse_address(self, parent_el: etree._Element) -> Address:
        addr_el = self._find(parent_el, "Address")
        if addr_el is None:
            return Address(name=self._text(parent_el, "Name"))

        return Address(
            name=self._text(addr_el, "Name"),
            name2=self._text(addr_el, "Name2"),
            street=self._text(addr_el, "Street"),
            pcode=self._text(addr_el, "PCode"),
            city=self._text(addr_el, "City"),
            country=self._text(addr_el, "Country"),
            phone=self._text(addr_el, "Phone"),
            fax=self._text(addr_el, "Fax"),
            email=self._text(addr_el, "EMail", "Email"),
        )


# ------------------------------------------------------------------
# Helpers (local copies to avoid circular import)
# ------------------------------------------------------------------

def _parse_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_date(text: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None
