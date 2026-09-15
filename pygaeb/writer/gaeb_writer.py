"""GAEBDocument → valid DA XML output for versions 2.0 through 3.3."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree

from pygaeb.models.boq import BoQ, BoQBkdn, BoQCtgy, BoQInfo, Totals
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
from pygaeb.models.document import (
    AwardInfo,
    ConstructionSite,
    GAEBDocument,
    GAEBInfo,
    Party,
)
from pygaeb.models.enums import BkdnType, ExchangePhase, ItemType, Provis, SourceVersion
from pygaeb.models.item import CostApproach, Item, RichText
from pygaeb.models.order import Address, OrderItem, TradeOrder
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
from pygaeb.writer.phase_profiles import PhaseProfile, profile_for
from pygaeb.writer.version_registry import (
    VERSION_REGISTRY,
    WRITABLE_VERSIONS,
    VersionMeta,
    cost_namespace,
    procurement_namespace,
    qty_namespace,
    trade_namespace,
)

if TYPE_CHECKING:
    from pygaeb.parser.gaeb_parser import XsdResult

logger = logging.getLogger("pygaeb.writer")

# xs:ID / xs:NCName: letter or underscore first, then letters, digits, . - _.
_NCNAME_RE = re.compile(r"[^\W\d][\w.\-]*")
_RNOPART_RE = re.compile(r"[_0-9A-Za-z]{1,14}")
# Legal direct children of DetailTxt (tgBoQText); anything else gets a <Text> wrapper.
_DETAIL_TXT_CHILDREN = frozenset({"Style", "Text", "TextComplement", "attachment"})


class _IdAllocator:
    """Hands out document-unique ``xs:ID`` values, keeping valid source IDs.

    Source IDs are reserved before any ID is generated, so a generated one can
    never collide with a source ID that appears later in the document.
    """

    def __init__(self) -> None:
        self._reserved: set[str] = set()
        self._issued: set[str] = set()
        self._counters: dict[str, int] = {}
        #: Python ``id()`` of a model object → the ID it will be written with.
        self.by_obj: dict[int, str] = {}
        #: Item OZ → written ID, for resolving MarkupSubQty references.
        self.by_rno: dict[str, str] = {}

    def reserve(self, ids: list[str]) -> None:
        self._reserved.update(ids)

    def claim(self, preferred: str | None, prefix: str) -> str:
        if preferred and _NCNAME_RE.fullmatch(preferred) and preferred not in self._issued:
            self._issued.add(preferred)
            return preferred
        n = self._counters.get(prefix, 0)
        while True:
            n += 1
            candidate = f"{prefix}{n}"
            if candidate not in self._reserved and candidate not in self._issued:
                break
        self._counters[prefix] = n
        self._issued.add(candidate)
        return candidate


def _assign_ids(boq: BoQ) -> _IdAllocator:
    """Pre-assign every BoQ/Lot/BoQCtgy/Item ID in document order."""
    ids = _IdAllocator()

    def walk(ctgy: BoQCtgy) -> list[BoQCtgy]:
        out = [ctgy]
        for sub in ctgy.subcategories:
            out.extend(walk(sub))
        return out

    ctgys = [c for lot in boq.lots for top in lot.body.categories for c in walk(top)]
    items = [item for c in ctgys for item in c.items]
    source_ids: list[str | None] = [
        boq.id,
        *(lot.id for lot in boq.lots),
        *(c.id for c in ctgys),
        *(i.id for i in items),
    ]
    ids.reserve([s for s in source_ids if s])
    ids.by_obj[id(boq)] = ids.claim(boq.id, "B")
    for lot in boq.lots:
        ids.by_obj[id(lot)] = ids.claim(lot.id, "L")
    for ctgy in ctgys:
        ids.by_obj[id(ctgy)] = ids.claim(ctgy.id, "C")
    for item in items:
        is_markup = item.item_type == ItemType.MARKUP
        ids.by_obj[id(item)] = ids.claim(item.id, "M" if is_markup else "I")
        if not is_markup:
            ids.by_rno.setdefault(item.oz, ids.by_obj[id(item)])
            ids.by_rno.setdefault(item.full_oz, ids.by_obj[id(item)])
    return ids


@dataclass
class _Ctx:
    """Everything the procurement emitters need to know about one write."""

    phase: ExchangePhase
    meta: VersionMeta
    profile: PhaseProfile
    warnings: list[str]
    ids: _IdAllocator
    up_frac_dig: int | None = None
    #: Elements the target phase's schema has no place for, keyed by what → where.
    omitted: dict[str, list[str]] = dc_field(default_factory=lambda: defaultdict(list))
    bad_rnoparts: list[str] = dc_field(default_factory=list)

    @property
    def de(self) -> bool:
        return self.meta.lang == "de"

    @property
    def phase_name(self) -> str:
        return self.phase.normalized().value

    def omit(self, what: str, where: str) -> None:
        self.omitted[what].append(where)

    def flush(self) -> None:
        # One summary line per element kind rather than one per item: these
        # omissions are inherent to the phase, not data loss the caller can fix.
        for what, places in self.omitted.items():
            sample = ", ".join(places[:3]) + (", …" if len(places) > 3 else "")
            self.warnings.append(
                f"{what} not written for {len(places)} element(s): not part of "
                f"{self.phase_name} in DA XML 3.x ({sample})"
            )
        if self.bad_rnoparts:
            sample = ", ".join(repr(o) for o in self.bad_rnoparts[:3])
            self.warnings.append(
                f"{len(self.bad_rnoparts)} item(s) have an RNoPart that is not "
                f"schema-valid (1-14 characters of [_0-9A-Za-z]; e.g. {sample}) — "
                f"use the leaf number, not the dotted OZ"
            )


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
        *,
        prog_system: str | None = None,
        prog_name: str | None = None,
    ) -> list[str]:
        """Serialize a GAEBDocument to a GAEB DA XML file.

        Args:
            doc: The document to serialize.
            path: Output file path.
            phase: Override exchange phase (default: keep original).
            target_version: Target DA XML version (default: 3.3).
            encoding: XML encoding declaration (default: utf-8).
            prog_system: ``<ProgSystem>`` — name and version of the generating
                software (default ``"pyGAEB <version>"``). Pass your own
                application's name when embedding pyGAEB.
            prog_name: ``<ProgName>`` (default: the source document's, else
                ``"pyGAEB"``).

        Returns:
            List of warnings about fields dropped or not written for the target
            version and phase.
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

        root, warnings = _build_xml(
            doc, target_phase, meta, prog_system=prog_system, prog_name=prog_name,
        )

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
        *,
        prog_system: str | None = None,
        prog_name: str | None = None,
    ) -> tuple[bytes, list[str]]:
        """Serialize a GAEBDocument to bytes.

        Returns:
            Tuple of (xml_bytes, warnings).
        """
        if target_version not in WRITABLE_VERSIONS:
            raise ValueError(f"Cannot write to {target_version.value}.")

        target_phase = phase or doc.exchange_phase
        meta = VERSION_REGISTRY[target_version]

        root, warnings = _build_xml(
            doc, target_phase, meta, prog_system=prog_system, prog_name=prog_name,
        )
        raw = etree.tostring(
            root, xml_declaration=True, encoding=encoding, pretty_print=True,
        )
        xml_bytes: bytes = raw if isinstance(raw, bytes) else raw.encode(encoding)

        if meta.lang == "de":
            translated = _translate_to_german(xml_bytes.decode(encoding))
            return translated.encode(encoding), warnings

        return xml_bytes, warnings

    @staticmethod
    def validate_against_xsd(
        doc: GAEBDocument,
        phase: ExchangePhase | None = None,
        target_version: SourceVersion = SourceVersion.DA_XML_33,
        xsd_dir: str | Path | None = None,
        *,
        prog_system: str | None = None,
        prog_name: str | None = None,
    ) -> XsdResult | None:
        """Serialize *doc* and validate the result against the phase's XSD.

        Args:
            doc: The document to serialize.
            phase: Exchange phase to write (default: the document's own).
            target_version: Target DA XML version (default: 3.3).
            xsd_dir: Schema directory; defaults to the ``PYGAEB_XSD_DIR`` setting.
            prog_system: See :meth:`write`.
            prog_name: See :meth:`write`.

        Returns:
            The validation result, or ``None`` when no schema is available.
        """
        from pygaeb.parser.gaeb_parser import validate_xml

        xml_bytes, _ = GAEBWriter.to_bytes(
            doc, phase=phase, target_version=target_version,
            prog_system=prog_system, prog_name=prog_name,
        )
        return validate_xml(
            xml_bytes, target_version, phase or doc.exchange_phase, xsd_dir,
        )


