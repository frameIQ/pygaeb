"""GAEBDocument → valid DA XML 3.x output. GAEBInfo is auto-regenerated on write."""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lxml import etree

from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, BoQInfo
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import BkdnType, ExchangePhase
from pygaeb.models.item import Item

logger = logging.getLogger("pygaeb.writer")

_GAEB_NS = "http://www.gaeb.de/GAEB_DA_XML/DA86/3.3"
_NS_MAP = {None: _GAEB_NS}


class GAEBWriter:
    """Write a GAEBDocument to a DA XML file.

    Usage:
        GAEBWriter.write(doc, "output.X84", phase=ExchangePhase.X84)
    """

    @staticmethod
    def write(
        doc: GAEBDocument,
        path: str | Path,
        phase: ExchangePhase | None = None,
        encoding: str = "utf-8",
    ) -> None:
        """Serialize a GAEBDocument to a GAEB DA XML file."""
        path = Path(path)
        target_phase = phase or doc.exchange_phase

        root = _build_xml(doc, target_phase)

        tree = etree.ElementTree(root)
        tree.write(
            str(path),
            xml_declaration=True,
            encoding=encoding,
            pretty_print=True,
        )
        logger.info("Wrote %s (%d items)", path.name, doc.item_count)


def _build_xml(doc: GAEBDocument, phase: ExchangePhase) -> etree._Element:
    root = etree.Element("GAEB", nsmap=_NS_MAP)
    root.set("xmlns", _GAEB_NS)

    _add_gaeb_info(root, doc.gaeb_info)
    _add_award(root, doc.award, phase)

    return root


def _add_gaeb_info(parent: etree._Element, info: GAEBInfo) -> None:
    gaeb_info = etree.SubElement(parent, "GAEBInfo")
    _add_text_el(gaeb_info, "Version", "3.3")
    from pygaeb import __version__
    _add_text_el(gaeb_info, "ProgSystem", info.prog_system or "pyGAEB")
    _add_text_el(gaeb_info, "ProgSystemVersion", info.prog_system_version or __version__)
    _add_text_el(gaeb_info, "Date", datetime.now().strftime("%Y-%m-%d"))


def _add_award(parent: etree._Element, award: AwardInfo, phase: ExchangePhase) -> None:
    award_el = etree.SubElement(parent, "Award")

    award_info_el = etree.SubElement(award_el, "AwardInfo")
    if award.project_no:
        _add_text_el(award_info_el, "Prj", award.project_no)
    if award.project_name:
        _add_text_el(award_info_el, "PrjName", award.project_name)
    if award.client:
        _add_text_el(award_info_el, "OWN", award.client)
    _add_text_el(award_info_el, "Cur", award.currency)
    if award.procurement_type:
        _add_text_el(award_info_el, "PrcTyp", award.procurement_type)

    _add_boq(award_el, award.boq, phase)


def _add_boq(parent: etree._Element, boq: BoQ, phase: ExchangePhase) -> None:
    boq_el = etree.SubElement(parent, "BoQ")

    if boq.boq_info:
        _add_boq_info(boq_el, boq.boq_info)

    boq_body = etree.SubElement(boq_el, "BoQBody")

    for lot in boq.lots:
        if boq.is_multi_lot:
            lot_ctgy = etree.SubElement(boq_body, "BoQCtgy")
            lot_ctgy.set("RNoPart", lot.rno)
            _add_text_el(lot_ctgy, "LblTx", lot.label)
            lot_body = etree.SubElement(lot_ctgy, "BoQBody")
            _add_body_categories(lot_body, lot.body, phase)
        else:
            _add_body_categories(boq_body, lot.body, phase)


def _add_boq_info(parent: etree._Element, info: BoQInfo) -> None:
    info_el = etree.SubElement(parent, "BoQInfo")
    if info.name:
        _add_text_el(info_el, "Name", info.name)
    if info.lbl_boq:
        _add_text_el(info_el, "LblBoQ", info.lbl_boq)

    if info.bkdn:
        bkdn_el = etree.SubElement(info_el, "BoQBkdn")
        for level in info.bkdn:
            tag = _bkdn_tag(level.bkdn_type)
            level_el = etree.SubElement(bkdn_el, tag)
            level_el.set("Length", str(level.length))


def _add_body_categories(parent: etree._Element, body: BoQBody, phase: ExchangePhase) -> None:
    for ctgy in body.categories:
        _add_ctgy(parent, ctgy, phase)


def _add_ctgy(parent: etree._Element, ctgy: BoQCtgy, phase: ExchangePhase) -> None:
    ctgy_el = etree.SubElement(parent, "BoQCtgy")
    if ctgy.rno:
        ctgy_el.set("RNoPart", ctgy.rno)
    if ctgy.label:
        _add_text_el(ctgy_el, "LblTx", ctgy.label)

    for sub in ctgy.subcategories:
        sub_body = etree.SubElement(ctgy_el, "BoQBody")
        _add_ctgy(sub_body, sub, phase)

    if ctgy.items:
        itemlist = etree.SubElement(ctgy_el, "Itemlist")
        for item in ctgy.items:
            _add_item(itemlist, item, phase)


def _add_item(parent: etree._Element, item: Item, phase: ExchangePhase) -> None:
    item_el = etree.SubElement(parent, "Item")
    item_el.set("RNoPart", item.oz)

    if item.short_text:
        _add_text_el(item_el, "ShortText", item.short_text)

    if item.qty is not None:
        _add_text_el(item_el, "Qty", _fmt_decimal(item.qty))

    if item.unit:
        _add_text_el(item_el, "QU", item.unit)

    if item.unit_price is not None:
        _add_text_el(item_el, "UP", _fmt_decimal(item.unit_price))

    if item.total_price is not None:
        _add_text_el(item_el, "IT", _fmt_decimal(item.total_price))

    if item.long_text and item.long_text.raw_html:
        lt_el = etree.SubElement(item_el, "LongText")
        lt_el.text = etree.CDATA(item.long_text.raw_html)

    if item.bim_guid:
        _add_text_el(item_el, "GUID", item.bim_guid)

    if item.change_order_number:
        _add_text_el(item_el, "CONo", item.change_order_number)

    for attachment in item.attachments:
        attach_el = etree.SubElement(item_el, "Attachment")
        _add_text_el(attach_el, "Filename", attachment.filename)
        _add_text_el(attach_el, "MimeType", attachment.mime_type)
        _add_text_el(attach_el, "Data", base64.b64encode(attachment.data).decode("ascii"))


def _add_text_el(parent: etree._Element, tag: str, text: str) -> None:
    el = etree.SubElement(parent, tag)
    el.text = text


def _fmt_decimal(value: Decimal) -> str:
    return str(value)


def _bkdn_tag(bkdn_type: BkdnType) -> str:
    return {
        BkdnType.LOT: "Lot",
        BkdnType.BOQ_LEVEL: "BoQLevel",
        BkdnType.ITEM: "Item",
        BkdnType.INDEX: "Index",
    }.get(bkdn_type, "BoQLevel")
