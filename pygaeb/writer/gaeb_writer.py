"""GAEBDocument → valid DA XML output for versions 2.0 through 3.3."""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lxml import etree

from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, BoQInfo
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import BkdnType, ExchangePhase, SourceVersion
from pygaeb.models.item import Item
from pygaeb.writer.version_registry import (
    VERSION_REGISTRY,
    WRITABLE_VERSIONS,
    VersionMeta,
)

logger = logging.getLogger("pygaeb.writer")


class GAEBWriter:
    """Write a GAEBDocument to a DA XML file.

    Usage::

        GAEBWriter.write(doc, "output.X84", phase=ExchangePhase.X84)
        GAEBWriter.write(doc, "legacy.D83", target_version=SourceVersion.DA_XML_20)
    """

    @staticmethod
    def write(
        doc: GAEBDocument,
        path: str | Path,
        phase: ExchangePhase | None = None,
        target_version: SourceVersion = SourceVersion.DA_XML_33,
        encoding: str = "utf-8",
    ) -> list[str]:
        """Serialize a GAEBDocument to a GAEB DA XML file.

        Args:
            doc: The document to serialize.
            path: Output file path.
            phase: Override exchange phase (default: keep original).
            target_version: Target DA XML version (default: 3.3).
            encoding: XML encoding declaration (default: utf-8).

        Returns:
            List of warnings about fields dropped for the target version.
        """
        if target_version not in WRITABLE_VERSIONS:
            supported = ", ".join(
                v.value for v in sorted(WRITABLE_VERSIONS, key=lambda v: v.value)
            )
            raise ValueError(
                f"Cannot write to {target_version.value}. Supported: {supported}"
            )

        path = Path(path)
        target_phase = phase or doc.exchange_phase
        meta = VERSION_REGISTRY[target_version]

        root, warnings = _build_xml(doc, target_phase, meta)

        if meta.lang == "de":
            raw = etree.tostring(
                root, xml_declaration=True, encoding=encoding, pretty_print=True,
            )
            raw_bytes: bytes = raw if isinstance(raw, bytes) else raw.encode(encoding)
            translated = _translate_to_german(raw_bytes.decode(encoding))
            path.write_text(translated, encoding=encoding)
        else:
            tree = etree.ElementTree(root)
            tree.write(
                str(path),
                xml_declaration=True,
                encoding=encoding,
                pretty_print=True,
            )

        logger.info(
            "Wrote %s (%d items, version %s)",
            path.name, doc.item_count, target_version.value,
        )
        return warnings

    @staticmethod
    def to_bytes(
        doc: GAEBDocument,
        phase: ExchangePhase | None = None,
        target_version: SourceVersion = SourceVersion.DA_XML_33,
        encoding: str = "utf-8",
    ) -> tuple[bytes, list[str]]:
        """Serialize a GAEBDocument to bytes.

        Returns:
            Tuple of (xml_bytes, warnings).
        """
        if target_version not in WRITABLE_VERSIONS:
            raise ValueError(f"Cannot write to {target_version.value}.")

        target_phase = phase or doc.exchange_phase
        meta = VERSION_REGISTRY[target_version]

        root, warnings = _build_xml(doc, target_phase, meta)
        raw = etree.tostring(
            root, xml_declaration=True, encoding=encoding, pretty_print=True,
        )
        xml_bytes: bytes = raw if isinstance(raw, bytes) else raw.encode(encoding)

        if meta.lang == "de":
            translated = _translate_to_german(xml_bytes.decode(encoding))
            return translated.encode(encoding), warnings

        return xml_bytes, warnings


def _build_xml(
    doc: GAEBDocument, phase: ExchangePhase, meta: VersionMeta,
) -> tuple[etree._Element, list[str]]:
    warnings: list[str] = []
    ns_map: dict[str | None, str] = {None: meta.namespace}
    root = etree.Element("GAEB", nsmap=ns_map)  # type: ignore[arg-type]
    root.set("xmlns", meta.namespace)

    _add_gaeb_info(root, doc.gaeb_info, meta)
    _add_award(root, doc.award, phase, meta, warnings)

    return root, warnings