def _build_xml(
    doc: GAEBDocument, phase: ExchangePhase, meta: VersionMeta,
    prog_system: str | None = None, prog_name: str | None = None,
) -> tuple[etree._Element, list[str]]:
    warnings: list[str] = []

    # NOTE: the default namespace is written as a literal ``xmlns`` attribute
    # (not via ``nsmap``): passing both used to emit the declaration twice,
    # producing malformed XML that strict parsers reject.
    if doc.is_quantity and doc.qty_determination is not None:
        ns = qty_namespace(phase, SourceVersion(meta.version_tag))
        root = etree.Element("GAEB")
        root.set("xmlns", ns)
        _add_gaeb_info(root, doc.gaeb_info, meta, prog_system, prog_name)
        _add_qty_determination(root, doc.qty_determination, warnings)
        return root, warnings

    if doc.is_cost and doc.elemental_costing is not None:
        ns = cost_namespace(phase, SourceVersion(meta.version_tag))
        root = etree.Element("GAEB")
        root.set("xmlns", ns)
        _add_gaeb_info(root, doc.gaeb_info, meta, prog_system, prog_name)
        _add_elemental_costing(root, doc.elemental_costing, warnings)
        return root, warnings

    if doc.is_trade and doc.order is not None:
        ns = trade_namespace(phase, SourceVersion(meta.version_tag))
        root = etree.Element("GAEB")
        root.set("xmlns", ns)
        _add_gaeb_info(root, doc.gaeb_info, meta, prog_system, prog_name)
        _add_order(root, doc.order, phase, warnings)
        return root, warnings

    ns = procurement_namespace(phase, SourceVersion(meta.version_tag))
    root = etree.Element("GAEB")
    root.set("xmlns", ns)

    ctx = _Ctx(
        phase=phase,
        meta=meta,
        profile=profile_for(phase),
        warnings=warnings,
        ids=_assign_ids(doc.award.boq),
        up_frac_dig=doc.award.up_frac_dig,
    )
    _add_gaeb_info(root, doc.gaeb_info, meta, prog_system, prog_name)
    _add_prj_info(root, doc.award, ctx)
    _add_award(root, doc.award, ctx)
    ctx.flush()

    return root, warnings


def _add_gaeb_info(
    parent: etree._Element, info: GAEBInfo, meta: VersionMeta,
    prog_system: str | None = None, prog_name: str | None = None,
) -> None:
    from pygaeb import __version__

    gaeb_info = etree.SubElement(parent, "GAEBInfo")
    _add_text_el(gaeb_info, "Version", meta.version_tag)
    # Keep the source's document date; only stamp today when there was none.
    date = info.date.strftime("%Y-%m-%d") if info.date else datetime.now().strftime("%Y-%m-%d")

    if meta.lang == "de":
        if info.vers_date:
            _add_text_el(gaeb_info, "VersDate", info.vers_date)
        _add_text_el(gaeb_info, "ProgSystem", prog_system or f"pyGAEB {__version__}")
        _add_text_el(
            gaeb_info, "ProgSystemVersion", info.prog_system_version or __version__,
        )
        if prog_name or info.prog_name:
            _add_text_el(gaeb_info, "ProgName", prog_name or info.prog_name or "")
        _add_text_el(gaeb_info, "Date", date)
        if info.time:
            _add_text_el(gaeb_info, "Time", info.time)
        return

    # tgGAEBInfo sequence: Version, VersDate, Date, Time, ProgSystem, ProgName.
    # VersDate is enumerated per schema release, so a converted document takes
    # the target version's value rather than carrying the source's over.
    same_version = info.version == meta.version_tag
    vers_date = info.vers_date if (info.vers_date and same_version) else meta.vers_date
    if vers_date or info.vers_date:
        _add_text_el(gaeb_info, "VersDate", vers_date or info.vers_date or "")
    _add_text_el(gaeb_info, "Date", date)
    if info.time:
        _add_text_el(gaeb_info, "Time", info.time)
    # BVBS certification checks that ProgSystem names the generating software;
    # ProgName stays the source's (issue #34) unless the caller overrides it.
    _add_text_el(gaeb_info, "ProgSystem", (prog_system or f"pyGAEB {__version__}")[:60])
    _add_text_el(gaeb_info, "ProgName", (prog_name or info.prog_name or "pyGAEB")[:60])


