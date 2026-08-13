"""GAEBDocument → valid DA XML output for versions 2.0 through 3.3."""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from lxml import etree

from pygaeb.models.boq import BoQ, BoQBkdn, BoQBody, BoQCtgy, BoQInfo, Totals
from pygaeb.models.catalog import Catalog, CtlgAssign
from pygaeb.models.cost import (
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
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import BkdnType, ExchangePhase, ItemType, SourceVersion
from pygaeb.models.item import CostApproach, Item, RichText
from pygaeb.models.order import OrderItem, TradeOrder
from pygaeb.models.position_types import NON_INTEROP_TYPES, WRITER_MARKER
from pygaeb.models.quantity import (
    QDetermItem,
    QtyAttachment,
    QtyBoQ,
    QtyBoQBody,
    QtyBoQCtgy,
    QtyDetermination,
    QtyDetermInfo,
    QtyItem,
)
from pygaeb.writer.version_registry import (
    VERSION_REGISTRY,
    WRITABLE_VERSIONS,
    VersionMeta,
    cost_namespace,
    procurement_namespace,
    qty_namespace,
    trade_namespace,
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

    # NOTE: the default namespace is written as a literal ``xmlns`` attribute
    # (not via ``nsmap``): passing both used to emit the declaration twice,
    # producing malformed XML that strict parsers reject.
    if doc.is_quantity and doc.qty_determination is not None:
        ns = qty_namespace(phase, SourceVersion(meta.version_tag))
        root = etree.Element("GAEB")
        root.set("xmlns", ns)
        _add_gaeb_info(root, doc.gaeb_info, meta)
        _add_qty_determination(root, doc.qty_determination, warnings)
        return root, warnings

    if doc.is_cost and doc.elemental_costing is not None:
        ns = cost_namespace(phase, SourceVersion(meta.version_tag))
        root = etree.Element("GAEB")
        root.set("xmlns", ns)
        _add_gaeb_info(root, doc.gaeb_info, meta)
        _add_elemental_costing(root, doc.elemental_costing, warnings)
        return root, warnings

    if doc.is_trade and doc.order is not None:
        ns = trade_namespace(phase, SourceVersion(meta.version_tag))
        root = etree.Element("GAEB")
        root.set("xmlns", ns)
        _add_gaeb_info(root, doc.gaeb_info, meta)
        _add_order(root, doc.order, phase, warnings)
        return root, warnings

    ns = procurement_namespace(phase, SourceVersion(meta.version_tag))
    root = etree.Element("GAEB")
    root.set("xmlns", ns)

    _add_gaeb_info(root, doc.gaeb_info, meta)
    _add_prj_info(root, doc.award)
    _add_award(root, doc.award, phase, meta, warnings)

    return root, warnings


def _add_gaeb_info(parent: etree._Element, info: GAEBInfo, meta: VersionMeta) -> None:
    gaeb_info = etree.SubElement(parent, "GAEBInfo")
    _add_text_el(gaeb_info, "Version", meta.version_tag)
    if info.vers_date:
        _add_text_el(gaeb_info, "VersDate", info.vers_date)
    from pygaeb import __version__

    _add_text_el(gaeb_info, "ProgSystem", info.prog_system or "pyGAEB")
    _add_text_el(
        gaeb_info, "ProgSystemVersion", info.prog_system_version or __version__,
    )
    if info.prog_name:
        _add_text_el(gaeb_info, "ProgName", info.prog_name)
    # Keep the source's document date; only stamp today when there was none.
    date = info.date.strftime("%Y-%m-%d") if info.date else datetime.now().strftime("%Y-%m-%d")
    _add_text_el(gaeb_info, "Date", date)
    if info.time:
        _add_text_el(gaeb_info, "Time", info.time)


def _add_prj_info(parent: etree._Element, award: AwardInfo) -> None:
    """Serialize PrjInfo fields from ``AwardInfo`` into a ``<PrjInfo>`` element."""
    has_prj_data = any([
        award.prj_id, award.lbl_prj, award.description,
        award.currency_label, award.bid_comm_perm, award.alter_bid_perm,
        award.up_frac_dig is not None, award.ctlg_assigns,
    ])
    if not has_prj_data:
        return

    prj_el = etree.SubElement(parent, "PrjInfo")
    if award.project_name:
        _add_text_el(prj_el, "NamePrj", award.project_name)
    if award.prj_id:
        _add_text_el(prj_el, "PrjID", award.prj_id)
    if award.lbl_prj:
        _add_text_el(prj_el, "LblPrj", award.lbl_prj)
    if award.description:
        _add_text_el(prj_el, "Descrip", award.description)
    if award.currency:
        _add_text_el(prj_el, "Cur", award.currency)
    if award.currency_label:
        _add_text_el(prj_el, "CurLbl", award.currency_label)
    if award.bid_comm_perm:
        _add_text_el(prj_el, "BidCommPerm", "Yes")
    if award.alter_bid_perm:
        _add_text_el(prj_el, "AlterBidPerm", "Yes")
    if award.up_frac_dig is not None:
        _add_text_el(prj_el, "UPFracDig", str(award.up_frac_dig))
    for ca in award.ctlg_assigns:
        _add_ctlg_assign(prj_el, ca)


def _add_award(
    parent: etree._Element, award: AwardInfo, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
) -> None:
    award_el = etree.SubElement(parent, "Award")
    # Exchange-phase marker, as the trade/cost/QD writers already emit.
    _add_text_el(award_el, "DP", phase.value.lstrip("X"))

    award_info_el = etree.SubElement(award_el, "AwardInfo")
    if award.project_no:
        _add_text_el(award_info_el, "Prj", award.project_no)
    if award.project_name:
        _add_text_el(award_info_el, "PrjName", award.project_name)
    _add_text_el(award_info_el, "Cur", award.currency)
    if award.currency_label:
        _add_text_el(award_info_el, "CurLbl", award.currency_label)
    if award.boq_id:
        _add_text_el(award_info_el, "BoQID", award.boq_id)
    if award.procurement_type:
        _add_text_el(award_info_el, "PrcTyp", award.procurement_type)
    if award.category:
        _add_text_el(award_info_el, "Cat", award.category)
    if award.open_date:
        _add_text_el(award_info_el, "OpenDate", award.open_date.strftime("%Y-%m-%d"))
    if award.open_time:
        _add_text_el(award_info_el, "OpenTime", award.open_time)
    if award.eval_end:
        _add_text_el(award_info_el, "EvalEnd", award.eval_end.strftime("%Y-%m-%d"))
    if award.submit_location:
        _add_text_el(award_info_el, "SubmLoc", award.submit_location)
    if award.construction_start:
        _add_text_el(award_info_el, "CnstStart", award.construction_start.strftime("%Y-%m-%d"))
    if award.construction_end:
        _add_text_el(award_info_el, "CnstEnd", award.construction_end.strftime("%Y-%m-%d"))
    if award.contract_no:
        _add_text_el(award_info_el, "ContrNo", award.contract_no)
    if award.contract_date:
        _add_text_el(award_info_el, "ContrDate", award.contract_date.strftime("%Y-%m-%d"))
    if award.accept_type:
        _add_text_el(award_info_el, "AcceptType", award.accept_type)
    if award.warranty_duration is not None:
        _add_text_el(award_info_el, "WarrDur", str(award.warranty_duration))
    if award.warranty_unit:
        _add_text_el(award_info_el, "WarrUnit", award.warranty_unit)

    if award.owner_address or award.award_no:
        own_el = etree.SubElement(award_el, "OWN")
        _add_address(own_el, award.owner_address)
        if award.award_no:
            _add_text_el(own_el, "AwardNo", award.award_no)
    elif award.client:
        _add_text_el(award_info_el, "OWN", award.client)

    _add_boq(award_el, award.boq, phase, meta, warnings, award.up_frac_dig)


def _add_boq(
    parent: etree._Element, boq: BoQ, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
    up_frac_dig: int | None = None,
) -> None:
    boq_el = etree.SubElement(parent, "BoQ")

    if boq.boq_info:
        _add_boq_info(boq_el, boq.boq_info, meta)

    boq_body = etree.SubElement(boq_el, "BoQBody")

    for lot in boq.lots:
        if boq.is_multi_lot:
            lot_ctgy = etree.SubElement(boq_body, "BoQCtgy")
            lot_ctgy.set("RNoPart", lot.rno)
            _add_text_el(lot_ctgy, "LblTx", lot.label)
            if lot.totals is not None:
                _add_totals(lot_ctgy, lot.totals)
            lot_body = etree.SubElement(lot_ctgy, "BoQBody")
            _add_body_categories(lot_body, lot.body, phase, meta, warnings, up_frac_dig)
        else:
            _add_body_categories(boq_body, lot.body, phase, meta, warnings, up_frac_dig)


def _add_bkdn(
    parent: etree._Element, bkdn: list[BoQBkdn], meta: VersionMeta,
) -> None:
    """Emit the BoQ breakdown in the form the target version expects."""
    if not bkdn:
        return

    if meta.bkdn_sibling_form:
        for level in bkdn:
            bkdn_el = etree.SubElement(parent, "BoQBkdn")
            _add_text_el(bkdn_el, "Type", _bkdn_tag(level.bkdn_type))
            _add_text_el(bkdn_el, "Length", str(level.length))
            if level.num:
                _add_text_el(bkdn_el, "Num", "Yes")
        return

    bkdn_el = etree.SubElement(parent, "BoQBkdn")
    for level in bkdn:
        level_el = etree.SubElement(bkdn_el, _bkdn_tag(level.bkdn_type))
        level_el.set("Length", str(level.length))
        if level.num:
            level_el.set("Num", "Yes")


def _add_boq_info(
    parent: etree._Element, info: BoQInfo, meta: VersionMeta,
) -> None:
    info_el = etree.SubElement(parent, "BoQInfo")
    if info.name:
        _add_text_el(info_el, "Name", info.name)
    if info.lbl_boq:
        _add_text_el(info_el, "LblBoQ", info.lbl_boq)
    if info.date:
        _add_text_el(info_el, "Date", info.date)

    _add_bkdn(info_el, info.bkdn, meta)

    if info.no_up_comps is not None:
        _add_text_el(info_el, "NoUPComps", str(info.no_up_comps))
    for idx, label in enumerate(info.lbl_up_comps, start=1):
        _add_text_el(info_el, f"LblUPComp{idx}", label)
    if info.lbl_time:
        _add_text_el(info_el, "LblTime", info.lbl_time)

    _add_boq_info_cost_types(info_el, info)

    for ca in info.ctlg_assigns:
        _add_ctlg_assign(info_el, ca)

    if info.totals is not None:
        _add_totals(info_el, info.totals)


def _add_body_categories(
    parent: etree._Element, body: BoQBody, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
    up_frac_dig: int | None = None,
) -> None:
    for ctgy in body.categories:
        # An anonymous, childless category is the wrapper the parser puts around
        # items that sat straight under BoQBody — write them back out bare rather
        # than inventing a category level the source never had.
        if not ctgy.rno and not ctgy.label and not ctgy.subcategories:
            _add_itemlist(parent, ctgy.items, phase, meta, warnings, up_frac_dig)
        else:
            _add_ctgy(parent, ctgy, phase, meta, warnings, up_frac_dig)


def _add_itemlist(
    parent: etree._Element, items: list[Item], phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
    up_frac_dig: int | None = None,
) -> None:
    if not items:
        return
    itemlist = etree.SubElement(parent, "Itemlist")
    for item in items:
        if item.item_type == ItemType.MARKUP:
            _add_markup_item(itemlist, item)
        else:
            _add_item(itemlist, item, phase, meta, warnings, up_frac_dig)


def _add_ctgy(
    parent: etree._Element, ctgy: BoQCtgy, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
    up_frac_dig: int | None = None,
) -> None:
    ctgy_el = etree.SubElement(parent, "BoQCtgy")
    if ctgy.rno:
        ctgy_el.set("RNoPart", ctgy.rno)
    if ctgy.label:
        _add_text_el(ctgy_el, "LblTx", ctgy.label)

    for ca in ctgy.ctlg_assigns:
        _add_ctlg_assign(ctgy_el, ca)

    if ctgy.totals is not None:
        _add_totals(ctgy_el, ctgy.totals)

    # GAEB schema: a BoQCtgy holds exactly ONE BoQBody, which contains the
    # sub-BoQCtgy elements and/or the Itemlist. A body per subcategory used
    # to be written here — parsers then read only the first one back.
    if ctgy.subcategories or ctgy.items:
        body_el = etree.SubElement(ctgy_el, "BoQBody")
        for sub in ctgy.subcategories:
            _add_ctgy(body_el, sub, phase, meta, warnings, up_frac_dig)
        _add_itemlist(body_el, ctgy.items, phase, meta, warnings, up_frac_dig)


def _copy_stripped(src: etree._Element, parent: etree._Element) -> None:
    """Copy an element tree over, dropping namespaces.

    The writer declares its namespace as a literal ``xmlns`` attribute on the root
    and builds every element bare, so re-embedded source markup must arrive bare
    too — otherwise the target document carries the source document's namespace.
    """
    el = etree.SubElement(parent, etree.QName(src).localname)
    for key, value in src.attrib.items():
        el.set(etree.QName(key).localname if "}" in key else key, value)
    el.text = src.text
    el.tail = src.tail
    for child in src:
        if callable(child.tag):  # comments / processing instructions
            continue
        _copy_stripped(child, el)


def _add_richtext(parent: etree._Element, text: RichText) -> bool:
    """Fill ``parent`` with the long text's markup. False when there was nothing."""
    inner = text.raw_html
    if inner and inner.strip():
        try:
            frag = etree.fromstring(f"<w>{inner}</w>")
        except etree.XMLSyntaxError:
            frag = None
        # Bare text (a 2.x long text) has no markup to carry over — fall through
        # so it gets a conforming <Text><p> wrapper instead of sitting loose.
        if frag is not None and len(frag):
            parent.text = frag.text
            for child in frag:
                if not callable(child.tag):
                    _copy_stripped(child, parent)
            return True

    paragraphs = text.paragraphs or (
        [text.plain_text] if text.plain_text else []
    )
    if not paragraphs:
        return False

    text_el = etree.SubElement(parent, "Text")
    for para in paragraphs:
        p_el = etree.SubElement(text_el, "p")
        span_el = etree.SubElement(p_el, "span")
        span_el.text = para
    return True


def _add_item_text(
    parent: etree._Element, item: Item, meta: VersionMeta,
) -> None:
    """Write short and long text in the shape the target version expects.

    DA XML 3.x carries both inside ``<Description>``; 2.x uses flat
    ``ShortText``/``LongText``, which ``_translate_to_german`` renames.
    """
    if meta.lang == "de":
        if item.long_text and meta.supports_long_text_cdata:
            inner = item.long_text.raw_html or item.long_text.plain_text or "\n".join(
                item.long_text.paragraphs
            )
            if inner:
                lt_el = etree.SubElement(parent, "LongText")
                lt_el.text = etree.CDATA(inner)
        return

    if not item.short_text and not item.long_text:
        return

    complete_el = etree.SubElement(
        etree.SubElement(parent, "Description"), "CompleteText",
    )

    if item.long_text is not None:
        detail_el = etree.SubElement(complete_el, "DetailTxt")
        if not _add_richtext(detail_el, item.long_text):
            complete_el.remove(detail_el)

    if item.short_text:
        outl_txt = etree.SubElement(
            etree.SubElement(complete_el, "OutlineText"), "OutlTxt",
        )
        span_el = etree.SubElement(
            etree.SubElement(outl_txt, "TextOutlTxt"), "span",
        )
        span_el.text = item.short_text


def _add_item(
    parent: etree._Element, item: Item, phase: ExchangePhase,
    meta: VersionMeta, warnings: list[str],
    up_frac_dig: int | None = None,
) -> None:
    item_el = etree.SubElement(parent, "Item")
    item_el.set("RNoPart", item.oz)

    # Position type (Bedarfs-/Alternativ-/Pauschalposition …). MARKUP is handled by
    # the _add_markup_item branch; NORMAL carries no marker. Emitting the marker keeps
    # the "priced but not summed" rule intact on re-read — without it every non-Normal
    # position silently becomes Normal and its price joins the total.
    marker = WRITER_MARKER.get(item.item_type)
    if marker is not None:
        etree.SubElement(item_el, marker)
        if item.item_type in NON_INTEROP_TYPES:
            warnings.append(
                f"Item {item.oz}: {item.item_type.value} written as pyGAEB-internal "
                f"<{marker}> — round-trips within pyGAEB but is not read by other AVA "
                f"software yet (real GAEB serialization not implemented)"
            )

    if item.short_text and meta.lang == "de":
        _add_text_el(item_el, "ShortText", item.short_text)

    if item.qty_tbd:
        _add_text_el(item_el, "QtyTBD", "Yes")

    if item.qty is not None:
        _add_text_el(item_el, "Qty", _fmt_decimal(item.qty))

    if item.unit:
        _add_text_el(item_el, "QU", item.unit)

    if item.unit_price is not None:
        _add_text_el(item_el, "UP", _fmt_decimal(item.unit_price, up_frac_dig))

    if item.total_price is not None:
        _add_text_el(item_el, "IT", _fmt_decimal(item.total_price))

    # Partial-quantity breakdown (Zuordnung der Teilmengen). Symmetric with the
    # parser's _parse_qty_splits (reads Label/Description, Qty, QU).
    for split in item.qty_splits:
        qs_el = etree.SubElement(item_el, "QtySplit")
        if split.label:
            _add_text_el(qs_el, "Label", split.label)
        if split.qty is not None:
            _add_text_el(qs_el, "Qty", _fmt_decimal(split.qty))
        if split.unit:
            _add_text_el(qs_el, "QU", split.unit)

    _add_item_text(item_el, item, meta)

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

    for ca in item.cost_approaches:
        _add_cost_approach(item_el, ca)

    for i, comp in enumerate(item.up_components, 1):
        _add_text_el(item_el, f"UPComp{i}", _fmt_decimal(comp))

    if item.discount_pct is not None:
        _add_text_el(item_el, "DiscountPcnt", _fmt_decimal(item.discount_pct))

    if item.vat is not None:
        _add_text_el(item_el, "VAT", _fmt_decimal(item.vat))

    for bp in item.bidder_prices:
        bp_el = etree.SubElement(item_el, "BidderUP")
        if bp.bidder_name:
            _add_text_el(bp_el, "BidderName", bp.bidder_name)
        if bp.bidder_id:
            _add_text_el(bp_el, "BidderID", bp.bidder_id)
        if bp.unit_price is not None:
            _add_text_el(bp_el, "UP", _fmt_decimal(bp.unit_price, up_frac_dig))
        if bp.total_price is not None:
            _add_text_el(bp_el, "IT", _fmt_decimal(bp.total_price))

    for ctlg in item.ctlg_assigns:
        _add_ctlg_assign(item_el, ctlg)


def _add_markup_item(parent: etree._Element, item: Item) -> None:
    """Serialize a markup item as ``<MarkupItem>`` (X52)."""
    mu_el = etree.SubElement(parent, "MarkupItem")
    mu_el.set("RNoPart", item.oz)

    if item.short_text:
        _add_text_el(mu_el, "ShortText", item.short_text)

    if item.markup_type:
        _add_text_el(mu_el, "MarkupType", item.markup_type)

    if item.unit_price is not None:
        _add_text_el(mu_el, "Markup", _fmt_decimal(item.unit_price))

    if item.total_price is not None:
        _add_text_el(mu_el, "ITMarkup", _fmt_decimal(item.total_price))

    if item.discount_pct is not None:
        _add_text_el(mu_el, "DiscountPcnt", _fmt_decimal(item.discount_pct))

    for sub in item.markup_sub_qtys:
        sub_el = etree.SubElement(mu_el, "MarkupSubQty")
        if sub.ref_rno:
            _add_text_el(sub_el, "RefRNoPart", sub.ref_rno)
        if sub.sub_qty is not None:
            _add_text_el(sub_el, "SubQty", _fmt_decimal(sub.sub_qty))

    for ca in item.ctlg_assigns:
        _add_ctlg_assign(mu_el, ca)


def _add_order(
    parent: etree._Element, order: TradeOrder,
    phase: ExchangePhase, warnings: list[str],
) -> None:
    """Serialize a TradeOrder to <Order> XML."""
    order_el = etree.SubElement(parent, "Order")

    _add_text_el(order_el, "DP", order.dp or phase.value.lstrip("X"))

    if order.order_info:
        oi_el = etree.SubElement(order_el, "OrderInfo")
        if order.order_info.order_no:
            _add_text_el(oi_el, "OrderNo", order.order_info.order_no)
        if order.order_info.currency:
            _add_text_el(oi_el, "Cur", order.order_info.currency)
        if order.order_info.order_date:
            _add_text_el(oi_el, "OrderDate", order.order_info.order_date.strftime("%Y-%m-%d"))
        if order.order_info.delivery_date:
            _add_text_el(oi_el, "DeliveryDate", order.order_info.delivery_date.strftime("%Y-%m-%d"))
        for ctlg in order.order_info.ctlg_assigns:
            _add_ctlg_assign(oi_el, ctlg)

    for info_name, tag_name in [
        ("supplier_info", "SupplierInfo"),
        ("customer_info", "CustomerInfo"),
        ("delivery_place_info", "DeliveryPlaceInfo"),
        ("planner_info", "PlannerInfo"),
        ("invoice_info", "InvoiceInfo"),
    ]:
        info_obj = getattr(order, info_name, None)
        if info_obj is not None:
            info_el = etree.SubElement(order_el, tag_name)
            _add_address(info_el, info_obj.address)

    for item in order.items:
        _add_order_item(order_el, item, warnings)

    for ctlg in order.ctlg_assigns:
        _add_ctlg_assign(order_el, ctlg)


def _add_address(parent: etree._Element, addr: Any) -> None:
    if addr is None:
        return
    addr_el = etree.SubElement(parent, "Address")
    for field_name, tag_name in [
        ("name", "Name1"), ("name2", "Name2"), ("name3", "Name3"), ("name4", "Name4"),
        ("street", "Street"), ("pcode", "PCode"), ("city", "City"), ("country", "Country"),
        ("contact", "Contact"), ("phone", "Phone"), ("fax", "Fax"), ("email", "EMail"),
        ("iln", "ILN"), ("vat_id", "VATID"),
    ]:
        val = getattr(addr, field_name, None)
        if val:
            _add_text_el(addr_el, tag_name, val)


def _add_order_item(
    parent: etree._Element, item: OrderItem, warnings: list[str],
) -> None:
    item_el = etree.SubElement(parent, "OrderItem")

    if item.ean:
        _add_text_el(item_el, "EAN", item.ean)
    if item.art_no_id:
        _add_text_el(item_el, "ArtNoID", item.art_no_id)
    if item.art_no:
        _add_text_el(item_el, "ArtNo", item.art_no)
    if item.supplier_art_no_id:
        _add_text_el(item_el, "SupplierArtNoID", item.supplier_art_no_id)
    if item.supplier_art_no:
        _add_text_el(item_el, "SupplierArtNo", item.supplier_art_no)
    if item.customer_art_no:
        _add_text_el(item_el, "CustomerArtNo", item.customer_art_no)
    if item.catalog_art_no:
        _add_text_el(item_el, "CatalogArtNo", item.catalog_art_no)
    if item.catalog_no:
        _add_text_el(item_el, "CatalogNo", item.catalog_no)

    if item.qty is not None:
        _add_text_el(item_el, "Qty", _fmt_decimal(item.qty))
    if item.unit:
        _add_text_el(item_el, "QU", item.unit)

    if item.short_text:
        desc_el = etree.SubElement(item_el, "Description")
        ct_el = etree.SubElement(desc_el, "CompleteText")
        ol_el = etree.SubElement(ct_el, "OutlineText")
        otl_el = etree.SubElement(ol_el, "OutlTxt")
        txt_el = etree.SubElement(otl_el, "TextOutlTxt")
        txt_el.text = item.short_text

    if item.offer_price is not None:
        _add_text_el(item_el, "OfferPrice", _fmt_decimal(item.offer_price))
    if item.net_price is not None:
        _add_text_el(item_el, "NetPrice", _fmt_decimal(item.net_price))
    if item.price_basis is not None:
        _add_text_el(item_el, "PriceBasis", _fmt_decimal(item.price_basis))
    if item.aqu:
        _add_text_el(item_el, "AQU", item.aqu)

    if item.mode_of_shipment:
        _add_text_el(item_el, "ModeOfShipment", item.mode_of_shipment)
    if item.delivery_date:
        _add_text_el(item_el, "DeliveryDate", item.delivery_date.strftime("%Y-%m-%d"))

    for ctlg in item.ctlg_assigns:
        _add_ctlg_assign(item_el, ctlg)


def _add_cost_approach(parent: etree._Element, ca: CostApproach) -> None:
    ca_el = etree.SubElement(parent, "CostApproach")
    if ca.cost_type:
        _add_text_el(ca_el, "CostType", ca.cost_type)
    if ca.amount is not None:
        _add_text_el(ca_el, "Amount", _fmt_decimal(ca.amount))
    if ca.remark:
        _add_text_el(ca_el, "Remark", ca.remark)


def _add_boq_info_cost_types(parent: etree._Element, info: BoQInfo) -> None:
    for ct in info.cost_types:
        ct_el = etree.SubElement(parent, "CostType")
        if ct.name:
            _add_text_el(ct_el, "Name", ct.name)
        if ct.label:
            _add_text_el(ct_el, "Label", ct.label)


def _add_totals(parent: etree._Element, totals: Totals) -> None:
    """Serialize a ``Totals`` model to a ``<Totals>`` XML element."""
    t_el = etree.SubElement(parent, "Totals")

    if totals.total is not None:
        _add_text_el(t_el, "Total", _fmt_decimal(totals.total))

    if totals.discount_pcnt is not None:
        _add_text_el(t_el, "DiscountPcnt", _fmt_decimal(totals.discount_pcnt))
    if totals.discount_amt is not None:
        _add_text_el(t_el, "DiscountAmt", _fmt_decimal(totals.discount_amt))
    if totals.tot_after_disc is not None:
        _add_text_el(t_el, "TotAfterDisc", _fmt_decimal(totals.tot_after_disc))

    if totals.total_lsum is not None:
        _add_text_el(t_el, "TotalLSUM", _fmt_decimal(totals.total_lsum))

    if totals.vat is not None:
        _add_text_el(t_el, "VAT", _fmt_decimal(totals.vat))

    if totals.total_net is not None:
        _add_text_el(t_el, "TotalNet", _fmt_decimal(totals.total_net))

    if totals.total_net_up_comp:
        uc_el = etree.SubElement(t_el, "TotalNetUpComp")
        for i, comp in enumerate(totals.total_net_up_comp, 1):
            _add_text_el(uc_el, f"UpComp{i}", _fmt_decimal(comp))

    for vp in totals.vat_parts:
        vp_el = etree.SubElement(t_el, "VATPart")
        vp_el.set("VATPcnt", _fmt_decimal(vp.vat_pcnt))
        if vp.total_net_part is not None:
            _add_text_el(vp_el, "TotalNetPart", _fmt_decimal(vp.total_net_part))
        if vp.vat_amount is not None:
            _add_text_el(vp_el, "VATAmount", _fmt_decimal(vp.vat_amount))

    if totals.vat_amount is not None:
        _add_text_el(t_el, "VATAmount", _fmt_decimal(totals.vat_amount))

    if totals.total_gross is not None:
        _add_text_el(t_el, "TotalGross", _fmt_decimal(totals.total_gross))


# ------------------------------------------------------------------
# Elemental Costing (X50/X51) serialization
# ------------------------------------------------------------------


def _add_elemental_costing(
    parent: etree._Element, ec: ElementalCosting, warnings: list[str],
) -> None:
    ec_el = etree.SubElement(parent, "ElementalCosting")
    if ec.dp:
        _add_text_el(ec_el, "DP", ec.dp)

    _add_ec_info(ec_el, ec.ec_info)
    _add_ec_body(ec_el, ec.body, warnings)


def _add_ec_info(parent: etree._Element, info: ECInfo) -> None:
    info_el = etree.SubElement(parent, "ECInfo")
    if info.name:
        _add_text_el(info_el, "Name", info.name)
    if info.label:
        _add_text_el(info_el, "LblEC", info.label)
    if info.ec_type:
        _add_text_el(info_el, "ECType", info.ec_type)
    if info.ec_method:
        _add_text_el(info_el, "ECMethod", info.ec_method)
    if info.date:
        _add_text_el(info_el, "Date", info.date.strftime("%Y-%m-%d"))
    if info.currency:
        _add_text_el(info_el, "Cur", info.currency)
    if info.currency_label:
        _add_text_el(info_el, "CurLbl", info.currency_label)
    if info.date_of_price:
        _add_text_el(info_el, "DateOfPrice", info.date_of_price.strftime("%Y-%m-%d"))

    for bkdn in info.breakdowns:
        bkdn_el = etree.SubElement(info_el, "ECBkdn")
        if bkdn.bkdn_type:
            _add_text_el(bkdn_el, "Type", bkdn.bkdn_type)
        if bkdn.label:
            _add_text_el(bkdn_el, "LblOutline", bkdn.label)
        if bkdn.length:
            _add_text_el(bkdn_el, "Length", str(bkdn.length))
        if bkdn.is_numeric:
            _add_text_el(bkdn_el, "Num", "Yes")

    for cm in info.consortium_members:
        cm_el = etree.SubElement(info_el, "ConsortiumMember")
        if cm.description:
            _add_text_el(cm_el, "Description", cm.description)
        if cm.name or cm.street or cm.city:
            addr_el = etree.SubElement(cm_el, "Address")
            if cm.name:
                _add_text_el(addr_el, "Name", cm.name)
            if cm.street:
                _add_text_el(addr_el, "Street", cm.street)
            if cm.pcode:
                _add_text_el(addr_el, "PCode", cm.pcode)
            if cm.city:
                _add_text_el(addr_el, "City", cm.city)
            if cm.country:
                _add_text_el(addr_el, "Country", cm.country)

    if info.totals_net is not None or info.totals_gross is not None:
        totals_el = etree.SubElement(info_el, "Totals")
        if info.totals_net is not None:
            _add_text_el(totals_el, "TotalNet", _fmt_decimal(info.totals_net))
        if info.totals_gross is not None:
            _add_text_el(totals_el, "TotalGross", _fmt_decimal(info.totals_gross))


def _add_ec_body(
    parent: etree._Element, body: ECBody, warnings: list[str],
) -> None:
    body_el = etree.SubElement(parent, "ECBody")

    for ctgy in body.categories:
        _add_ec_ctgy(body_el, ctgy, warnings)

    for ce in body.cost_elements:
        _add_cost_element(body_el, ce, warnings)

    for de in body.dimension_elements:
        _add_dimension_element(body_el, de)

    for cat in body.category_elements:
        _add_category_element(body_el, cat)


def _add_ec_ctgy(
    parent: etree._Element, ctgy: ECCtgy, warnings: list[str],
) -> None:
    ctgy_el = etree.SubElement(parent, "ECCtgy")
    if ctgy.ele_no:
        _add_text_el(ctgy_el, "EleNo", ctgy.ele_no)
    if ctgy.description:
        _add_text_el(ctgy_el, "Descr", ctgy.description)
    if ctgy.portion is not None:
        _add_text_el(ctgy_el, "Portion", _fmt_decimal(ctgy.portion))

    for prop in ctgy.properties:
        _add_cost_property(ctgy_el, prop)

    if ctgy.body is not None:
        _add_ec_body(ctgy_el, ctgy.body, warnings)

    if ctgy.totals_net is not None or ctgy.totals_gross is not None:
        totals_el = etree.SubElement(ctgy_el, "Totals")
        if ctgy.totals_net is not None:
            _add_text_el(totals_el, "TotalNet", _fmt_decimal(ctgy.totals_net))
        if ctgy.totals_gross is not None:
            _add_text_el(totals_el, "TotalGross", _fmt_decimal(ctgy.totals_gross))


def _add_cost_element(
    parent: etree._Element, ce: CostElement, warnings: list[str],
) -> None:
    ce_el = etree.SubElement(parent, "CostElement")
    if ce.ele_no:
        _add_text_el(ce_el, "EleNo", ce.ele_no)
    if ce.short_text:
        _add_text_el(ce_el, "Descr", ce.short_text)
    if ce.cat_id:
        _add_text_el(ce_el, "CatID", ce.cat_id)
    if ce.remark:
        _add_text_el(ce_el, "Remark", ce.remark)
    if ce.qty is not None:
        _add_text_el(ce_el, "Qty", _fmt_decimal(ce.qty))
    if ce.unit:
        _add_text_el(ce_el, "QU", ce.unit)
    if ce.unit_price is not None:
        _add_text_el(ce_el, "UP", _fmt_decimal(ce.unit_price))
    if ce.item_total is not None:
        _add_text_el(ce_el, "IT", _fmt_decimal(ce.item_total))
    if ce.markup is not None:
        _add_text_el(ce_el, "Markup", _fmt_decimal(ce.markup))
    if ce.up_from is not None:
        _add_text_el(ce_el, "UPFrom", _fmt_decimal(ce.up_from))
    if ce.up_avg is not None:
        _add_text_el(ce_el, "UPAvg", _fmt_decimal(ce.up_avg))
    if ce.up_to is not None:
        _add_text_el(ce_el, "UPTo", _fmt_decimal(ce.up_to))
    if ce.is_bill_element:
        _add_text_el(ce_el, "BillElement", "Yes")

    for prop in ce.properties:
        _add_cost_property(ce_el, prop)

    for rg in ce.ref_groups:
        _add_ref_group(ce_el, rg)

    for child in ce.children:
        _add_cost_element(ce_el, child, warnings)


def _add_cost_property(parent: etree._Element, prop: CostProperty) -> None:
    prop_el = etree.SubElement(parent, "Property")
    if prop.name:
        _add_text_el(prop_el, "Name", prop.name)
    if prop.label:
        _add_text_el(prop_el, "LblProp", prop.label)
    if prop.arithmetic_qty_approach:
        _add_text_el(prop_el, "ArithmeticQuantityApproach", prop.arithmetic_qty_approach)
    if prop.value_qty_approach is not None:
        _add_text_el(prop_el, "ValueQuantityApproach", _fmt_decimal(prop.value_qty_approach))
    if prop.unit:
        _add_text_el(prop_el, "QU", prop.unit)
    if prop.prop_type:
        _add_text_el(prop_el, "Type", prop.prop_type)
    if prop.cad_id:
        _add_text_el(prop_el, "CAD_ID", prop.cad_id)


def _add_ref_group(parent: etree._Element, rg: RefGroup) -> None:
    rg_el = etree.SubElement(parent, "RefGroup")
    if rg.title:
        _add_text_el(rg_el, "Title", rg.title)
    for bi_ref in rg.boq_item_refs:
        ref_el = etree.SubElement(rg_el, "BoQItemRef")
        if bi_ref.id_ref:
            ref_el.set("IDRef", bi_ref.id_ref)
        if bi_ref.ref_type:
            ref_el.set("Type", bi_ref.ref_type)
        if bi_ref.portion is not None:
            _add_text_el(ref_el, "Portion", _fmt_decimal(bi_ref.portion))
    for bc_ref in rg.boq_ctgy_refs:
        ref_el = etree.SubElement(rg_el, "BoQCtgyRef")
        if bc_ref.id_ref:
            ref_el.set("IDRef", bc_ref.id_ref)
        if bc_ref.ref_type:
            ref_el.set("Type", bc_ref.ref_type)
        if bc_ref.portion is not None:
            _add_text_el(ref_el, "Portion", _fmt_decimal(bc_ref.portion))
    for ce_ref in rg.cost_element_refs:
        ref_el = etree.SubElement(rg_el, "CostElementRef")
        if ce_ref.id_ref:
            ref_el.set("IDRef", ce_ref.id_ref)
        if ce_ref.ref_type:
            ref_el.set("Type", ce_ref.ref_type)
        if ce_ref.portion is not None:
            _add_text_el(ref_el, "Portion", _fmt_decimal(ce_ref.portion))
    for de_ref in rg.dimension_element_refs:
        ref_el = etree.SubElement(rg_el, "DimensionElementRef")
        if de_ref.id_ref:
            ref_el.set("IDRef", de_ref.id_ref)
        if de_ref.ref_type:
            ref_el.set("Type", de_ref.ref_type)
        if de_ref.portion is not None:
            _add_text_el(ref_el, "Portion", _fmt_decimal(de_ref.portion))
    for cat_ref in rg.category_element_refs:
        ref_el = etree.SubElement(rg_el, "CategoryElementRef")
        if cat_ref.id_ref:
            ref_el.set("IDRef", cat_ref.id_ref)
        if cat_ref.ref_type:
            ref_el.set("Type", cat_ref.ref_type)
        if cat_ref.portion is not None:
            _add_text_el(ref_el, "Portion", _fmt_decimal(cat_ref.portion))
    for cm_ref in rg.consortium_member_refs:
        ref_el = etree.SubElement(rg_el, "ConsortiumMemberRef")
        if cm_ref.id_ref:
            ref_el.set("IDRef", cm_ref.id_ref)


def _add_dimension_element(parent: etree._Element, de: DimensionElement) -> None:
    de_el = etree.SubElement(parent, "DimensionElement")
    if de.ele_no:
        _add_text_el(de_el, "EleNo", de.ele_no)
    if de.description:
        _add_text_el(de_el, "Descr", de.description)
    if de.cat_id:
        _add_text_el(de_el, "CatID", de.cat_id)
    if de.remark:
        _add_text_el(de_el, "Remark", de.remark)
    if de.qty is not None:
        _add_text_el(de_el, "Qty", _fmt_decimal(de.qty))
    if de.unit:
        _add_text_el(de_el, "QU", de.unit)
    if de.markup is not None:
        _add_text_el(de_el, "Markup", _fmt_decimal(de.markup))
    for prop in de.properties:
        _add_cost_property(de_el, prop)


def _add_category_element(parent: etree._Element, cat: CategoryElement) -> None:
    cat_el = etree.SubElement(parent, "CategoryElement")
    if cat.ele_no:
        _add_text_el(cat_el, "EleNo", cat.ele_no)
    if cat.description:
        _add_text_el(cat_el, "Descr", cat.description)
    if cat.cat_id:
        _add_text_el(cat_el, "CatID", cat.cat_id)
    if cat.remark:
        _add_text_el(cat_el, "Remark", cat.remark)
    if cat.markup is not None:
        _add_text_el(cat_el, "Markup", _fmt_decimal(cat.markup))
    for prop in cat.properties:
        _add_cost_property(cat_el, prop)


# ------------------------------------------------------------------
# Quantity Determination (X31) serialisation
# ------------------------------------------------------------------

def _add_qty_determination(
    parent: etree._Element,
    qd: QtyDetermination,
    warnings: list[str],
) -> None:
    qd_el = etree.SubElement(parent, "QtyDeterm")

    if qd.prj_info is not None:
        prj_el = etree.SubElement(qd_el, "PrjInfo")
        if qd.prj_info.ref_prj_name:
            _add_text_el(prj_el, "RefPrjName", qd.prj_info.ref_prj_name)
        if qd.prj_info.ref_prj_id:
            _add_text_el(prj_el, "RefPrjID", qd.prj_info.ref_prj_id)

    _add_qty_determ_info(qd_el, qd.info)

    if qd.dp:
        _add_text_el(qd_el, "DP", qd.dp)

    if qd.owner is not None:
        own_el = etree.SubElement(qd_el, "OWN")
        _add_address(own_el, qd.owner)

    if qd.contractor is not None:
        ctr_el = etree.SubElement(qd_el, "CTR")
        _add_address(ctr_el, qd.contractor)

    _add_qty_boq(qd_el, qd.boq, warnings)


def _add_qty_determ_info(parent: etree._Element, info: QtyDetermInfo) -> None:
    info_el = etree.SubElement(parent, "QtyDetermInfo")

    if info.method:
        _add_text_el(info_el, "MethodDescription", info.method)
    if info.order_descr:
        _add_text_el(info_el, "OrdDescr", info.order_descr)
    if info.project_descr:
        _add_text_el(info_el, "ProjDescr", info.project_descr)

    if info.service_start is not None:
        _add_text_el(
            info_el, "ServiceProvisionStartDate",
            info.service_start.strftime("%Y-%m-%d"),
        )
    if info.service_end is not None:
        _add_text_el(
            info_el, "ServiceProvisionEndDate",
            info.service_end.strftime("%Y-%m-%d"),
        )

    if info.creator is not None:
        creator_el = etree.SubElement(info_el, "Creator")
        _add_address(creator_el, info.creator)

    if info.profiler is not None:
        profiler_el = etree.SubElement(info_el, "Profiler")
        _add_address(profiler_el, info.profiler)

    for ca in info.ctlg_assigns:
        _add_ctlg_assign(info_el, ca)


def _add_qty_boq(
    parent: etree._Element, boq: QtyBoQ, warnings: list[str],
) -> None:
    boq_el = etree.SubElement(parent, "BoQ")
    boq_el.set("ID", "B1")

    if boq.ref_boq_name:
        _add_text_el(boq_el, "RefBoQName", boq.ref_boq_name)
    if boq.ref_boq_id:
        _add_text_el(boq_el, "RefBoQID", boq.ref_boq_id)

    # QD keeps the <Type>/<Length> form for every version: its parser reads
    # only that shape. See the follow-up issue before making this version-aware.
    for bkdn in boq.bkdn:
        bkdn_el = etree.SubElement(boq_el, "BoQBkdn")
        _add_text_el(bkdn_el, "Type", _bkdn_tag(bkdn.bkdn_type))
        _add_text_el(bkdn_el, "Length", str(bkdn.length))

    for ctlg in boq.catalogs:
        _add_catalog(boq_el, ctlg)

    _add_qty_boq_body(boq_el, boq.body, warnings)

    for ca in boq.ctlg_assigns:
        _add_ctlg_assign(boq_el, ca)

    if boq.attachments:
        att_container = etree.SubElement(boq_el, "CtlgAttachment")
        for att in boq.attachments:
            _add_qty_attachment(att_container, att)


def _add_qty_boq_body(
    parent: etree._Element, body: QtyBoQBody, warnings: list[str],
) -> None:
    body_el = etree.SubElement(parent, "BoQBody")

    for ctgy in body.categories:
        if ctgy.rno:
            _add_qty_boq_ctgy(body_el, ctgy, warnings)
        else:
            itemlist_el = body_el.find("Itemlist")
            if itemlist_el is None:
                itemlist_el = etree.SubElement(body_el, "Itemlist")
            for item in ctgy.items:
                _add_qty_item(itemlist_el, item)


def _add_qty_boq_ctgy(
    parent: etree._Element, ctgy: QtyBoQCtgy, warnings: list[str],
) -> None:
    ctgy_el = etree.SubElement(parent, "BoQCtgy")
    ctgy_el.set("ID", f"C_{ctgy.rno}")
    ctgy_el.set("RNoPart", ctgy.rno)

    for ca in ctgy.ctlg_assigns:
        _add_ctlg_assign(ctgy_el, ca)

    if ctgy.subcategories or ctgy.items:
        inner_body = QtyBoQBody(categories=ctgy.subcategories)
        if ctgy.items:
            inner_body.categories = [
                *ctgy.subcategories,
                QtyBoQCtgy(rno="", items=ctgy.items),
            ]

        if ctgy.subcategories:
            sub_body_el = etree.SubElement(ctgy_el, "BoQBody")
            for sub in ctgy.subcategories:
                _add_qty_boq_ctgy(sub_body_el, sub, warnings)

        if ctgy.items:
            itemlist_el = etree.SubElement(ctgy_el, "Itemlist")
            for item in ctgy.items:
                _add_qty_item(itemlist_el, item)


def _add_qty_item(parent: etree._Element, item: QtyItem) -> None:
    item_el = etree.SubElement(parent, "Item")
    item_el.set("ID", f"I_{item.rno_part}")
    item_el.set("RNoPart", item.rno_part)
    if item.rno_index:
        item_el.set("RNoIndex", item.rno_index)

    if item.qty is not None or item.determ_items:
        qd_el = etree.SubElement(item_el, "QtyDeterm")
        if item.qty is not None:
            _add_text_el(qd_el, "Qty", _fmt_decimal(item.qty))
        for di in item.determ_items:
            _add_q_determ_item(qd_el, di)

    for ca in item.ctlg_assigns:
        _add_ctlg_assign(item_el, ca)


def _add_q_determ_item(parent: etree._Element, di: QDetermItem) -> None:
    di_el = etree.SubElement(parent, "QDetermItem")

    qtakeoff_el = etree.SubElement(di_el, "QTakeoff")
    qtakeoff_el.set("Row", di.takeoff_row.raw)

    for ca in di.ctlg_assigns:
        _add_ctlg_assign(di_el, ca)


def _add_catalog(parent: etree._Element, ctlg: Catalog) -> None:
    ctlg_el = etree.SubElement(parent, "Ctlg")
    if ctlg.ctlg_id:
        _add_text_el(ctlg_el, "CtlgID", ctlg.ctlg_id)
    if ctlg.ctlg_type:
        _add_text_el(ctlg_el, "CtlgType", ctlg.ctlg_type)
    if ctlg.ctlg_name:
        _add_text_el(ctlg_el, "CtlgName", ctlg.ctlg_name)
    if ctlg.assign_type:
        _add_text_el(ctlg_el, "CtlgAssignType", ctlg.assign_type)


def _add_ctlg_assign(parent: etree._Element, ca: CtlgAssign) -> None:
    ca_el = etree.SubElement(parent, "CtlgAssign")
    if ca.ctlg_id:
        _add_text_el(ca_el, "CtlgID", ca.ctlg_id)
    if ca.ctlg_code:
        _add_text_el(ca_el, "CtlgCode", ca.ctlg_code)
    if ca.quantity is not None:
        _add_text_el(ca_el, "Quantity", _fmt_decimal(ca.quantity))


def _add_qty_attachment(parent: etree._Element, att: QtyAttachment) -> None:
    att_el = etree.SubElement(parent, "Attachment")
    if att.name:
        _add_text_el(att_el, "Name", att.name)
    if att.text:
        _add_text_el(att_el, "Text", att.text)
    if att.description:
        _add_text_el(att_el, "Descrip", att.description)
    if att.file_type:
        _add_text_el(att_el, "Type", att.file_type)
    if att.data:
        _add_text_el(att_el, "Data", att.data_base64)


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


def _fmt_decimal(value: Decimal, decimal_places: int | None = None) -> str:
    """Format a Decimal value for XML output.

    When *decimal_places* is given the value is quantized to that precision
    (ROUND_HALF_UP).  Otherwise the native ``str()`` representation is used
    which preserves the precision from parsing.
    """
    if decimal_places is not None:
        quantizer = Decimal(10) ** -decimal_places
        return str(value.quantize(quantizer, rounding=ROUND_HALF_UP))
    return str(value)


def _bkdn_tag(bkdn_type: BkdnType) -> str:
    return {
        BkdnType.LOT: "Lot",
        BkdnType.BOQ_LEVEL: "BoQLevel",
        BkdnType.ITEM: "Item",
        BkdnType.INDEX: "Index",
    }.get(bkdn_type, "BoQLevel")
