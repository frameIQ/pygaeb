"""Base parser for DA XML 3.x (Track B) — handles BoQ, BoQCtgy, Item, AwardInfo.

Supports iterparse for large files and two-pass recovery on malformed XML.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from lxml import etree

from pygaeb.detector.version_detector import ParseRoute
from pygaeb.models.boq import (
    BoQ,
    BoQBkdn,
    BoQBody,
    BoQCtgy,
    BoQInfo,
    CostType,
    Lot,
    Totals,
    VATPart,
)
from pygaeb.models.catalog import CtlgAssign
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.order import Address
from pygaeb.models.enums import (
    BkdnType,
    ItemType,
)
from pygaeb.models.item import Attachment, CostApproach, Item, MarkupSubQty, QtySplit
from pygaeb.parser.recovery import parse_xml_safe
from pygaeb.parser.xml_v3.richtext_parser import parse_plaintext, parse_richtext

logger = logging.getLogger("pygaeb.parser")

KNOWN_ITEM_TAGS: frozenset[str] = frozenset({
    "ShortText", "Qty", "QU", "UP", "IT",
    "LongText", "Description", "CompleteText", "OutlineText",
    "QtySplit", "ItemTag", "GUID", "BIMRef", "CONo",
    "CostApproach", "UPComp1", "UPComp2", "UPComp3",
    "UPComp4", "UPComp5", "UPComp6", "DiscountPcnt", "VAT",
    "CtlgAssign", "Attachment", "ATTImage", "ATTBinary",
    "LumpSumItem", "GlobItem", "AlternativeItem", "AltItem",
    "ContingencyItem", "EventualItem", "TextItem",
    "SurchargeItem", "SupplementItem", "IndexItem",
    "Itemlist", "Item",
})


class BaseV3Parser:
    """Shared parse logic for all DA XML 3.x versions."""

    def __init__(self, route: ParseRoute, keep_xml: bool = False) -> None:
        self.route = route
        self._ns: str | None = None
        self._ns_prefix: str = ""
        self._category_labels: dict[str, str] = {}
        self._bkdn: list[BoQBkdn] = []
        self._keep_xml = keep_xml

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

        if self._keep_xml:
            doc.xml_root = root

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

    def _findall(self, parent: etree._Element, tag: str) -> list[Any]:
        result = parent.findall(self._tag(tag))
        if not result:
            result = parent.findall(tag)
        return result

    def _text(self, parent: etree._Element, *tags: str) -> str | None:
        el = self._find(parent, *tags)
        if el is None:
            return None
        if el.text and str(el.text).strip():
            return str(el.text).strip()
        full = "".join(str(t) for t in el.itertext()).strip()
        return full or None

    def _detect_namespace(self, root: etree._Element) -> str | None:
        tag = str(root.tag)
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

        if self._keep_xml:
            info.source_element = gaeb_info_el

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
            award.currency = self._text(award_info_el, "Cur") or "EUR"
            award.procurement_type = self._text(award_info_el, "PrcTyp")
            date_str = self._text(award_info_el, "Dp")
            if date_str:
                award.date = _parse_date(date_str)

            award.category = self._text(award_info_el, "Cat")
            if not award.currency_label:
                award.currency_label = self._text(award_info_el, "CurLbl")

            for tag, attr in [
                ("OpenDate", "open_date"), ("EvalEnd", "eval_end"),
                ("CnstStart", "construction_start"), ("CnstEnd", "construction_end"),
                ("ContrDate", "contract_date"),
            ]:
                ds = self._text(award_info_el, tag)
                if ds:
                    setattr(award, attr, _parse_date(ds))

            award.open_time = self._text(award_info_el, "OpenTime")
            award.submit_location = self._text(award_info_el, "SubmLoc")
            award.contract_no = self._text(award_info_el, "ContrNo")
            award.accept_type = self._text(award_info_el, "AcceptType")
            award.warranty_unit = self._text(award_info_el, "WarrUnit")

            warr_dur = self._text(award_info_el, "WarrDur")
            if warr_dur:
                with contextlib.suppress(ValueError):
                    award.warranty_duration = int(warr_dur)

        own_el = self._find(award_el, "OWN")
        if own_el is not None:
            award.owner_address = self._parse_address(own_el)
            award.award_no = self._text(own_el, "AwardNo")
            if award.owner_address and award.owner_address.name:
                award.client = award.owner_address.name
        elif award_info_el is not None:
            award.client = self._text(award_info_el, "OWN", "Client")

        prj_info_el = self._find(root, "PrjInfo")
        if prj_info_el is not None:
            if not award.project_name:
                award.project_name = self._text(prj_info_el, "NamePrj", "PrjName")
            if not award.currency or award.currency == "EUR":
                award.currency = self._text(prj_info_el, "Cur") or award.currency

            award.prj_id = self._text(prj_info_el, "PrjID")
            award.lbl_prj = self._text(prj_info_el, "LblPrj")
            award.description = self._text(prj_info_el, "Descrip")
            award.currency_label = self._text(prj_info_el, "CurLbl")

            bcp = self._text(prj_info_el, "BidCommPerm")
            if bcp and bcp.lower() in ("yes", "true", "1"):
                award.bid_comm_perm = True

            abp = self._text(prj_info_el, "AlterBidPerm")
            if abp and abp.lower() in ("yes", "true", "1"):
                award.alter_bid_perm = True

            upfd = self._text(prj_info_el, "UPFracDig")
            if upfd:
                with contextlib.suppress(ValueError):
                    award.up_frac_dig = int(upfd)

            award.ctlg_assigns = self._parse_ctlg_assigns(prj_info_el)

        boq_el = self._find(award_el, "BoQ")
        if boq_el is not None:
            award.boq = self._parse_boq(boq_el, doc)
        else:
            doc.add_warning("No BoQ element found in Award")

        if self._keep_xml:
            award.source_element = award_el

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
            lot.totals = self._parse_totals(boq_body_el)
            boq.lots.append(lot)

            lot_els = self._findall(boq_body_el, "BoQCtgy")
            if lot_els and len(lot_els) > 1 and self._has_lot_bkdn():
                boq.lots = []
                for i, lot_el in enumerate(lot_els):
                    rno = lot_el.get("RNoPart", str(i + 1))
                    label = self._text(lot_el, "LblTx") or f"Lot {i + 1}"
                    lot = Lot(rno=rno, label=label, boq_info=boq.boq_info)
                    lot.body = self._parse_ctgy_as_body(lot_el, doc, lot_label=label)
                    lot.totals = self._parse_totals(lot_el)
                    boq.lots.append(lot)

        return boq

    def _parse_boq_info(self, info_el: etree._Element) -> BoQInfo:
        info = BoQInfo()
        info.name = self._text(info_el, "Name")
        info.lbl_boq = self._text(info_el, "LblBoQ")

        bkdn_els = self._findall(info_el, "BoQBkdn")
        if len(bkdn_els) > 1:
            self._parse_bkdn_v32(bkdn_els, info)
        elif len(bkdn_els) == 1:
            self._parse_bkdn_v33(bkdn_els[0], info)

        for ct_el in self._findall(info_el, "CostType"):
            ct = CostType(
                name=self._text(ct_el, "Name") or "",
                label=self._text(ct_el, "Label") or "",
            )
            info.cost_types.append(ct)

        info.ctlg_assigns = self._parse_ctlg_assigns(info_el)
        info.totals = self._parse_totals(info_el)

        return info

    def _parse_bkdn_v33(self, bkdn_el: etree._Element, info: BoQInfo) -> None:
        """v3.3 format: single <BoQBkdn> with <BoQLevel Length="2"/> children."""
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

    def _parse_bkdn_v32(self, bkdn_els: list[Any], info: BoQInfo) -> None:
        """v3.2 format: multiple <BoQBkdn> siblings, each with <Type>/<Length> children."""
        for bkdn_el in bkdn_els:
            type_text = self._text(bkdn_el, "Type") or "BoQLevel"
            length_str = self._text(bkdn_el, "Length") or "0"
            try:
                length = int(length_str)
            except ValueError:
                length = 0

            bkdn_type = _bkdn_type_from_tag(type_text)
            info.bkdn.append(BoQBkdn(
                bkdn_type=bkdn_type,
                length=length,
                key=type_text,
            ))

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
            for mu_el in self._findall(item_el, "MarkupItem"):
                markup_item = self._parse_markup_item(mu_el, doc, current_path, lot_label)
                ctgy.items.append(markup_item)

        for it_el in self._findall(target, "Item"):
            if it_el.getparent() is not None:
                parent_tag = self._local_tag(it_el.getparent().tag)
                if parent_tag == "Itemlist":
                    continue
            item = self._parse_item(it_el, doc, current_path, lot_label)
            ctgy.items.append(item)

        ctgy.ctlg_assigns = self._parse_ctlg_assigns(ctgy_el)
        ctgy.totals = self._parse_totals(ctgy_el)

        if self._keep_xml:
            ctgy.source_element = ctgy_el

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

        st = self._text(item_el, "ShortText")
        if not st:
            st = self._extract_outline_text(item_el)
        item.short_text = st or ""

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

        if not item.long_text:
            desc_el = self._find(item_el, "Description")
            if desc_el is not None:
                detail_el = self._find(desc_el, "CompleteText", "DetailTxt")
                if detail_el is not None:
                    html = etree.tostring(detail_el, encoding="unicode", method="html")
                    item.long_text = parse_richtext(html)

        item.attachments = self._parse_item_attachments(item_el)

        bim_el = self._find(item_el, "GUID", "BIMRef")
        if bim_el is not None:
            item.bim_guid = bim_el.text.strip() if bim_el.text else None

        co_el = self._find(item_el, "CONo")
        if co_el is not None:
            item.change_order_number = co_el.text.strip() if co_el.text else None

        for ca_el in self._findall(item_el, "CostApproach"):
            ca = CostApproach(
                cost_type=self._text(ca_el, "CostType") or "",
                amount=_parse_decimal(self._text(ca_el, "Amount")),
                remark=self._text(ca_el, "Remark") or "",
            )
            if self._keep_xml:
                ca.source_element = ca_el
            item.cost_approaches.append(ca)

        for i in range(1, 7):
            val = _parse_decimal(self._text(item_el, f"UPComp{i}"))
            if val is not None:
                while len(item.up_components) < i:
                    item.up_components.append(Decimal("0"))
                item.up_components[i - 1] = val

        disc_str = self._text(item_el, "DiscountPcnt")
        if disc_str:
            item.discount_pct = _parse_decimal(disc_str)

        vat_str = self._text(item_el, "VAT")
        if vat_str:
            item.vat = _parse_decimal(vat_str)

        item.ctlg_assigns = self._parse_ctlg_assigns(item_el)

        if self._keep_xml:
            item.source_element = item_el

        return item

    def _parse_markup_item(
        self,
        el: etree._Element,
        doc: GAEBDocument,
        hierarchy_path: list[str],
        lot_label: str = "",
    ) -> Item:
        """Parse a ``<MarkupItem>`` element (X52) into an ``Item`` with ``ItemType.MARKUP``."""
        oz = el.get("RNoPart", "")
        item = Item(
            oz=oz,
            hierarchy_path=hierarchy_path,
            lot_label=lot_label or None,
            item_type=ItemType.MARKUP,
        )

        item.short_text = self._text(el, "ShortText") or ""
        item.markup_type = self._text(el, "MarkupType")

        it_str = self._text(el, "ITMarkup")
        if it_str:
            item.total_price = _parse_decimal(it_str)

        markup_str = self._text(el, "Markup")
        if markup_str:
            item.unit_price = _parse_decimal(markup_str)

        disc_str = self._text(el, "DiscountPcnt")
        if disc_str:
            item.discount_pct = _parse_decimal(disc_str)

        for sub_el in self._findall(el, "MarkupSubQty"):
            ref_rno = self._text(sub_el, "RefRNoPart") or sub_el.get("RNoPart", "")
            sub_qty = _parse_decimal(self._text(sub_el, "SubQty"))
            item.markup_sub_qtys.append(MarkupSubQty(ref_rno=ref_rno, sub_qty=sub_qty))

        item.ctlg_assigns = self._parse_ctlg_assigns(el)

        if self._keep_xml:
            item.source_element = el

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

    def _extract_outline_text(self, item_el: etree._Element) -> str | None:
        """Extract short text from Description/OutlineText structure.

        Handles both flat and nested paths:
          <Description>/<CompleteText>/<OutlineText>/<OutlTxt>/<TextOutlTxt>/<span>
          <Description>/<OutlineText>/...
        """
        desc = self._find(item_el, "Description")
        if desc is None:
            return None

        for outline in self._walk_to(desc, "OutlineText"):
            txt = self._text(outline, "OutlTxt", "TextOutlTxt")
            if txt:
                return txt
            full = "".join(str(t) for t in outline.itertext()).strip()
            if full:
                return full
        return None

    def _walk_to(
        self, el: etree._Element, target_tag: str
    ) -> list[Any]:
        """Find target_tag at any depth below el (BFS one level of nesting)."""
        direct = self._findall(el, target_tag)
        if direct:
            return direct
        results: list[Any] = []
        for child in el:
            found = self._findall(child, target_tag)
            results.extend(found)
        return results

    def _parse_ctlg_assign(self, el: etree._Element) -> CtlgAssign:
        """Parse a single ``<CtlgAssign>`` element."""
        return CtlgAssign(
            ctlg_id=self._text(el, "CtlgID") or "",
            ctlg_code=self._text(el, "CtlgCode") or "",
            quantity=_parse_decimal(self._text(el, "Quantity")),
        )

    def _parse_ctlg_assigns(self, parent: etree._Element) -> list[CtlgAssign]:
        """Parse all ``<CtlgAssign>`` children of *parent*."""
        return [self._parse_ctlg_assign(el) for el in self._findall(parent, "CtlgAssign")]

    def _parse_totals(self, parent: etree._Element) -> Totals | None:
        """Parse a ``<Totals>`` child element into a :class:`Totals` model."""
        totals_el = self._find(parent, "Totals")
        if totals_el is None:
            return None

        t = Totals()
        t.total = _parse_decimal(self._text(totals_el, "Total"))
        t.discount_pcnt = _parse_decimal(self._text(totals_el, "DiscountPcnt"))
        t.discount_amt = _parse_decimal(self._text(totals_el, "DiscountAmt"))
        t.tot_after_disc = _parse_decimal(self._text(totals_el, "TotAfterDisc"))
        t.total_lsum = _parse_decimal(self._text(totals_el, "TotalLSUM"))
        t.vat = _parse_decimal(self._text(totals_el, "VAT"))
        t.total_net = _parse_decimal(self._text(totals_el, "TotalNet"))

        up_comp_el = self._find(totals_el, "TotalNetUpComp")
        if up_comp_el is not None:
            for i in range(1, 7):
                val = _parse_decimal(self._text(up_comp_el, f"UpComp{i}"))
                if val is not None:
                    while len(t.total_net_up_comp) < i:
                        t.total_net_up_comp.append(Decimal("0"))
                    t.total_net_up_comp[i - 1] = val

        for vp_el in self._findall(totals_el, "VATPart"):
            pcnt = _parse_decimal(vp_el.get("VATPcnt")) or Decimal("0")
            vp = VATPart(
                vat_pcnt=pcnt,
                total_net_part=_parse_decimal(self._text(vp_el, "TotalNetPart")),
                vat_amount=_parse_decimal(self._text(vp_el, "VATAmount")),
            )
            t.vat_parts.append(vp)

        t.vat_amount = _parse_decimal(self._text(totals_el, "VATAmount"))
        t.total_gross = _parse_decimal(self._text(totals_el, "TotalGross"))
        return t

    def _parse_item_attachments(self, item_el: etree._Element) -> list[Attachment]:
        """Extract attachments from a procurement item's ``<Description>`` subtree.

        Handles two patterns defined in the GAEB Lib schema:
        - URI references: ``<attachment>`` elements (plain URI strings)
        - Embedded images: ``<image>`` elements with base64 content and
          ``Type``/``Name`` attributes
        """
        import base64

        attachments: list[Attachment] = []

        desc = self._find(item_el, "Description")
        if desc is None:
            return attachments

        for att_el in desc.iter():
            local = self._local_tag(att_el.tag)
            if local == "attachment" and att_el.text and att_el.text.strip():
                uri = att_el.text.strip()
                attachments.append(Attachment(
                    filename=uri,
                    mime_type="application/octet-stream",
                    data=b"",
                ))
            elif local == "image":
                b64_text = att_el.text or ""
                if not b64_text.strip():
                    continue
                mime = att_el.get("Type", "image/png")
                name = att_el.get("Name", "embedded_image")
                try:
                    data = base64.b64decode(b64_text.strip())
                except Exception:
                    logger.warning("Failed to decode embedded image %s", name)
                    continue
                attachments.append(Attachment(
                    filename=name,
                    mime_type=mime,
                    data=data,
                ))

        return attachments

    def _parse_address(self, parent_el: etree._Element) -> Address:
        """Parse a ``tgAddress`` structure from *parent_el*.

        Handles both XSD-canonical ``Name1``-``Name4`` and older ``Name``
        fallback for non-conformant files.
        """
        addr_el = self._find(parent_el, "Address")
        if addr_el is None:
            return Address(name=self._text(parent_el, "Name", "Name1"))
        return Address(
            name=self._text(addr_el, "Name1", "Name"),
            name2=self._text(addr_el, "Name2"),
            name3=self._text(addr_el, "Name3"),
            name4=self._text(addr_el, "Name4"),
            street=self._text(addr_el, "Street"),
            pcode=self._text(addr_el, "PCode"),
            city=self._text(addr_el, "City"),
            country=self._text(addr_el, "Country"),
            contact=self._text(addr_el, "Contact"),
            phone=self._text(addr_el, "Phone"),
            fax=self._text(addr_el, "Fax"),
            email=self._text(addr_el, "EMail", "Email"),
            iln=self._text(addr_el, "ILN"),
            vat_id=self._text(addr_el, "VATID"),
        )

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