def _add_ml_text(parent: etree._Element, tag: str, text: str | None) -> etree._Element:
    """Write formatted text (tgMLText/tgFText): ``<tag><p><span>text</span></p></tag>``."""
    el = etree.SubElement(parent, tag)
    if text:
        span_el = etree.SubElement(etree.SubElement(el, "p"), "span")
        span_el.text = text
    return el


def _fmt_date(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d") if value else None


def _add_prj_info(parent: etree._Element, award: AwardInfo, ctx: _Ctx) -> None:
    """Serialize PrjInfo fields from ``AwardInfo`` into a ``<PrjInfo>`` element."""
    if ctx.de:
        _add_prj_info_v2(parent, award)
        return

    slots = ctx.profile.prj_info
    # X84 allows PrjInfo only as NamePrj/PrjID/LblPrj, so it needs a name to exist.
    if slots.requires("NamePrj") and not award.project_name:
        return

    values: dict[str, str | None] = {
        "NamePrj": award.project_name,
        # The schema has no Prj element; the project number lives in PrjID.
        "PrjID": award.prj_id or award.project_no,
        "LblPrj": award.lbl_prj,
        "Descrip": award.description,
        "Cur": award.currency,
        "CurLbl": award.currency_label,
        "BidCommPerm": "Yes" if award.bid_comm_perm else None,
        "AlterBidPerm": "Yes" if award.alter_bid_perm else None,
        "UPFracDig": str(award.up_frac_dig) if award.up_frac_dig is not None else None,
    }
    has_data = any(v for k, v in values.items() if k != "Cur") or bool(award.ctlg_assigns)
    if not has_data:
        return

    prj_el = etree.SubElement(parent, "PrjInfo")
    for slot in slots.order:
        if slot == "CtlgAssign":
            for ca in award.ctlg_assigns:
                _add_ctlg_assign(prj_el, ca)
        elif slot == "Descrip":
            if values["Descrip"]:
                _add_ml_text(prj_el, "Descrip", values["Descrip"])
        elif values.get(slot):
            _add_text_el(prj_el, slot, values[slot] or "")


def _add_prj_info_v2(parent: etree._Element, award: AwardInfo) -> None:
    """DA XML 2.x PrjInfo — the pre-1.17 shape, renamed by ``_translate_to_german``."""
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


def _add_award(parent: etree._Element, award: AwardInfo, ctx: _Ctx) -> None:
    award_el = etree.SubElement(parent, "Award")
    # Exchange-phase marker, as the trade/cost/QD writers already emit.
    _add_text_el(award_el, "DP", ctx.phase.value.lstrip("X"))

    if ctx.de:
        _add_award_info_v2(award_el, award)
        _add_boq(award_el, award.boq, ctx)
        return

    slots = ctx.profile.award_info
    award_info_el = etree.SubElement(award_el, "AwardInfo")
    fields: list[tuple[str, str | None]] = [
        ("BoQID", award.boq_id),
        ("Cat", award.category),
        ("Cur", award.currency),
        ("CurLbl", award.currency_label),
        ("OpenDate", _fmt_date(award.open_date)),
        # OpenTime is only valid right after OpenDate.
        ("OpenTime", award.open_time if award.open_date else None),
        ("EvalEnd", _fmt_date(award.eval_end)),
        ("SubmLoc", award.submit_location),
        ("CnstStart", _fmt_date(award.construction_start)),
        ("CnstEnd", _fmt_date(award.construction_end)),
        ("ContrNo", award.contract_no),
        ("ContrDate", _fmt_date(award.contract_date)),
        ("AcceptType", award.accept_type),
        ("WarrDur", str(award.warranty_duration) if award.warranty_duration is not None else None),
        ("WarrUnit", award.warranty_unit),
    ]
    for tag, value in fields:
        if not value:
            continue
        if slots.allows(tag):
            _add_text_el(award_info_el, tag, value)
        else:
            ctx.omit(tag, "AwardInfo")
    if award.procurement_type:
        ctx.omit("PrcTyp", "AwardInfo")

    award_slots = ctx.profile.award
    _add_party(
        award_el, "OWN", _owner_party(award), ("DPNo", "AwardNo", "AcctRecNo"), award_slots, ctx,
    )
    _add_party(award_el, "CTR", award.contractor, ctx.profile.ctr_fields, award_slots, ctx)
    if award.construction_site is not None:
        if award_slots.allows("CnstSite"):
            _add_cnst_site(award_el, award.construction_site, ctx)
        else:
            ctx.omit("CnstSite", "Award")

    _add_boq(award_el, award.boq, ctx)


def _add_award_info_v2(award_el: etree._Element, award: AwardInfo) -> None:
    """DA XML 2.x AwardInfo/OWN — the pre-1.17 shape, renamed by ``_translate_to_german``."""
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
    for tag, value in [
        ("OpenDate", _fmt_date(award.open_date)),
        ("OpenTime", award.open_time),
        ("EvalEnd", _fmt_date(award.eval_end)),
        ("SubmLoc", award.submit_location),
        ("CnstStart", _fmt_date(award.construction_start)),
        ("CnstEnd", _fmt_date(award.construction_end)),
        ("ContrNo", award.contract_no),
        ("ContrDate", _fmt_date(award.contract_date)),
        ("AcceptType", award.accept_type),
        ("WarrDur", str(award.warranty_duration) if award.warranty_duration is not None else None),
        ("WarrUnit", award.warranty_unit),
    ]:
        if value:
            _add_text_el(award_info_el, tag, value)

    if award.owner_address or award.award_no:
        own_el = etree.SubElement(award_el, "OWN")
        _add_address(own_el, award.owner_address)
        if award.award_no:
            _add_text_el(own_el, "AwardNo", award.award_no)
    elif award.client:
        _add_text_el(award_info_el, "OWN", award.client)


def _owner_party(award: AwardInfo) -> Party | None:
    """Assemble the OWN block from the flat owner fields on ``AwardInfo``."""
    if not (award.owner_address or award.award_no or award.client):
        return None
    address = award.owner_address
    if address is None and award.client:
        address = Address(name=award.client)
    return Party(address=address, award_no=award.award_no)


def _add_party(
    parent: etree._Element, tag: str, party: Party | None, fields: tuple[str, ...],
    slots: Any, ctx: _Ctx,
) -> None:
    """Write an OWN/CTR block, or a placeholder when the phase requires one.

    *fields* lists the children the phase allows after ``Address``, in order.
    """
    if not slots.allows(tag):
        if party is not None:
            ctx.omit(tag, "Award")
        return
    if party is None:
        if not slots.requires(tag):
            return
        party = Party()
        ctx.warnings.append(
            f"{tag} is required in {ctx.phase_name} but the document has none; "
            f"wrote an empty placeholder"
        )

    el = etree.SubElement(parent, tag)
    if party.address is not None or ctx.profile.party_address_required:
        _add_address(el, party.address, complete=True)
    values = {
        "DPNo": party.dp_no, "AwardNo": party.award_no,
        "AcctRecNo": party.acct_no, "AcctsPayNo": party.acct_no,
        "BidderNo": party.bidder_no,
    }
    for child in fields:
        if values.get(child):
            _add_text_el(el, child, values[child] or "")
    if party.bidder_no and "BidderNo" not in fields:
        ctx.omit("BidderNo", tag)


def _add_cnst_site(parent: etree._Element, site: ConstructionSite, ctx: _Ctx) -> None:
    el = etree.SubElement(parent, "CnstSite")
    if site.address is not None or ctx.profile.party_address_required:
        _add_address(el, site.address, complete=True)
    if site.id_no:
        _add_text_el(el, "CnstSiteIDNo", site.id_no)
    if site.name:
        _add_text_el(el, "CnstSiteName", site.name)


def _add_boq(parent: etree._Element, boq: BoQ, ctx: _Ctx) -> None:
    boq_el = etree.SubElement(parent, "BoQ")
    if not ctx.de:
        boq_el.set("ID", ctx.ids.by_obj.get(id(boq)) or ctx.ids.claim(boq.id, "B"))

    # tgBoQ requires BoQInfo; 3.x synthesises one for documents built without it.
    if boq.boq_info is not None or not ctx.de:
        _add_boq_info(boq_el, boq.boq_info or BoQInfo(), ctx)

    boq_body = etree.SubElement(boq_el, "BoQBody")

    for lot in boq.lots:
        if boq.is_multi_lot:
            # A lot is a BoQCtgy in the file; reuse the category emitter so the
            # ID, label markup and body/totals order come out identical.
            wrapper = BoQCtgy(
                id=lot.id, rno=lot.rno, label=lot.label,
                subcategories=lot.body.categories, totals=lot.totals,
            )
            _add_ctgy(boq_body, wrapper, ctx, element_id=ctx.ids.by_obj.get(id(lot)))
        else:
            _add_body_categories(boq_body, lot.body.categories, ctx)


def _add_bkdn(
    parent: etree._Element, bkdn: list[BoQBkdn], meta: VersionMeta,
) -> None:
    """Emit the BoQ breakdown in the form the target version expects."""
    if not bkdn:
        return

    if meta.bkdn_sibling_form:
        # tgBoQBkdn: Type, LblBoQBkdn?, Length, Num, Alignment? — Num is required.
        for level in bkdn:
            bkdn_el = etree.SubElement(parent, "BoQBkdn")
            _add_text_el(bkdn_el, "Type", _bkdn_tag(level.bkdn_type))
            if level.label:
                _add_text_el(bkdn_el, "LblBoQBkdn", level.label)
            _add_text_el(bkdn_el, "Length", str(level.length))
            _add_text_el(bkdn_el, "Num", "No" if level.num is False else "Yes")
            if level.alignment:
                _add_text_el(bkdn_el, "Alignment", level.alignment)
        return

    bkdn_el = etree.SubElement(parent, "BoQBkdn")
    for level in bkdn:
        level_el = etree.SubElement(bkdn_el, _bkdn_tag(level.bkdn_type))
        level_el.set("Length", str(level.length))
        if level.num:
            level_el.set("Num", "Yes")


def _add_boq_info(parent: etree._Element, info: BoQInfo, ctx: _Ctx) -> None:
    info_el = etree.SubElement(parent, "BoQInfo")
    if ctx.de:
        _fill_boq_info_v2(info_el, info, ctx.meta)
        return

    slots = ctx.profile.boq_info
    name = info.name or ""
    if slots.allows("Name") and (name or slots.requires("Name")):
        _add_text_el(info_el, "Name", name)
        if len(name) > 20:
            ctx.warnings.append(f"BoQInfo/Name exceeds the schema's 20 characters: {name!r}")
    if slots.allows("LblBoQ"):
        lbl = info.lbl_boq or (name if slots.requires("LblBoQ") else None)
        if lbl is not None:
            _add_text_el(info_el, "LblBoQ", lbl)
    if slots.allows("Date") and info.date:
        _add_text_el(info_el, "Date", info.date)
    if slots.allows("OutlCompl"):
        outl = info.outl_compl or ("AllTxt" if slots.requires("OutlCompl") else None)
        if outl:
            _add_text_el(info_el, "OutlCompl", outl)

    if not info.bkdn:
        ctx.warnings.append("BoQInfo has no breakdown levels; the schema requires at least one")
    elif len(info.bkdn) > 7:
        ctx.warnings.append(
            f"BoQInfo has {len(info.bkdn)} breakdown levels; the schema allows 7"
        )
    _add_bkdn(info_el, info.bkdn, ctx.meta)

    if slots.allows("NoUPComps"):
        count = info.no_up_comps
        if count is None and info.lbl_up_comps:
            count = len(info.lbl_up_comps)
        if count is not None:
            _add_text_el(info_el, "NoUPComps", str(count))
            for idx, label in enumerate(info.lbl_up_comps[:6], start=1):
                lbl_el = etree.SubElement(info_el, f"LblUPComp{idx}")
                lbl_el.text = label
                types = info.lbl_up_comp_types
                lbl_el.set("Type", types[idx - 1] if idx - 1 < len(types) else "Unknown")
    if slots.allows("LblTime") and info.lbl_time:
        _add_text_el(info_el, "LblTime", info.lbl_time)

    if slots.allows("CostType"):
        _add_boq_info_cost_types(info_el, info)
    elif info.cost_types:
        ctx.omit("CostType", "BoQInfo")

    if slots.allows("CtlgAssign"):
        for ca in info.ctlg_assigns:
            _add_ctlg_assign(info_el, ca)

    if slots.allows("Totals"):
        if info.totals is not None:
            _add_totals(info_el, info.totals)
    elif info.totals is not None:
        ctx.omit("Totals", "BoQInfo")


def _fill_boq_info_v2(info_el: etree._Element, info: BoQInfo, meta: VersionMeta) -> None:
    """DA XML 2.x BoQInfo — the pre-1.17 shape, renamed by ``_translate_to_german``."""
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
    parent: etree._Element, categories: list[BoQCtgy], ctx: _Ctx,
) -> None:
    for ctgy in categories:
        # An anonymous, childless category is the wrapper the parser puts around
        # items that sat straight under BoQBody — write them back out bare rather
        # than inventing a category level the source never had.
        if not ctgy.rno and not ctgy.label and not ctgy.subcategories:
            _add_itemlist(parent, ctgy.items, ctx)
        else:
            _add_ctgy(parent, ctgy, ctx)