def _add_gaeb_info(parent: etree._Element, info: GAEBInfo, meta: VersionMeta) -> None:
    gaeb_info = etree.SubElement(parent, "GAEBInfo")
    _add_text_el(gaeb_info, "Version", meta.version_tag)
    from pygaeb import __version__

    _add_text_el(gaeb_info, "ProgSystem", info.prog_system or "pyGAEB")
    _add_text_el(
        gaeb_info, "ProgSystemVersion", info.prog_system_version or __version__,
    )
    _add_text_el(gaeb_info, "Date", datetime.now().strftime("%Y-%m-%d"))


def _add_award(
    parent: etree._Element, award: AwardInfo, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
) -> None:
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

    _add_boq(award_el, award.boq, phase, meta, warnings)


def _add_boq(
    parent: etree._Element, boq: BoQ, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
) -> None:
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
            _add_body_categories(lot_body, lot.body, phase, meta, warnings)
        else:
            _add_body_categories(boq_body, lot.body, phase, meta, warnings)


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


def _add_body_categories(
    parent: etree._Element, body: BoQBody, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
) -> None:
    for ctgy in body.categories:
        _add_ctgy(parent, ctgy, phase, meta, warnings)


def _add_ctgy(
    parent: etree._Element, ctgy: BoQCtgy, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
) -> None:
    ctgy_el = etree.SubElement(parent, "BoQCtgy")
    if ctgy.rno:
        ctgy_el.set("RNoPart", ctgy.rno)
    if ctgy.label:
        _add_text_el(ctgy_el, "LblTx", ctgy.label)

    for sub in ctgy.subcategories:
        sub_body = etree.SubElement(ctgy_el, "BoQBody")
        _add_ctgy(sub_body, sub, phase, meta, warnings)

    if ctgy.items:
        itemlist = etree.SubElement(ctgy_el, "Itemlist")
        for item in ctgy.items:
            _add_item(itemlist, item, phase, meta, warnings)


def _add_item(
    parent: etree._Element, item: Item, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
) -> None:
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

    if item.long_text and item.long_text.raw_html and meta.supports_long_text_cdata:
        lt_el = etree.SubElement(item_el, "LongText")
        lt_el.text = etree.CDATA(item.long_text.raw_html)

    if item.bim_guid:
        if meta.supports_bim_guid:
            _add_text_el(item_el, "GUID", item.bim_guid)
        else:
            warnings.append(
                f"Item {item.oz}: bim_guid dropped (not supported in DA XML {meta.version_tag})"
            )

    if item.change_order_number:
        if meta.supports_change_order:
            _add_text_el(item_el, "CONo", item.change_order_number)
        else:
            warnings.append(
                f"Item {item.oz}: change_order_number dropped "
                f"(not supported in DA XML {meta.version_tag})"
            )

    if item.attachments:
        if meta.supports_attachments:
            for attachment in item.attachments:
                attach_el = etree.SubElement(item_el, "Attachment")
                _add_text_el(attach_el, "Filename", attachment.filename)
                _add_text_el(attach_el, "MimeType", attachment.mime_type)
                _add_text_el(
                    attach_el, "Data",
                    base64.b64encode(attachment.data).decode("ascii"),
                )
        else:
            warnings.append(
                f"Item {item.oz}: {len(item.attachments)} attachment(s) dropped "
                f"(not supported in DA XML {meta.version_tag})"
            )


def _translate_to_german(xml_text: str) -> str:
    """Translate English DA XML 3.x element names to German DA XML 2.x equivalents."""
    from pygaeb.parser.xml_v2.german_element_map import ENGLISH_TO_GERMAN

    def _replace_tag(match: re.Match[str]) -> str:
        slash = match.group(1) or ""
        tag_name = match.group(2)
        rest = match.group(3) or ""
        german = ENGLISH_TO_GERMAN.get(tag_name, tag_name)
        return f"<{slash}{german}{rest}>"

    return re.sub(r"<(/?)(\w+)((?:\s[^>]*)?)>", _replace_tag, xml_text)


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
