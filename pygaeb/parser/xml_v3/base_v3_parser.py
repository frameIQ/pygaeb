"""Base parser for DA XML 3.x (Track B) — handles BoQ, BoQCtgy, Item, AwardInfo.

Supports iterparse for large files and two-pass recovery on malformed XML.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.boq import BoQ, BoQBkdn, BoQBody, BoQCtgy, BoQInfo, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import (
    BkdnType,
    ItemType,
)
from pygaeb.models.item import Item, QtySplit
from pygaeb.parser.recovery import parse_xml_safe
from pygaeb.parser.xml_v3.richtext_parser import parse_plaintext, parse_richtext

logger = logging.getLogger("pygaeb.parser")


class BaseV3Parser:
    """Shared parse logic for all DA XML 3.x versions."""

    def __init__(self, route: ParseRoute) -> None:
        self.route = route
        self._ns: str | None = None
        self._ns_prefix: str = ""
        self._category_labels: dict[str, str] = {}
        self._bkdn: list[BoQBkdn] = []

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
        doc.award = self._parse_award(root, doc)

        return doc

    def _tag(self, local: str) -> str:
        """Build a namespaced tag name."""
        return f"{self._ns_prefix}{local}" if self._ns_prefix else local

    def _find(self, parent: etree._Element, *tags: str) -> etree._Element | None:
        for tag in tags:
            el = parent.find(self._tag(tag))
            if el is not None:
                return el
            el = parent.find(tag)
            if el is not None:
                return el
        return None

    def _findall(self, parent: etree._Element, tag: str) -> list[etree._Element]:
        result = parent.findall(self._tag(tag))
        if not result:
            result = parent.findall(tag)
        return result

    def _text(self, parent: etree._Element, *tags: str) -> str | None:
        el = self._find(parent, *tags)
        if el is not None and el.text:
            return el.text.strip()
        return None

    def _detect_namespace(self, root: etree._Element) -> str | None:
        tag = root.tag
        if tag.startswith("{"):
            return tag[1:].split("}", 1)[0]
        return None

    def _parse_gaeb_info(self, root: etree._Element) -> GAEBInfo:
        info = GAEBInfo()
        gaeb_info_el = self._find(root, "GAEBInfo")
        if gaeb_info_el is None:
            return info

        info.version = self._text(gaeb_info_el, "Version")
        info.prog_system = self._text(gaeb_info_el, "ProgSystem")
        info.prog_system_version = self._text(gaeb_info_el, "ProgSystemVersion")

        date_str = self._text(gaeb_info_el, "Date")
        if date_str:
            info.date = _parse_date(date_str)

        return info

    def _parse_award(self, root: etree._Element, doc: GAEBDocument) -> AwardInfo:
        award = AwardInfo()

        award_el = self._find(root, "Award")
        if award_el is None:
            doc.add_warning("No Award element found")
            return award

        award_info_el = self._find(award_el, "AwardInfo")
        if award_info_el is not None:
            award.project_no = self._text(award_info_el, "Prj")
            award.project_name = self._text(award_info_el, "PrjName", "Name")
            award.client = self._text(award_info_el, "OWN", "Client")
            award.currency = self._text(award_info_el, "Cur") or "EUR"
            award.procurement_type = self._text(award_info_el, "PrcTyp")
            date_str = self._text(award_info_el, "Dp")
            if date_str:
                award.date = _parse_date(date_str)

        boq_el = self._find(award_el, "BoQ")
        if boq_el is not None:
            award.boq = self._parse_boq(boq_el, doc)
        else:
            doc.add_warning("No BoQ element found in Award")

        return award

    def _parse_boq(self, boq_el: etree._Element, doc: GAEBDocument) -> BoQ:
        boq = BoQ()

        boq_info_el = self._find(boq_el, "BoQInfo")
        if boq_info_el is not None:
            boq.boq_info = self._parse_boq_info(boq_info_el)
            self._bkdn = boq.boq_info.bkdn

        boq_body_el = self._find(boq_el, "BoQBody")
        if boq_body_el is not None:
            lot = Lot(rno="1", label="Default", boq_info=boq.boq_info)
            lot.body = self._parse_boq_body(boq_body_el, doc)
            boq.lots.append(lot)

            lot_els = self._findall(boq_body_el, "BoQCtgy")
            if lot_els and len(lot_els) > 1 and self._has_lot_bkdn():
                boq.lots = []
                for i, lot_el in enumerate(lot_els):
                    rno = lot_el.get("RNoPart", str(i + 1))
                    label = self._text(lot_el, "LblTx") or f"Lot {i + 1}"
                    lot = Lot(rno=rno, label=label, boq_info=boq.boq_info)
                    lot.body = self._parse_ctgy_as_body(lot_el, doc, lot_label=label)
                    boq.lots.append(lot)

        return boq

    def _parse_boq_info(self, info_el: etree._Element) -> BoQInfo:
        info = BoQInfo()
        info.name = self._text(info_el, "Name")
        info.lbl_boq = self._text(info_el, "LblBoQ")

        bkdn_el = self._find(info_el, "BoQBkdn")
        if bkdn_el is not None:
            for level_el in bkdn_el:
                tag = self._local_tag(level_el.tag)
                length_str = level_el.get("Length", "0")
                try:
                    length = int(length_str)
                except ValueError:
                    length = 0

                bkdn_type = _bkdn_type_from_tag(tag)
                info.bkdn.append(BoQBkdn(
                    bkdn_type=bkdn_type,
                    length=length,
                    key=level_el.get("Key", tag),
                ))

        return info

    def _parse_boq_body(self, body_el: etree._Element, doc: GAEBDocument) -> BoQBody:
        body = BoQBody()
        for ctgy_el in self._findall(body_el, "BoQCtgy"):
            ctgy = self._parse_ctgy(ctgy_el, doc, [])
            body.categories.append(ctgy)
        return body

    def _parse_ctgy_as_body(
        self, ctgy_el: etree._Element, doc: GAEBDocument, lot_label: str = ""
    ) -> BoQBody:
        body = BoQBody()
        for sub_el in self._findall(ctgy_el, "BoQBody"):
            for inner_ctgy_el in self._findall(sub_el, "BoQCtgy"):
                ctgy = self._parse_ctgy(inner_ctgy_el, doc, [], lot_label=lot_label)
                body.categories.append(ctgy)
        if not body.categories:
            ctgy = self._parse_ctgy(ctgy_el, doc, [], lot_label=lot_label)
            body.categories.append(ctgy)
        return body

    def _parse_ctgy(
        self,
        ctgy_el: etree._Element,
        doc: GAEBDocument,
        parent_path: list[str],
        lot_label: str = "",
    ) -> BoQCtgy:
        rno = ctgy_el.get("RNoPart", "")
        label = self._text(ctgy_el, "LblTx") or ""
        ctgy = BoQCtgy(rno=rno, label=label, lbl_tx=label)

        current_path = parent_path + ([label] if label else [rno] if rno else [])

        if rno:
            self._category_labels[rno] = label or rno

        boq_body_el = self._find(ctgy_el, "BoQBody")
        target = boq_body_el if boq_body_el is not None else ctgy_el

        for sub_ctgy_el in self._findall(target, "BoQCtgy"):
            sub = self._parse_ctgy(sub_ctgy_el, doc, current_path, lot_label)
            ctgy.subcategories.append(sub)

        for item_el in self._findall(target, "Itemlist"):
            for it_el in self._findall(item_el, "Item"):
                item = self._parse_item(it_el, doc, current_path, lot_label)
                ctgy.items.append(item)

        for it_el in self._findall(target, "Item"):
            if it_el.getparent() is not None:
                parent_tag = self._local_tag(it_el.getparent().tag)
                if parent_tag == "Itemlist":
                    continue
            item = self._parse_item(it_el, doc, current_path, lot_label)
            ctgy.items.append(item)

        return ctgy

    def _parse_item(
        self,
        item_el: etree._Element,
        doc: GAEBDocument,
        hierarchy_path: list[str],
        lot_label: str = "",
    ) -> Item:
        oz = item_el.get("RNoPart", "")

        item = Item(
            oz=oz,
            hierarchy_path=hierarchy_path,
            lot_label=lot_label or None,
        )

        item.short_text = self._text(item_el, "Qty", "ShortText", "Description") or ""
        short_text_el = self._find(item_el, "Description")
        if short_text_el is not None:
            item.short_text = self._text(short_text_el, "CompleteText", "OutlineText") or ""
            if not item.short_text:
                item.short_text = short_text_el.text or "" if short_text_el.text else ""

        st = self._text(item_el, "ShortText")
        if st:
            item.short_text = st

        qty_el = self._find(item_el, "Qty")
        if qty_el is not None:
            item.qty = _parse_decimal(qty_el.text)

        qu_el = self._find(item_el, "QU")
        if qu_el is not None:
            item.unit = qu_el.text.strip() if qu_el.text else None

        up_el = self._find(item_el, "UP")
        if up_el is not None:
            item.unit_price = _parse_decimal(up_el.text)

        it_el = self._find(item_el, "IT")
        if it_el is not None:
            item.total_price = _parse_decimal(it_el.text)

        item.item_type = self._detect_item_type(item_el)

        qty_splits = self._parse_qty_splits(item_el)
        if qty_splits:
            item.qty_splits = qty_splits

        long_text_el = self._find(item_el, "LongText", "Textblock")
        if long_text_el is not None:
            html_content = etree.tostring(long_text_el, encoding="unicode", method="html")
            item.long_text = parse_richtext(html_content)

        if not item.long_text:
            lt_str = self._text(item_el, "LongText")
            if lt_str:
                item.long_text = parse_plaintext(lt_str)

        bim_el = self._find(item_el, "GUID", "BIMRef")
        if bim_el is not None:
            item.bim_guid = bim_el.text.strip() if bim_el.text else None

        co_el = self._find(item_el, "CONo")
        if co_el is not None:
            item.change_order_number = co_el.text.strip() if co_el.text else None

        return item

    def _detect_item_type(self, item_el: etree._Element) -> ItemType:
        item_tag = self._text(item_el, "ItemTag")
        if item_tag:
            tag_map = {
                "NormalItem": ItemType.NORMAL,
                "LumpSumItem": ItemType.LUMP_SUM,
                "AlternativeItem": ItemType.ALTERNATIVE,
                "ContingencyItem": ItemType.EVENTUAL,
                "EventualItem": ItemType.EVENTUAL,
                "TextItem": ItemType.TEXT_ONLY,
                "SurchargeItem": ItemType.BASE_SURCHARGE,
                "IndexItem": ItemType.INDEX,
                "SupplementItem": ItemType.SUPPLEMENT,
            }
            return tag_map.get(item_tag, ItemType.NORMAL)

        for child in item_el:
            tag = self._local_tag(child.tag)
            if tag in ("LumpSumItem", "GlobItem"):
                return ItemType.LUMP_SUM
            if tag in ("AlternativeItem", "AltItem"):
                return ItemType.ALTERNATIVE
            if tag in ("ContingencyItem", "EventualItem"):
                return ItemType.EVENTUAL
            if tag == "TextItem":
                return ItemType.TEXT_ONLY
            if tag == "SurchargeItem":
                return ItemType.BASE_SURCHARGE
            if tag == "SupplementItem":
                return ItemType.SUPPLEMENT

        return ItemType.NORMAL

    def _parse_qty_splits(self, item_el: etree._Element) -> list[QtySplit]:
        splits: list[QtySplit] = []
        for qs_el in self._findall(item_el, "QtySplit"):
            label = self._text(qs_el, "Label", "Description") or ""
            qty = _parse_decimal(self._text(qs_el, "Qty"))
            unit = self._text(qs_el, "QU")
            if qty is not None:
                splits.append(QtySplit(label=label, qty=qty, unit=unit))
        return splits

    def _has_lot_bkdn(self) -> bool:
        return any(b.bkdn_type == BkdnType.LOT for b in self._bkdn)

    def _local_tag(self, tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag


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


def _bkdn_type_from_tag(tag: str) -> BkdnType:
    tag_lower = tag.lower()
    if "lot" in tag_lower:
        return BkdnType.LOT
    if "item" in tag_lower:
        return BkdnType.ITEM
    if "index" in tag_lower:
        return BkdnType.INDEX
    return BkdnType.BOQ_LEVEL