def _add_itemlist(parent: etree._Element, items: list[Item], ctx: _Ctx) -> None:
    if not items:
        return
    itemlist = etree.SubElement(parent, "Itemlist")
    for item in items:
        if item.item_type == ItemType.MARKUP:
            _add_markup_item(itemlist, item, ctx)
        else:
            _add_item(itemlist, item, ctx)


def _add_ctgy(
    parent: etree._Element, ctgy: BoQCtgy, ctx: _Ctx, element_id: str | None = None,
) -> None:
    ctgy_el = etree.SubElement(parent, "BoQCtgy")
    if not ctx.de:
        ctgy_el.set(
            "ID",
            element_id or ctx.ids.by_obj.get(id(ctgy)) or ctx.ids.claim(ctgy.id, "C"),
        )
    if ctgy.rno:
        ctgy_el.set("RNoPart", ctgy.rno)

    slots = ctx.profile.boq_ctgy
    where = f"BoQCtgy {ctgy.rno or '?'}"
    if ctx.de:
        if ctgy.label:
            _add_text_el(ctgy_el, "LblTx", ctgy.label)
    elif slots.allows("LblTx"):
        # LblTx is formatted text and required; an empty element is valid.
        _add_ml_text(ctgy_el, "LblTx", ctgy.label)
    elif ctgy.label:
        ctx.omit("LblTx", where)

    if ctx.de or slots.allows("CtlgAssign"):
        for ca in ctgy.ctlg_assigns:
            _add_ctlg_assign(ctgy_el, ca)
    elif ctgy.ctlg_assigns:
        ctx.omit("CtlgAssign", where)

    # GAEB schema: a BoQCtgy holds exactly ONE BoQBody, which contains either
    # sub-BoQCtgy elements or the Itemlist. A body per subcategory used to be
    # written here — parsers then read only the first one back.
    if ctgy.subcategories or ctgy.items:
        if ctgy.subcategories and ctgy.items and not ctx.de:
            ctx.warnings.append(
                f"{where}: holds both subcategories and items; the schema allows "
                f"one or the other in a BoQBody"
            )
        body_el = etree.SubElement(ctgy_el, "BoQBody")
        _add_body_categories(body_el, ctgy.subcategories, ctx)
        _add_itemlist(body_el, ctgy.items, ctx)

    totals = ctgy.totals
    if ctx.de or slots.allows("Totals"):
        if totals is None and slots.requires("Totals") and not ctx.de:
            totals = Totals(total=ctgy.subtotal)
        if totals is not None:
            _add_totals(ctgy_el, totals)
    elif totals is not None:
        ctx.omit("Totals", where)


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
            children = [c for c in frag if not callable(c.tag)]
            # DetailTxt only takes Text/TextComplement/…; a 2.x-sourced fragment
            # starts at <p>, so give it the <Text> wrapper the schema wants.
            needs_wrapper = any(
                etree.QName(c).localname not in _DETAIL_TXT_CHILDREN for c in children
            )
            if needs_wrapper:
                target = etree.SubElement(parent, "Text")
                if frag.text and frag.text.strip():
                    span_el = etree.SubElement(etree.SubElement(target, "p"), "span")
                    span_el.text = frag.text
            else:
                target = parent
                # Verbatim, whitespace included: keeps repeated round trips stable.
                target.text = frag.text
            for child in children:
                _copy_stripped(child, target)
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


