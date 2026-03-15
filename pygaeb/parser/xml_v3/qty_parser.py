"""Quantity determination parser (X31) — reads <QtyDeterm> structure.

Inherits shared XML helpers from BaseV3Parser but replaces the Award/BoQ
parsing with the X31-specific QtyDetermination / QtyBoQ hierarchy.
"""

from __future__ import annotations

import base64
import contextlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from pygaeb.models.boq import BoQBkdn
from pygaeb.models.catalog import Catalog, CtlgAssign
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import BkdnType
from pygaeb.models.quantity import (
    PrjInfoQD,
    QDetermItem,
    QTakeoffRow,
    QtyAttachment,
    QtyBoQ,
    QtyBoQBody,
    QtyBoQCtgy,
    QtyDetermination,
    QtyDetermInfo,
    QtyItem,
)
from pygaeb.parser.recovery import parse_xml_safe
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser

logger = logging.getLogger("pygaeb.parser")


class QtyParser(BaseV3Parser):
    """Parser for GAEB quantity determination phase (X31).

    These documents use ``<QtyDeterm>`` instead of ``<Award>`` and contain
    a simplified BoQ with quantity take-off measurement rows.
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
        doc.qty_determination = self._parse_qty_determination(root, doc)

        if self._keep_xml:
            doc.xml_root = root

        return doc

    # ------------------------------------------------------------------
    # QtyDetermination root
    # ------------------------------------------------------------------

    def _parse_qty_determination(
        self, root: etree._Element, doc: GAEBDocument,
    ) -> QtyDetermination:
        qd = QtyDetermination()

        qd_el = self._find(root, "QtyDeterm")
        if qd_el is None:
            doc.add_warning("No QtyDeterm element found")
            return qd

        dp_str = self._text(qd_el, "DP")
        if dp_str:
            qd.dp = dp_str

        prj_info_el = self._find(qd_el, "PrjInfo")
        if prj_info_el is not None:
            qd.prj_info = self._parse_prj_info_qd(prj_info_el)

        info_el = self._find(qd_el, "QtyDetermInfo")
        if info_el is not None:
            qd.info = self._parse_qty_determ_info(info_el)

        own_el = self._find(qd_el, "OWN")
        if own_el is not None:
            qd.owner = self._parse_address(own_el)

        ctr_el = self._find(qd_el, "CTR")
        if ctr_el is not None:
            qd.contractor = self._parse_address(ctr_el)

        boq_el = self._find(qd_el, "BoQ")
        if boq_el is not None:
            qd.boq = self._parse_qty_boq(boq_el, doc)
        else:
            doc.add_warning("No BoQ element found in QtyDeterm")

        return qd

    # ------------------------------------------------------------------
    # PrjInfoQD
    # ------------------------------------------------------------------

    def _parse_prj_info_qd(self, el: etree._Element) -> PrjInfoQD:
        return PrjInfoQD(
            ref_prj_name=self._text(el, "RefPrjName") or "",
            ref_prj_id=self._text(el, "RefPrjID") or "",
        )

    # ------------------------------------------------------------------
    # QtyDetermInfo
    # ------------------------------------------------------------------

    def _parse_qty_determ_info(self, el: etree._Element) -> QtyDetermInfo:
        info = QtyDetermInfo()
        info.method = self._text(el, "MethodDescription") or ""
        info.order_descr = self._text(el, "OrdDescr") or ""
        info.project_descr = self._text(el, "ProjDescr") or ""

        start_str = self._text(el, "ServiceProvisionStartDate")
        if start_str:
            info.service_start = _parse_date(start_str)

        end_str = self._text(el, "ServiceProvisionEndDate")
        if end_str:
            info.service_end = _parse_date(end_str)

        creator_el = self._find(el, "Creator")
        if creator_el is not None:
            info.creator = self._parse_address(creator_el)

        profiler_el = self._find(el, "Profiler")
        if profiler_el is not None:
            info.profiler = self._parse_address(profiler_el)

        for ca_el in self._findall(el, "CtlgAssign"):
            info.ctlg_assigns.append(self._parse_ctlg_assign(ca_el))

        return info

    # ------------------------------------------------------------------
    # QtyBoQ
    # ------------------------------------------------------------------

    def _parse_qty_boq(
        self, boq_el: etree._Element, doc: GAEBDocument,
    ) -> QtyBoQ:
        boq = QtyBoQ()
        boq.ref_boq_name = self._text(boq_el, "RefBoQName") or ""
        boq.ref_boq_id = self._text(boq_el, "RefBoQID") or ""

        for bkdn_el in self._findall(boq_el, "BoQBkdn"):
            bkdn = self._parse_bkdn(bkdn_el)
            if bkdn is not None:
                boq.bkdn.append(bkdn)

        for ctlg_el in self._findall(boq_el, "Ctlg"):
            boq.catalogs.append(self._parse_catalog(ctlg_el))

        body_el = self._find(boq_el, "BoQBody")
        if body_el is not None:
            boq.body = self._parse_qty_body(body_el, doc, [])

        for ca_el in self._findall(boq_el, "CtlgAssign"):
            boq.ctlg_assigns.append(self._parse_ctlg_assign(ca_el))

        att_container = self._find(boq_el, "CtlgAttachment")
        if att_container is not None:
            for att_el in self._findall(att_container, "Attachment"):
                att = self._parse_qty_attachment(att_el)
                if att is not None:
                    boq.attachments.append(att)

        if self._keep_xml:
            boq.source_element = boq_el

        return boq

    # ------------------------------------------------------------------
    # BoQBkdn
    # ------------------------------------------------------------------

    def _parse_bkdn(self, el: etree._Element) -> BoQBkdn | None:
        type_str = self._text(el, "Type") or ""
        length_str = self._text(el, "Length") or "0"

        type_map = {
            "Lot": BkdnType.LOT,
            "BoQLevel": BkdnType.BOQ_LEVEL,
            "Item": BkdnType.ITEM,
            "Index": BkdnType.INDEX,
        }
        bkdn_type = type_map.get(type_str)
        if bkdn_type is None:
            return None

        length = 0
        with contextlib.suppress(ValueError):
            length = int(length_str)

        return BoQBkdn(bkdn_type=bkdn_type, length=length)

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def _parse_catalog(self, el: etree._Element) -> Catalog:
        return Catalog(
            ctlg_id=self._text(el, "CtlgID") or "",
            ctlg_type=self._text(el, "CtlgType") or "",
            ctlg_name=self._text(el, "CtlgName") or "",
            assign_type=self._text(el, "CtlgAssignType") or "",
        )

    # ------------------------------------------------------------------
    # CtlgAssign
    # ------------------------------------------------------------------

    def _parse_ctlg_assign(self, el: etree._Element) -> CtlgAssign:
        return CtlgAssign(
            ctlg_id=self._text(el, "CtlgID") or "",
            ctlg_code=self._text(el, "CtlgCode") or "",
            quantity=_parse_decimal(self._text(el, "Quantity")),
        )

    # ------------------------------------------------------------------
    # BoQBody / BoQCtgy (QD-specific)
    # ------------------------------------------------------------------

    def _parse_qty_body(
        self,
        el: etree._Element,
        doc: GAEBDocument,
        hierarchy: list[str],
    ) -> QtyBoQBody:
        body = QtyBoQBody()

        for ctgy_el in self._findall(el, "BoQCtgy"):
            body.categories.append(
                self._parse_qty_ctgy(ctgy_el, doc, hierarchy),
            )

        itemlist_el = self._find(el, "Itemlist")
        if itemlist_el is not None:
            for item_el in self._findall(itemlist_el, "Item"):
                item = self._parse_qty_item(item_el, hierarchy)
                if item is not None:
                    body.categories.append(
                        QtyBoQCtgy(rno="", items=[item]),
                    )

        return body

    def _parse_qty_ctgy(
        self,
        el: etree._Element,
        doc: GAEBDocument,
        hierarchy: list[str],
    ) -> QtyBoQCtgy:
        ctgy = QtyBoQCtgy()
        ctgy.rno = el.get("RNoPart", "") or ""

        current_path = [*hierarchy, ctgy.rno]

        for ca_el in self._findall(el, "CtlgAssign"):
            ctgy.ctlg_assigns.append(self._parse_ctlg_assign(ca_el))

        body_el = self._find(el, "BoQBody")
        if body_el is not None:
            inner_body = self._parse_qty_body(body_el, doc, current_path)
            ctgy.subcategories = inner_body.categories

        itemlist_el = self._find(el, "Itemlist")
        if itemlist_el is not None:
            for item_el in self._findall(itemlist_el, "Item"):
                item = self._parse_qty_item(item_el, current_path)
                if item is not None:
                    ctgy.items.append(item)

        if self._keep_xml:
            ctgy.source_element = el

        return ctgy

    # ------------------------------------------------------------------
    # QtyItem
    # ------------------------------------------------------------------

    def _parse_qty_item(
        self,
        el: etree._Element,
        hierarchy: list[str],
    ) -> QtyItem | None:
        rno_part = el.get("RNoPart", "") or ""
        rno_index = el.get("RNoIndex", "") or ""

        oz_parts = [*hierarchy, rno_part]
        if rno_index:
            oz_parts.append(rno_index)
        oz = ".".join(p for p in oz_parts if p)

        item = QtyItem(oz=oz, rno_part=rno_part, rno_index=rno_index)

        qty_determ_el = self._find(el, "QtyDeterm")
        if qty_determ_el is not None:
            qty_str = self._text(qty_determ_el, "Qty")
            if qty_str:
                item.qty = _parse_decimal(qty_str)

            for qdi_el in self._findall(qty_determ_el, "QDetermItem"):
                item.determ_items.append(self._parse_q_determ_item(qdi_el))

        for ca_el in self._findall(el, "CtlgAssign"):
            item.ctlg_assigns.append(self._parse_ctlg_assign(ca_el))

        if self._keep_xml:
            item.source_element = el

        return item

    # ------------------------------------------------------------------
    # QDetermItem / QTakeoff
    # ------------------------------------------------------------------

    def _parse_q_determ_item(self, el: etree._Element) -> QDetermItem:
        di = QDetermItem()

        qtakeoff_el = self._find(el, "QTakeoff")
        if qtakeoff_el is not None:
            row_str = qtakeoff_el.get("Row", "") or ""
            di.takeoff_row = QTakeoffRow(raw=row_str)
            if self._keep_xml:
                di.takeoff_row.source_element = qtakeoff_el

        for ca_el in self._findall(el, "CtlgAssign"):
            di.ctlg_assigns.append(self._parse_ctlg_assign(ca_el))

        if self._keep_xml:
            di.source_element = el

        return di

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def _parse_qty_attachment(self, el: etree._Element) -> QtyAttachment | None:
        name = self._text(el, "Name") or ""
        text = self._text(el, "Text") or ""
        description = self._text(el, "Descrip") or ""
        file_type = self._text(el, "Type") or ""
        b64_data = self._text(el, "Data") or ""

        if not b64_data:
            return None

        try:
            data = base64.b64decode(b64_data)
        except Exception as e:
            logger.warning("Failed to decode X31 attachment %s: %s", name, e)
            return None

        return QtyAttachment(
            name=name,
            text=text,
            description=description,
            file_type=file_type,
            data=data,
        )


# ------------------------------------------------------------------
# Helpers
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
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(text.strip(), fmt)
    return None
