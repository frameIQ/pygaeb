"""Structural conformance of the 3.x procurement writer, checked without XSDs.

The official GAEB schemas cannot be bundled, so these pin the rules the schemas
impose — required IDs, element order, per-phase profiles, header layout — with
plain lxml assertions. ``tests/test_bvbs_conformance.py`` runs the same output
through the real schemas when they are available locally.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from pygaeb import ExchangePhase, GAEBParser, GAEBWriter, SourceVersion, __version__
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument
from pygaeb.models.enums import ItemType
from pygaeb.models.item import Attachment, Item
from pygaeb.writer.phase_profiles import GENERIC, PROFILES, profile_for

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic_33.X86"
LEGACY_32 = FIXTURES / "gaebxml.x83"

_NCNAME = re.compile(r"[^\W\d][\w.\-]*")


def _write(doc: GAEBDocument, phase: ExchangePhase, **kwargs) -> tuple[etree._Element, list[str]]:
    xml, warnings = GAEBWriter.to_bytes(doc, phase=phase, **kwargs)
    return etree.fromstring(xml), warnings


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _children(el: etree._Element) -> list[str]:
    return [_local(c) for c in el if not callable(c.tag)]


def _find_all(root: etree._Element, tag: str) -> list[etree._Element]:
    return [e for e in root.iter() if not callable(e.tag) and _local(e) == tag]


def _slot_of(tag: str) -> str:
    """Map an emitted element name onto its profile slot."""
    if tag in ("Provis", "LumpSumItem", "GlobItem", "AlternativeItem", "EventualItem",
               "TextItem", "SurchargeItem", "SupplementItem", "IndexItem"):
        return "TypeMarker"
    if tag.startswith("UPComp"):
        return "UPComp"
    if tag.startswith("LblUPComp"):
        return "LblUPComp"
    return tag


def _is_subsequence(seq: list[str], order: tuple[str, ...]) -> bool:
    pos = 0
    for slot in seq:
        try:
            pos = order.index(slot, pos)
        except ValueError:
            return False
    return True


@pytest.fixture(scope="module")
def synthetic() -> GAEBDocument:
    return GAEBParser.parse(SYNTHETIC)


@pytest.fixture
def bare_doc() -> GAEBDocument:
    """A programmatic document with no IDs, no BoQInfo, no parties."""
    items = [
        Item(oz="0010", short_text="Normal", qty=Decimal("2"), unit="m",
             unit_price=Decimal("10.00"), total_price=Decimal("20.00")),
        Item(oz="0020", short_text="Bedarf", qty=Decimal("1"), unit="St",
             unit_price=Decimal("5.00"), total_price=Decimal("5.00"),
             item_type=ItemType.EVENTUAL),
    ]
    ctgy = BoQCtgy(rno="01", label="Titel", items=items)
    lot = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy]))
    return GAEBDocument(
        exchange_phase=ExchangePhase.X86,
        award=AwardInfo(project_name="Bare", boq=BoQ(lots=[lot])),
    )


# --- header ---------------------------------------------------------------


class TestHeader:
    def test_gaeb_info_order_and_defaults(self, synthetic):
        root, _ = _write(synthetic, ExchangePhase.X86)
        info = _find_all(root, "GAEBInfo")[0]
        assert _children(info) == ["Version", "VersDate", "Date", "Time", "ProgSystem", "ProgName"]
        texts = {_local(c): c.text for c in info}
        assert texts["Version"] == "3.3"
        assert texts["VersDate"] == "2021-05"
        assert texts["Date"] == "2026-09-01"
        # ProgSystem names the generating software; ProgName keeps the source's.
        assert texts["ProgSystem"] == f"pyGAEB {__version__}"
        assert texts["ProgName"] == "pyGAEB"

    def test_header_overrides(self, synthetic):
        root, _ = _write(
            synthetic, ExchangePhase.X86, prog_system="FrameIQ 2.0", prog_name="FrameIQ",
        )
        texts = {_local(c): c.text for c in _find_all(root, "GAEBInfo")[0]}
        assert texts["ProgSystem"] == "FrameIQ 2.0"
        assert texts["ProgName"] == "FrameIQ"

    def test_vers_date_follows_target_version(self):
        doc = GAEBParser.parse(LEGACY_32)
        assert doc.gaeb_info.vers_date == "2013-10"
        as_33, _ = _write(doc, ExchangePhase.X83, target_version=SourceVersion.DA_XML_33)
        as_32, _ = _write(doc, ExchangePhase.X83, target_version=SourceVersion.DA_XML_32)
        assert _find_all(as_33, "VersDate")[0].text == "2021-05"
        assert _find_all(as_32, "VersDate")[0].text == "2013-10"

    @pytest.mark.parametrize("tag", ["ProgSystemVersion", "Prj", "PrjName", "PrcTyp", "ShortText"])
    def test_non_schema_elements_absent(self, synthetic, tag):
        root, _ = _write(synthetic, ExchangePhase.X86)
        assert not _find_all(root, tag)


# --- IDs ------------------------------------------------------------------


class TestIds:
    @pytest.mark.parametrize("phase", list(PROFILES))
    def test_every_structural_element_has_a_unique_ncname_id(self, synthetic, phase):
        root, _ = _write(synthetic, phase)
        ids = [
            e.get("ID") for e in root.iter()
            if not callable(e.tag) and _local(e) in ("BoQ", "BoQCtgy", "Item", "MarkupItem")
        ]
        assert ids and all(ids)
        assert len(ids) == len(set(ids))
        assert all(_NCNAME.fullmatch(i) for i in ids)

    def test_source_ids_are_preserved(self, synthetic):
        root, _ = _write(synthetic, ExchangePhase.X86)
        assert {e.get("ID") for e in _find_all(root, "Item")} == {"I1", "I2", "I3", "I4"}
        assert _find_all(root, "MarkupItem")[0].get("ID") == "M1"
        assert _find_all(root, "BoQ")[0].get("ID") == "B1"

    def test_generated_ids_are_deterministic(self, bare_doc):
        first, _ = GAEBWriter.to_bytes(bare_doc, phase=ExchangePhase.X86)
        second, _ = GAEBWriter.to_bytes(bare_doc, phase=ExchangePhase.X86)
        assert first == second
        root = etree.fromstring(first)
        assert [e.get("ID") for e in _find_all(root, "Item")] == ["I1", "I2"]
        assert _find_all(root, "BoQCtgy")[0].get("ID") == "C1"

    def test_duplicate_and_invalid_source_ids_are_replaced(self, bare_doc):
        items = bare_doc.award.boq.lots[0].body.categories[0].items
        items[0].id = "dup"
        items[1].id = "dup"
        bare_doc.award.boq.lots[0].body.categories[0].id = "1-starts-with-digit"
        root, _ = _write(bare_doc, ExchangePhase.X86)
        item_ids = [e.get("ID") for e in _find_all(root, "Item")]
        assert item_ids[0] == "dup" and item_ids[1] != "dup"
        assert _NCNAME.fullmatch(_find_all(root, "BoQCtgy")[0].get("ID"))

    def test_markup_reference_resolves_to_item_id(self, synthetic):
        root, _ = _write(synthetic, ExchangePhase.X86)
        ref = _find_all(root, "RefItem")[0]
        assert ref.get("IDRef") == "I1"
        assert not _find_all(root, "RefRNoPart")

    def test_unresolvable_markup_reference_is_not_written(self, synthetic):
        mu = next(i for i in synthetic.iter_items() if i.item_type == ItemType.MARKUP)
        mu.markup_sub_qtys[0].ref_id = None
        mu.markup_sub_qtys[0].ref_rno = "9999"
        try:
            root, warnings = _write(synthetic, ExchangePhase.X86)
        finally:
            mu.markup_sub_qtys[0].ref_id = "I1"
            mu.markup_sub_qtys[0].ref_rno = "0010"
        assert not _find_all(root, "MarkupSubQty")
        assert any("does not resolve" in w for w in warnings)


# --- breakdown, labels, markers ------------------------------------------


class TestBreakdownAndLabels:
    def test_bkdn_sibling_form_with_label_num_alignment(self, synthetic):
        root, _ = _write(synthetic, ExchangePhase.X86)
        levels = [_children(b) for b in _find_all(root, "BoQBkdn")]
        assert levels == [
            ["Type", "LblBoQBkdn", "Length", "Num"],
            ["Type", "LblBoQBkdn", "Length", "Num"],
            ["Type", "Length", "Num", "Alignment"],
        ]
        index = _find_all(root, "BoQBkdn")[2]
        assert {_local(c): c.text for c in index} == {
            "Type": "Index", "Length": "1", "Num": "No", "Alignment": "left",
        }

    def test_bkdn_round_trips(self, synthetic):
        xml, _ = GAEBWriter.to_bytes(synthetic, phase=ExchangePhase.X86)
        again = GAEBParser.parse_bytes(xml, filename="again.X86")
        key = lambda b: (b.bkdn_type, b.length, b.label, b.num, b.alignment)  # noqa: E731
        assert [key(b) for b in again.award.boq.boq_info.bkdn] == [
            key(b) for b in synthetic.award.boq.boq_info.bkdn
        ]

    def test_lbl_tx_is_formatted_text(self, synthetic, bare_doc):
        root, _ = _write(synthetic, ExchangePhase.X86)
        lbl = _find_all(root, "LblTx")[0]
        assert _children(lbl) == ["p"] and _children(lbl[0]) == ["span"]
        assert lbl[0][0].text == "Erdarbeiten"

        bare_doc.award.boq.lots[0].body.categories[0].label = ""
        root, _ = _write(bare_doc, ExchangePhase.X86)
        empty = _find_all(root, "LblTx")[0]
        assert len(empty) == 0 and not (empty.text or "").strip()

    def test_markers_carry_schema_values(self, synthetic):
        root, _ = _write(synthetic, ExchangePhase.X86)
        assert _find_all(root, "Provis")[0].text == "WithTotal"
        assert _find_all(root, "LumpSumItem")[0].text == "Yes"

    def test_lump_sum_no_is_not_a_marker(self):
        xml = SYNTHETIC.read_bytes().replace(
            b"<LumpSumItem>Yes</LumpSumItem>", b"<LumpSumItem>No</LumpSumItem>",
        )
        doc = GAEBParser.parse_bytes(xml, filename="x.X86")
        assert doc.award.boq.get_item("0030").item_type == ItemType.NORMAL

    def test_up_component_labels_carry_type(self, synthetic):
        root, _ = _write(synthetic, ExchangePhase.X86)
        assert _find_all(root, "LblUPComp1")[0].get("Type") == "Wages"
        assert _find_all(root, "LblUPComp2")[0].get("Type") == "Materials"

    def test_change_order_needs_status(self, synthetic, bare_doc):
        root, _ = _write(synthetic, ExchangePhase.X86)
        item = next(e for e in _find_all(root, "Item") if e.get("RNoIndex") == "A")
        assert _children(item)[:2] == ["CONo", "COStatus"]

        bare_doc.award.boq.lots[0].body.categories[0].items[0].change_order_number = "NT-2"
        root, warnings = _write(bare_doc, ExchangePhase.X86)
        assert not _find_all(root, "CONo")
        assert any("COStatus" in w and "dropped" in w for w in warnings)


# --- per-phase profiles ---------------------------------------------------


class TestPhaseProfiles:
    @pytest.mark.parametrize("phase", list(PROFILES))
    def test_children_follow_schema_order(self, synthetic, phase):
        profile = profile_for(phase)
        root, _ = _write(synthetic, phase)
        checks = [
            ("Award", profile.award), ("AwardInfo", profile.award_info),
            ("PrjInfo", profile.prj_info), ("BoQInfo", profile.boq_info),
            ("BoQCtgy", profile.boq_ctgy), ("Item", profile.item),
            ("MarkupItem", profile.markup_item),
        ]
        for tag, slots in checks:
            for el in _find_all(root, tag):
                seq = [_slot_of(c) for c in _children(el)]
                assert _is_subsequence(seq, slots.order), f"{phase.value} {tag}: {seq}"

    def test_unknown_phase_uses_generic_profile(self):
        assert profile_for(ExchangePhase.X89) is GENERIC
        assert profile_for(ExchangePhase.D83) is PROFILES[ExchangePhase.X83]

    def test_x83_has_no_prices_and_requires_units(self, synthetic, bare_doc):
        root, warnings = _write(synthetic, ExchangePhase.X83)
        for tag in ("UP", "IT", "Totals", "UPComp1", "ITMarkup", "Markup", "CTR"):
            assert not _find_all(root, tag), tag
        assert all("QU" in _children(i) for i in _find_all(root, "Item"))
        assert any("UP not written" in w and "X83" in w for w in warnings)

        item = bare_doc.award.boq.lots[0].body.categories[0].items[0]
        item.qty_tbd = True
        item.unit = None
        root, warnings = _write(bare_doc, ExchangePhase.X83)
        first = _find_all(root, "Item")[0]
        assert "QtyTBD" in _children(first) and "Qty" not in _children(first)
        assert _find_all(root, "QU")[0].text in (None, "")
        assert any("QU is required" in w for w in warnings)

    def test_x84_bid_shape(self, synthetic, bare_doc):
        root, warnings = _write(synthetic, ExchangePhase.X84)
        assert not _find_all(root, "LblTx")
        assert not _find_all(root, "OWN")
        assert not _find_all(root, "Provis") and not _find_all(root, "LumpSumItem")
        assert not _find_all(root, "OutlineText")
        assert not _find_all(root, "QtySplit") and not _find_all(root, "QU")
        assert all("Totals" in _children(c) for c in _find_all(root, "BoQCtgy"))
        assert _children(_find_all(root, "Award")[0]) == ["DP", "AwardInfo", "CTR", "BoQ"]
        assert any("position marker not written" in w for w in warnings)

        # No contractor on the model: X84 still needs a CTR block.
        root, warnings = _write(bare_doc, ExchangePhase.X84)
        ctr = _find_all(root, "CTR")[0]
        assert _children(ctr[0]) == ["Name1", "Street", "PCode", "City"]
        assert any("CTR is required in X84" in w for w in warnings)

    def test_x86_requires_parties_and_totals(self, bare_doc):
        root, warnings = _write(bare_doc, ExchangePhase.X86)
        assert _children(_find_all(root, "Award")[0]) == ["DP", "AwardInfo", "OWN", "CTR", "BoQ"]
        totals = _find_all(_find_all(root, "BoQCtgy")[0], "Totals")
        # Provis defaults to WithoutTotal, so only the normal item is summed.
        assert totals and totals[0][0].text == "20.00"
        assert sum("required in X86" in w for w in warnings) == 2

    def test_x86_synthesises_boq_info_and_totals_only_when_missing(self, synthetic):
        root, warnings = _write(synthetic, ExchangePhase.X86)
        info = _find_all(root, "BoQInfo")[0]
        assert _children(info)[:4] == ["Name", "LblBoQ", "Date", "OutlCompl"]
        assert _find_all(_find_all(root, "BoQCtgy")[0], "Totals")[0][0].text == "1655.00"
        assert not any("required" in w for w in warnings)

    def test_invented_elements_are_gone(self, bare_doc):
        item = bare_doc.award.boq.lots[0].body.categories[0].items[0]
        item.attachments = [Attachment(filename="a.pdf", mime_type="application/pdf", data=b"x")]
        item.bim_guid = "abc"
        root, warnings = _write(bare_doc, ExchangePhase.X86)
        assert not _find_all(root, "Attachment") and not _find_all(root, "GUID")
        assert any("Item.attachments not written" in w for w in warnings)
        assert any("GUID not written" in w for w in warnings)

    def test_multi_lot_wrappers(self, multi_lot_document):
        root, _ = _write(multi_lot_document, ExchangePhase.X86)
        lots = [c for c in _find_all(root, "BoQBody")[0] if _local(c) == "BoQCtgy"]
        assert [lot.get("RNoPart") for lot in lots] == ["1", "2"]
        for lot in lots:
            assert lot.get("ID") and _NCNAME.fullmatch(lot.get("ID"))
            assert _children(lot) == ["LblTx", "BoQBody", "Totals"]

    def test_2x_output_keeps_its_dialect(self, synthetic):
        xml, _ = GAEBWriter.to_bytes(
            synthetic, phase=ExchangePhase.X83, target_version=SourceVersion.DA_XML_20,
        )
        text = xml.decode()
        assert "<Kurztext>" in text
        assert "<LVGliederung>" in text and '<OZEbene Length="2"' in text
        assert 'ID="' not in text


# --- round trip through the synthetic fixture -----------------------------


class TestSyntheticRoundTrip:
    def test_model_survives_x86_round_trip(self, synthetic):
        xml, _ = GAEBWriter.to_bytes(synthetic, phase=ExchangePhase.X86)
        again = GAEBParser.parse_bytes(xml, filename="again.X86")

        assert again.item_count == synthetic.item_count
        before = {i.full_oz + (i.rno_index or ""): i for i in synthetic.iter_items()}
        after = {i.full_oz + (i.rno_index or ""): i for i in again.iter_items()}
        assert before.keys() == after.keys()
        for key, item in before.items():
            other = after[key]
            assert other.item_type == item.item_type
            assert other.provis == item.provis
            assert other.qty == item.qty and other.unit_price == item.unit_price
            assert [s.qty for s in other.qty_splits] == [s.qty for s in item.qty_splits]
            assert other.short_text == item.short_text
            assert other.id == item.id

        assert again.award.contractor is not None
        assert again.award.contractor.address.name == "Musterbau GmbH"
        assert again.award.contractor.bidder_no == "7"
        assert again.award.owner_address.name == "Musterbauamt"
        assert again.award.boq.boq_info.outl_compl == "AllTxt"
        assert again.award.boq.boq_info.lbl_up_comp_types == ["Wages", "Materials"]

    def test_second_write_is_byte_identical(self, synthetic):
        first, _ = GAEBWriter.to_bytes(synthetic, phase=ExchangePhase.X86)
        again = GAEBParser.parse_bytes(first, filename="again.X86")
        second, _ = GAEBWriter.to_bytes(again, phase=ExchangePhase.X86)
        assert first == second