def _add_bidder_complements(parent: etree._Element, text: RichText) -> bool:
    """X84 DetailTxt: only the bidder's ``TextComplement`` blocks, each reduced to
    its ``ComplBody`` — the tender's own text is not repeated in a bid."""
    inner = text.raw_html
    if not inner or not inner.strip():
        return False
    try:
        frag = etree.fromstring(f"<w>{inner}</w>")
    except etree.XMLSyntaxError:
        return False

    found = False
    for tc in frag.iter():
        if callable(tc.tag) or etree.QName(tc).localname != "TextComplement":
            continue
        tc_el = etree.SubElement(parent, "TextComplement")
        for key, value in tc.attrib.items():
            tc_el.set(etree.QName(key).localname if "}" in key else key, value)
        for child in tc:
            if callable(child.tag):
                continue
            if etree.QName(child).localname in ("ComplBodyDec", "ComplBodyInt", "ComplBody"):
                _copy_stripped(child, tc_el)
        if tc_el.find("ComplBody") is None:
            etree.SubElement(tc_el, "ComplBody")
        # Drop the source's inter-element whitespace so repeated writes are
        # byte-identical; pretty_print re-indents element-only content.
        tc_el.text = None
        for copied in tc_el:
            copied.tail = None
        found = True
    return found


def _has_long_text(item: Item) -> bool:
    lt = item.long_text
    return lt is not None and bool(
        (lt.raw_html or "").strip() or lt.paragraphs or lt.plain_text
    )


def _add_outline(parent: etree._Element, short_text: str) -> None:
    """``OutlineText/OutlTxt/TextOutlTxt`` — an empty TextOutlTxt is schema-valid."""
    outl_txt = etree.SubElement(etree.SubElement(parent, "OutlineText"), "OutlTxt")
    _add_ml_text(outl_txt, "TextOutlTxt", short_text)


