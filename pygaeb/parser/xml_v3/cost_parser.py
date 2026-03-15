"""Cost phase parser (X50, X51) — reads <ElementalCosting> structure.

Inherits shared XML helpers from BaseV3Parser but replaces the Award/BoQ
parsing with elemental costing (ECBody / ECCtgy / CostElement hierarchy).
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from pygaeb.models.cost import (
    BoQCtgyRef,
    BoQItemRef,
    CategoryElement,
    CategoryElementRef,
    ConsortiumMember,
    ConsortiumMemberRef,
    CostElement,
    CostElementRef,
    CostProperty,
    DimensionElement,
    DimensionElementRef,
    ECBkdn,
    ECBody,
    ECCtgy,
    ECInfo,
    ElementalCosting,
    RefGroup,
)
from pygaeb.models.document import GAEBDocument
from pygaeb.parser.recovery import parse_xml_safe
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser
from pygaeb.parser.xml_v3.richtext_parser import parse_richtext

logger = logging.getLogger("pygaeb.parser")


class CostParser(BaseV3Parser):
    """Parser for GAEB cost phases (X50, X51).

    These phases use ``<ElementalCosting>`` instead of ``<Award>`` and contain
    a recursive tree of ``<ECCtgy>`` / ``<CostElement>`` instead of a BoQ.
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
        doc.elemental_costing = self._parse_elemental_costing(root, doc)

        if self._keep_xml:
            doc.xml_root = root

        return doc

    def _parse_elemental_costing(
        self, root: etree._Element, doc: GAEBDocument,
    ) -> ElementalCosting:
        ec = ElementalCosting()

        ec_el = self._find(root, "ElementalCosting")
        if ec_el is None:
            doc.add_warning("No ElementalCosting element found")
            return ec

        dp = self._text(ec_el, "DP")
        if dp:
            ec.dp = dp

        ec_info_el = self._find(ec_el, "ECInfo")
        if ec_info_el is not None:
            ec.ec_info = self._parse_ec_info(ec_info_el)

        ec_body_el = self._find(ec_el, "ECBody")
        if ec_body_el is not None:
            ec.body = self._parse_ec_body(ec_body_el, doc)

        if self._keep_xml:
            ec.source_element = ec_el

        return ec

    def _parse_ec_info(self, el: etree._Element) -> ECInfo:
        info = ECInfo()
        info.name = self._text(el, "Name") or ""
        info.label = self._text(el, "LblEC") or ""
        info.ec_type = self._text(el, "ECType")
        info.ec_method = self._text(el, "ECMethod")

        date_str = self._text(el, "Date")
        if date_str:
            info.date = _parse_date(date_str)

        info.currency = self._text(el, "Cur")
        info.currency_label = self._text(el, "CurLbl")

        dop_str = self._text(el, "DateOfPrice")
        if dop_str:
            info.date_of_price = _parse_date(dop_str)

        doi_el = self._find(el, "DateOfInformation")
        if doi_el is not None:
            doi_date = self._text(doi_el, "Date")
            if doi_date:
                info.date_of_information = _parse_date(doi_date)

        for bkdn_el in self._findall(el, "ECBkdn"):
            bkdn = ECBkdn()
            bkdn.bkdn_type = self._text(bkdn_el, "Type") or ""
            bkdn.label = self._text(bkdn_el, "LblOutline") or ""
            length_str = self._text(bkdn_el, "Length")
            if length_str:
                with contextlib.suppress(ValueError):
                    bkdn.length = int(length_str)
            num_str = self._text(bkdn_el, "Num")
            if num_str and num_str.lower() in ("yes", "true", "1"):
                bkdn.is_numeric = True
            info.breakdowns.append(bkdn)

        for cm_el in self._findall(el, "ConsortiumMember"):
            cm = ConsortiumMember()
            cm.description = self._text(cm_el, "Description") or ""
            addr_el = self._find(cm_el, "Address")
            if addr_el is not None:
                cm.name = self._text(addr_el, "Name") or ""
                cm.street = self._text(addr_el, "Street") or ""
                cm.pcode = self._text(addr_el, "PCode") or ""
                cm.city = self._text(addr_el, "City") or ""
                cm.country = self._text(addr_el, "Country") or ""
            info.consortium_members.append(cm)

        totals_el = self._find(el, "Totals")
        if totals_el is not None:
            net = self._text(totals_el, "TotalNet")
            if net:
                info.totals_net = _parse_decimal(net)
            gross = self._text(totals_el, "TotalGross")
            if gross:
                info.totals_gross = _parse_decimal(gross)

        return info

    def _parse_ec_body(self, el: etree._Element, doc: GAEBDocument) -> ECBody:
        body = ECBody()

        for ctgy_el in self._findall(el, "ECCtgy"):
            ctgy = self._parse_ec_ctgy(ctgy_el, doc)
            body.categories.append(ctgy)

        for ce_el in self._findall(el, "CostElement"):
            ce = self._parse_cost_element(ce_el, doc)
            body.cost_elements.append(ce)

        for de_el in self._findall(el, "DimensionElement"):
            de = self._parse_dimension_element(de_el)
            body.dimension_elements.append(de)

        for cat_el in self._findall(el, "CategoryElement"):
            cat = self._parse_category_element(cat_el)
            body.category_elements.append(cat)

        return body

    def _parse_ec_ctgy(self, el: etree._Element, doc: GAEBDocument) -> ECCtgy:
        ctgy = ECCtgy()
        ctgy.ele_no = self._text(el, "EleNo") or ""
        ctgy.description = self._text(el, "Descr") or ""

        portion_str = self._text(el, "Portion")
        if portion_str:
            ctgy.portion = _parse_decimal(portion_str)

        for prop_el in self._findall(el, "Property"):
            ctgy.properties.append(self._parse_property(prop_el))

        ec_body_el = self._find(el, "ECBody")
        if ec_body_el is not None:
            ctgy.body = self._parse_ec_body(ec_body_el, doc)

        totals_el = self._find(el, "Totals")
        if totals_el is not None:
            net = self._text(totals_el, "TotalNet")
            if net:
                ctgy.totals_net = _parse_decimal(net)
            gross = self._text(totals_el, "TotalGross")
            if gross:
                ctgy.totals_gross = _parse_decimal(gross)

        if self._keep_xml:
            ctgy.source_element = el

        return ctgy

    def _parse_cost_element(self, el: etree._Element, doc: GAEBDocument) -> CostElement:
        ce = CostElement()
        ce.ele_no = self._text(el, "EleNo") or ""

        descr = self._text(el, "Descr")
        if descr:
            ce.short_text = descr

        ce.cat_id = self._text(el, "CatID")

        desc_el = self._find(el, "Description")
        if desc_el is not None:
            st = self._extract_outline_text(el)
            if st and not ce.short_text:
                ce.short_text = st

            detail_el = self._find(desc_el, "CompleteText", "DetailTxt")
            if detail_el is not None:
                html = etree.tostring(detail_el, encoding="unicode", method="html")
                ce.long_text = parse_richtext(html)

            if not ce.long_text:
                outline_el = self._find(desc_el, "OutlineText")
                if outline_el is not None:
                    html = etree.tostring(outline_el, encoding="unicode", method="html")
                    rt = parse_richtext(html)
                    if rt and rt.plain_text and not ce.short_text:
                        ce.short_text = rt.plain_text

        ce.remark = self._text(el, "Remark") or ""

        qty_str = self._text(el, "Qty")
        if qty_str:
            ce.qty = _parse_decimal(qty_str)

        ce.unit = self._text(el, "QU")

        up_str = self._text(el, "UP")
        if up_str:
            ce.unit_price = _parse_decimal(up_str)

        it_str = self._text(el, "IT")
        if it_str:
            ce.item_total = _parse_decimal(it_str)

        markup_str = self._text(el, "Markup")
        if markup_str:
            ce.markup = _parse_decimal(markup_str)

        for price_tag, attr in [("UPFrom", "up_from"), ("UPAvg", "up_avg"), ("UPTo", "up_to")]:
            val = self._text(el, price_tag)
            if val:
                setattr(ce, attr, _parse_decimal(val))

        bill_el = self._find(el, "BillElement")
        if bill_el is not None:
            text = (bill_el.text or "").strip().lower()
            ce.is_bill_element = text in ("yes", "true", "1")

        for prop_el in self._findall(el, "Property"):
            ce.properties.append(self._parse_property(prop_el))

        for rg_el in self._findall(el, "RefGroup"):
            ce.ref_groups.append(self._parse_ref_group(rg_el))

        for child_el in self._findall(el, "CostElement"):
            ce.children.append(self._parse_cost_element(child_el, doc))

        if self._keep_xml:
            ce.source_element = el

        return ce

    def _parse_property(self, el: etree._Element) -> CostProperty:
        prop = CostProperty()
        prop.name = self._text(el, "Name") or ""
        prop.label = self._text(el, "LblProp") or ""
        prop.arithmetic_qty_approach = self._text(el, "ArithmeticQuantityApproach")

        val_str = self._text(el, "ValueQuantityApproach")
        if val_str:
            prop.value_qty_approach = _parse_decimal(val_str)

        prop.unit = self._text(el, "QU") or ""
        prop.prop_type = self._text(el, "Type")
        prop.cad_id = self._text(el, "CAD_ID")

        return prop

    def _parse_ref_group(self, el: etree._Element) -> RefGroup:
        rg = RefGroup()
        rg.title = self._text(el, "Title") or ""

        for ref_el in self._findall(el, "BoQItemRef"):
            bi_ref = BoQItemRef(
                id_ref=ref_el.get("IDRef", ""),
                ref_type=ref_el.get("Type"),
            )
            portion_str = self._text(ref_el, "Portion")
            if portion_str:
                bi_ref.portion = _parse_decimal(portion_str)
            rg.boq_item_refs.append(bi_ref)

        for ref_el in self._findall(el, "BoQCtgyRef"):
            bc_ref = BoQCtgyRef(
                id_ref=ref_el.get("IDRef", ""),
                ref_type=ref_el.get("Type"),
            )
            portion_str = self._text(ref_el, "Portion")
            if portion_str:
                bc_ref.portion = _parse_decimal(portion_str)
            rg.boq_ctgy_refs.append(bc_ref)

        for ref_el in self._findall(el, "CostElementRef"):
            ce_ref = CostElementRef(
                id_ref=ref_el.get("IDRef", ""),
                ref_type=ref_el.get("Type"),
            )
            portion_str = self._text(ref_el, "Portion")
            if portion_str:
                ce_ref.portion = _parse_decimal(portion_str)
            rg.cost_element_refs.append(ce_ref)

        for ref_el in self._findall(el, "DimensionElementRef"):
            de_ref = DimensionElementRef(
                id_ref=ref_el.get("IDRef", ""),
                ref_type=ref_el.get("Type"),
            )
            portion_str = self._text(ref_el, "Portion")
            if portion_str:
                de_ref.portion = _parse_decimal(portion_str)
            rg.dimension_element_refs.append(de_ref)

        for ref_el in self._findall(el, "CategoryElementRef"):
            cat_ref = CategoryElementRef(
                id_ref=ref_el.get("IDRef", ""),
                ref_type=ref_el.get("Type"),
            )
            portion_str = self._text(ref_el, "Portion")
            if portion_str:
                cat_ref.portion = _parse_decimal(portion_str)
            rg.category_element_refs.append(cat_ref)

        for ref_el in self._findall(el, "ConsortiumMemberRef"):
            cm_ref = ConsortiumMemberRef(id_ref=ref_el.get("IDRef", ""))
            rg.consortium_member_refs.append(cm_ref)

        return rg

    def _parse_dimension_element(self, el: etree._Element) -> DimensionElement:
        de = DimensionElement()
        de.ele_no = self._text(el, "EleNo") or ""
        de.description = self._text(el, "Descr") or ""
        de.cat_id = self._text(el, "CatID")
        de.remark = self._text(el, "Remark") or ""

        qty_str = self._text(el, "Qty")
        if qty_str:
            de.qty = _parse_decimal(qty_str)
        de.unit = self._text(el, "QU") or ""

        markup_str = self._text(el, "Markup")
        if markup_str:
            de.markup = _parse_decimal(markup_str)

        for prop_el in self._findall(el, "Property"):
            de.properties.append(self._parse_property(prop_el))

        if self._keep_xml:
            de.source_element = el

        return de

    def _parse_category_element(self, el: etree._Element) -> CategoryElement:
        cat = CategoryElement()
        cat.ele_no = self._text(el, "EleNo") or ""
        cat.description = self._text(el, "Descr") or ""
        cat.cat_id = self._text(el, "CatID")
        cat.remark = self._text(el, "Remark") or ""

        markup_str = self._text(el, "Markup")
        if markup_str:
            cat.markup = _parse_decimal(markup_str)

        for prop_el in self._findall(el, "Property"):
            cat.properties.append(self._parse_property(prop_el))

        if self._keep_xml:
            cat.source_element = el

        return cat


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