def _add_item_text(
    parent: etree._Element, item: Item, ctx: _Ctx, required: bool = False,
) -> None:
    """Write short and long text in the shape the target phase expects.

    DA XML 3.x carries both inside ``<Description>``; 2.x uses flat
    ``ShortText``/``LongText``, which ``_translate_to_german`` renames.
    """
    meta = ctx.meta
    if ctx.de:
        if item.long_text and meta.supports_long_text_cdata:
            inner = item.long_text.raw_html or item.long_text.plain_text or "\n".join(
                item.long_text.paragraphs
            )
            if inner:
                lt_el = etree.SubElement(parent, "LongText")
                lt_el.text = etree.CDATA(inner)
        return

    has_long = _has_long_text(item)

    # X84: Description is CompleteText/DetailTxt holding only the bidder's
    # text complements — no outline text, no tender text.
    if ctx.profile.description == "detail_only":
        if not has_long:
            return
        desc_el = etree.SubElement(parent, "Description")
        detail_el = etree.SubElement(
            etree.SubElement(desc_el, "CompleteText"), "DetailTxt",
        )
        if item.long_text is None or not _add_bidder_complements(detail_el, item.long_text):
            parent.remove(desc_el)
        return

    if not item.short_text and not has_long and not required:
        return

    desc_el = etree.SubElement(parent, "Description")
    if has_long and item.long_text is not None:
        # tgCompleteText requires DetailTxt, so CompleteText only exists with one.
        complete_el = etree.SubElement(desc_el, "CompleteText")
        detail_el = etree.SubElement(complete_el, "DetailTxt")
        if _add_richtext(detail_el, item.long_text):
            if item.short_text:
                _add_outline(complete_el, item.short_text)
            return
        desc_el.remove(complete_el)

    _add_outline(desc_el, item.short_text)


def _add_item(parent: etree._Element, item: Item, ctx: _Ctx) -> None:
    if ctx.de:
        _add_item_v2(parent, item, ctx)
        return

    meta = ctx.meta
    slots = ctx.profile.item
    where = f"Item {item.full_oz or item.oz}"

    item_el = etree.SubElement(parent, "Item")
    item_el.set("ID", ctx.ids.by_obj.get(id(item)) or ctx.ids.claim(item.id, "I"))
    item_el.set("RNoPart", item.oz)
    if item.rno_index:
        item_el.set("RNoIndex", item.rno_index)
    if not _RNOPART_RE.fullmatch(item.oz or ""):
        ctx.bad_rnoparts.append(item.oz)

    # Position type (Bedarfs-/Alternativ-/Pauschalposition …). MARKUP is handled by
    # the _add_markup_item branch; NORMAL carries no marker. Emitting the marker keeps
    # the "priced but not summed" rule intact on re-read — without it every non-Normal
    # position silently becomes Normal and its price joins the total.
    marker = WRITER_MARKER.get(item.item_type)
    if marker is not None:
        if slots.allows("TypeMarker"):
            marker_el = etree.SubElement(item_el, marker)
            if marker == "Provis":
                marker_el.text = (item.provis or Provis.WITHOUT_TOTAL).value
            elif marker in ("LumpSumItem", "GlobItem"):
                marker_el.text = "Yes"  # tgYesNo
            if item.item_type in NON_INTEROP_TYPES:
                ctx.warnings.append(
                    f"{where}: {item.item_type.value} written as pyGAEB-internal "
                    f"<{marker}> — round-trips within pyGAEB but is not read by other "
                    f"AVA software yet (real GAEB serialization not implemented)"
                )
        else:
            # X84 has no position-type markers: the bid inherits them from the tender.
            ctx.omit(f"{item.item_type.value} position marker", where)

    if item.change_order_number:
        if not meta.supports_change_order:
            ctx.warnings.append(
                f"{where}: change_order_number dropped "
                f"(not supported in DA XML {meta.version_tag})"
            )
        elif not slots.allows("CONo"):
            ctx.omit("CONo", where)
        elif item.co_status:
            _add_text_el(item_el, "CONo", item.change_order_number)
            _add_text_el(item_el, "COStatus", item.co_status)
        else:
            ctx.warnings.append(
                f"{where}: change_order_number dropped (the schema only allows CONo "
                f"together with COStatus; set item.co_status)"
            )

    # X83 spells "quantity still open" as QtyTBD *instead of* Qty.
    tbd_only = item.qty_tbd and ctx.phase.normalized() == ExchangePhase.X83
    if item.qty_tbd and slots.allows("QtyTBD"):
        _add_text_el(item_el, "QtyTBD", "Yes")
    if item.qty is not None and slots.allows("Qty") and not tbd_only:
        _add_text_el(item_el, "Qty", _fmt_decimal(item.qty))

    if item.qty_splits:
        if slots.allows("QtySplit") and not tbd_only:
            # tgQtySplit is (QtyPcnt | Qty) + CtlgAssign — no label, no unit.
            for split in item.qty_splits:
                qs_el = etree.SubElement(item_el, "QtySplit")
                _add_text_el(qs_el, "Qty", _fmt_decimal(split.qty))
            if any(s.label or s.unit for s in item.qty_splits):
                ctx.omit("QtySplit label/unit", where)
        else:
            ctx.omit("QtySplit", where)

    if slots.allows("QU"):
        if item.unit:
            _add_text_el(item_el, "QU", item.unit)
        elif slots.requires("QU"):
            _add_text_el(item_el, "QU", "")
            ctx.warnings.append(
                f"{where}: QU is required in {ctx.phase_name} but the item has no unit"
            )
    elif item.unit:
        ctx.omit("QU", where)

    if slots.allows("CtlgAssign"):
        for ctlg in item.ctlg_assigns:
            _add_ctlg_assign(item_el, ctlg)
    elif item.ctlg_assigns:
        ctx.omit("CtlgAssign", where)

    # UPComp and DiscountPcnt are only valid inside the UP group.
    if item.unit_price is not None:
        if slots.allows("UP"):
            _add_text_el(item_el, "UP", _fmt_decimal(item.unit_price, ctx.up_frac_dig))
            if slots.allows("UPComp"):
                for i, comp in enumerate(item.up_components, 1):
                    _add_text_el(item_el, f"UPComp{i}", _fmt_decimal(comp))
            if item.discount_pct is not None and slots.allows("DiscountPcnt"):
                _add_text_el(item_el, "DiscountPcnt", _fmt_decimal(item.discount_pct))
        else:
            ctx.omit("UP", where)
    else:
        if item.up_components:
            ctx.omit("UPComp", where)
        if item.discount_pct is not None:
            ctx.omit("DiscountPcnt", where)

    if item.total_price is not None:
        if slots.allows("IT"):
            _add_text_el(item_el, "IT", _fmt_decimal(item.total_price))
        else:
            ctx.omit("IT", where)

    if item.vat is not None:
        _add_text_el(item_el, "VAT", _fmt_decimal(item.vat))

    _add_item_text(item_el, item, ctx)

    if slots.allows("CostApproach"):
        for ca in item.cost_approaches:
            _add_cost_approach(item_el, ca)
    elif item.cost_approaches:
        ctx.omit("CostApproach", where)

    # Not part of any 3.x procurement schema: pyGAEB-only serialisations.
    if item.bim_guid:
        if not meta.supports_bim_guid:
            ctx.warnings.append(
                f"{where}: bim_guid dropped (not supported in DA XML {meta.version_tag})"
            )
        else:
            ctx.omit("GUID", where)
    if item.attachments:
        if not meta.supports_attachments:
            ctx.warnings.append(
                f"{where}: {len(item.attachments)} attachment(s) dropped "
                f"(not supported in DA XML {meta.version_tag})"
            )
        else:
            # Embedded images survive inside the long text's own markup.
            ctx.omit("Item.attachments", where)
    if item.bidder_prices:
        # Preisspiegel data has no GAEB home; kept as a pyGAEB extension so it
        # round-trips, at the cost of schema validity for such documents.
        for bp in item.bidder_prices:
            bp_el = etree.SubElement(item_el, "BidderUP")
            if bp.bidder_name:
                _add_text_el(bp_el, "BidderName", bp.bidder_name)
            if bp.bidder_id:
                _add_text_el(bp_el, "BidderID", bp.bidder_id)
            if bp.unit_price is not None:
                _add_text_el(bp_el, "UP", _fmt_decimal(bp.unit_price, ctx.up_frac_dig))
            if bp.total_price is not None:
                _add_text_el(bp_el, "IT", _fmt_decimal(bp.total_price))
        ctx.warnings.append(
            f"{where}: bidder_prices written as pyGAEB-internal <BidderUP> — "
            f"round-trips within pyGAEB but is not part of the GAEB schema"
        )


def _add_item_v2(parent: etree._Element, item: Item, ctx: _Ctx) -> None:
    """DA XML 2.x item — the pre-1.17 shape, renamed by ``_translate_to_german``."""
    meta = ctx.meta
    warnings = ctx.warnings
    item_el = etree.SubElement(parent, "Item")
    item_el.set("RNoPart", item.oz)

    marker = WRITER_MARKER.get(item.item_type)
    if marker is not None:
        etree.SubElement(item_el, marker)
        if item.item_type in NON_INTEROP_TYPES:
            warnings.append(
                f"Item {item.oz}: {item.item_type.value} written as pyGAEB-internal "
                f"<{marker}> — round-trips within pyGAEB but is not read by other AVA "
                f"software yet (real GAEB serialization not implemented)"
            )

    if item.short_text:
        _add_text_el(item_el, "ShortText", item.short_text)
    if item.qty_tbd:
        _add_text_el(item_el, "QtyTBD", "Yes")
    if item.qty is not None:
        _add_text_el(item_el, "Qty", _fmt_decimal(item.qty))
    if item.unit:
        _add_text_el(item_el, "QU", item.unit)
    if item.unit_price is not None:
        _add_text_el(item_el, "UP", _fmt_decimal(item.unit_price, ctx.up_frac_dig))
    if item.total_price is not None:
        _add_text_el(item_el, "IT", _fmt_decimal(item.total_price))

    for split in item.qty_splits:
        qs_el = etree.SubElement(item_el, "QtySplit")
        if split.label:
            _add_text_el(qs_el, "Label", split.label)
        _add_text_el(qs_el, "Qty", _fmt_decimal(split.qty))
        if split.unit:
            _add_text_el(qs_el, "QU", split.unit)

    _add_item_text(item_el, item, ctx)

    if item.bim_guid:
        warnings.append(
            f"Item {item.oz}: bim_guid dropped (not supported in DA XML {meta.version_tag})"
        )
    if item.change_order_number:
        warnings.append(
            f"Item {item.oz}: change_order_number dropped "
            f"(not supported in DA XML {meta.version_tag})"
        )
    if item.attachments:
        warnings.append(
            f"Item {item.oz}: {len(item.attachments)} attachment(s) dropped "
            f"(not supported in DA XML {meta.version_tag})"
        )

    for i, comp in enumerate(item.up_components, 1):
        _add_text_el(item_el, f"UPComp{i}", _fmt_decimal(comp))
    if item.discount_pct is not None:
        _add_text_el(item_el, "DiscountPcnt", _fmt_decimal(item.discount_pct))
    if item.vat is not None:
        _add_text_el(item_el, "VAT", _fmt_decimal(item.vat))
    for ctlg in item.ctlg_assigns:
        _add_ctlg_assign(item_el, ctlg)


def _add_markup_item(parent: etree._Element, item: Item, ctx: _Ctx) -> None:
    """Serialize a markup item as ``<MarkupItem>`` (Zuschlagsposition)."""
    mu_el = etree.SubElement(parent, "MarkupItem")
    if not ctx.de:
        mu_el.set("ID", ctx.ids.by_obj.get(id(item)) or ctx.ids.claim(item.id, "M"))
    mu_el.set("RNoPart", item.oz)
    if item.rno_index and not ctx.de:
        mu_el.set("RNoIndex", item.rno_index)

    if ctx.de:
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
        return

    slots = ctx.profile.markup_item
    where = f"MarkupItem {item.full_oz or item.oz}"

    if slots.allows("MarkupType"):
        if item.markup_type:
            _add_text_el(mu_el, "MarkupType", item.markup_type)
        elif slots.requires("MarkupType"):
            ctx.warnings.append(
                f"{where}: MarkupType is required in {ctx.phase_name} but unset "
                f"(IdentAsMark | AllInCat | ListInSubQty)"
            )
    elif item.markup_type:
        ctx.omit("MarkupType", where)

    if slots.allows("MarkupSubQty"):
        for sub in item.markup_sub_qtys:
            # RefItem/@IDRef must point at an Item written in this document.
            ref = sub.ref_id or ctx.ids.by_rno.get(sub.ref_rno)
            if not ref:
                ctx.warnings.append(
                    f"{where}: MarkupSubQty reference {sub.ref_rno or sub.ref_id!r} "
                    f"does not resolve to an item; not written"
                )
                continue
            sub_el = etree.SubElement(mu_el, "MarkupSubQty")
            etree.SubElement(sub_el, "RefItem").set("IDRef", ref)
            if sub.sub_qty is not None:
                _add_text_el(sub_el, "SubQty", _fmt_decimal(sub.sub_qty))
    elif item.markup_sub_qtys:
        ctx.omit("MarkupSubQty", where)

    for tag, value in (("ITMarkup", item.total_price), ("Markup", item.unit_price)):
        if not slots.allows(tag):
            if value is not None:
                ctx.omit(tag, where)
            continue
        if value is not None:
            _add_text_el(mu_el, tag, _fmt_decimal(value))
        elif slots.requires(tag):
            _add_text_el(mu_el, tag, "0.00")
            ctx.warnings.append(
                f"{where}: {tag} is required in {ctx.phase_name} but unset; wrote 0.00"
            )

    if item.discount_pct is not None:
        if slots.allows("DiscountPcnt"):
            _add_text_el(mu_el, "DiscountPcnt", _fmt_decimal(item.discount_pct))
        else:
            ctx.omit("DiscountPcnt", where)

    _add_item_text(mu_el, item, ctx, required=slots.requires("Description"))

    if slots.allows("CtlgAssign"):
        for ca in item.ctlg_assigns:
            _add_ctlg_assign(mu_el, ca)
    elif item.ctlg_assigns:
        ctx.omit("CtlgAssign", where)


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


_ADDRESS_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Name1"), ("name2", "Name2"), ("name3", "Name3"), ("name4", "Name4"),
    ("street", "Street"), ("pcode", "PCode"), ("city", "City"), ("country", "Country"),
    ("iln", "ILN"), ("contact", "Contact"), ("phone", "Phone"), ("fax", "Fax"),
    ("email", "Email"), ("vat_id", "VATID"),
)
_ADDRESS_REQUIRED = frozenset({"Name1", "Street", "PCode", "City"})


def _add_address(parent: etree._Element, addr: Any, complete: bool = False) -> None:
    """Write a ``tgAddress``; *complete* always emits its four required children."""
    if addr is None and not complete:
        return
    addr_el = etree.SubElement(parent, "Address")
    for field_name, tag_name in _ADDRESS_FIELDS:
        val = getattr(addr, field_name, None) if addr is not None else None
        if val or (complete and tag_name in _ADDRESS_REQUIRED):
            _add_text_el(addr_el, tag_name, val or "")


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

    # Total is the one required child of tgTotals.
    total = totals.total if totals.total is not None else Decimal("0.00")
    _add_text_el(t_el, "Total", _fmt_decimal(total))

    # tgTotals: ((DiscountPcnt | DiscountAmt) TotAfterDisc) | TotalLSUM — a
    # discount is only expressible together with the discounted total.
    if totals.tot_after_disc is not None and (
        totals.discount_pcnt is not None or totals.discount_amt is not None
    ):
        if totals.discount_pcnt is not None:
            _add_text_el(t_el, "DiscountPcnt", _fmt_decimal(totals.discount_pcnt))
        else:
            _add_text_el(t_el, "DiscountAmt", _fmt_decimal(totals.discount_amt or Decimal("0")))
        _add_text_el(t_el, "TotAfterDisc", _fmt_decimal(totals.tot_after_disc))
    elif totals.total_lsum is not None:
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
    ids = _IdAllocator()
    boq_el = etree.SubElement(parent, "BoQ")
    boq_el.set("ID", ids.claim("B1", "B"))

    if boq.ref_boq_name:
        _add_text_el(boq_el, "RefBoQName", boq.ref_boq_name)
    if boq.ref_boq_id:
        _add_text_el(boq_el, "RefBoQID", boq.ref_boq_id)

    # QD keeps the <Type>/<Length> form for every version: its parser reads
    # only that shape (the procurement writer's _add_bkdn is the 3.x reference).
    for bkdn in boq.bkdn:
        bkdn_el = etree.SubElement(boq_el, "BoQBkdn")
        _add_text_el(bkdn_el, "Type", _bkdn_tag(bkdn.bkdn_type))
        _add_text_el(bkdn_el, "Length", str(bkdn.length))

    for ctlg in boq.catalogs:
        _add_catalog(boq_el, ctlg)

    _add_qty_boq_body(boq_el, boq.body, warnings, ids)

    for ca in boq.ctlg_assigns:
        _add_ctlg_assign(boq_el, ca)

    if boq.attachments:
        att_container = etree.SubElement(boq_el, "CtlgAttachment")
        for att in boq.attachments:
            _add_qty_attachment(att_container, att)


def _add_qty_boq_body(
    parent: etree._Element, body: QtyBoQBody, warnings: list[str], ids: _IdAllocator,
) -> None:
    body_el = etree.SubElement(parent, "BoQBody")

    for ctgy in body.categories:
        if ctgy.rno:
            _add_qty_boq_ctgy(body_el, ctgy, warnings, ids)
        else:
            itemlist_el = body_el.find("Itemlist")
            if itemlist_el is None:
                itemlist_el = etree.SubElement(body_el, "Itemlist")
            for item in ctgy.items:
                _add_qty_item(itemlist_el, item, ids)


def _add_qty_boq_ctgy(
    parent: etree._Element, ctgy: QtyBoQCtgy, warnings: list[str], ids: _IdAllocator,
) -> None:
    ctgy_el = etree.SubElement(parent, "BoQCtgy")
    # Keep the readable C_<rno> form; the allocator de-duplicates repeats.
    ctgy_el.set("ID", ids.claim(f"C_{ctgy.rno}", "C"))
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
                _add_qty_boq_ctgy(sub_body_el, sub, warnings, ids)

        if ctgy.items:
            itemlist_el = etree.SubElement(ctgy_el, "Itemlist")
            for item in ctgy.items:
                _add_qty_item(itemlist_el, item, ids)


def _add_qty_item(parent: etree._Element, item: QtyItem, ids: _IdAllocator) -> None:
    item_el = etree.SubElement(parent, "Item")
    # Same RNoPart can recur across categories, so I_<rno> alone is not unique.
    item_el.set("ID", ids.claim(f"I_{item.rno_part}", "I"))
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
