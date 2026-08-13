"""Regression tests for issue #34.

Document metadata was dropped on write. Three separate causes: fields parsed but
never written (`VersDate`), fields written but overwritten with a fresh value
(`Date`), and fields the model never held at all (`Time`, `BoQID`, the
unit-price component labels, `Num`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from pygaeb import GAEBParser, GAEBWriter, SourceVersion

FIXTURE = Path(__file__).parent / "fixtures" / "gaebxml.x83"


@pytest.fixture(scope="module")
def parsed():
    return GAEBParser().parse(str(FIXTURE))


@pytest.fixture(scope="module")
def written(parsed) -> str:
    return GAEBWriter().to_bytes(parsed, target_version=SourceVersion.DA_XML_32)[0].decode()


@pytest.fixture(scope="module")
def reparsed(written):
    return GAEBParser().parse_string(written)


def _texts(xml: str, tag: str) -> list[str]:
    root = etree.fromstring(xml.encode())
    return [
        (e.text or "").strip()
        for e in root.iter()
        if etree.QName(e).localname == tag
    ]


# --- parsed into the model --------------------------------------------------


def test_gaeb_info_metadata_parsed(parsed):
    info = parsed.gaeb_info
    assert info.vers_date == "2013-10"
    assert info.time == "09:15:42"
    assert info.prog_name == "pyGAEB Fixture Builder V1.0.0"
    assert info.date is not None and info.date.strftime("%Y-%m-%d") == "2026-08-13"


def test_boq_id_parsed(parsed):
    assert parsed.award.boq_id == "3f2a91c4-7d18-4b6e-9a05-1c8e4d720b3f"


def test_up_component_labels_parsed(parsed):
    info = parsed.award.boq.boq_info
    assert info.no_up_comps == 2
    assert info.lbl_up_comps == ["Material", "Geräte"]
    assert info.lbl_time == "Lohn"
    assert info.date == "2026-08-13"


def test_bkdn_num_flag_parsed(parsed):
    assert [b.num for b in parsed.award.boq.boq_info.bkdn] == [True, True, True]


# --- written back -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("DP", ["83"]),
        ("VersDate", ["2013-10"]),
        ("Time", ["09:15:42"]),
        ("ProgName", ["pyGAEB Fixture Builder V1.0.0"]),
        ("BoQID", ["3f2a91c4-7d18-4b6e-9a05-1c8e4d720b3f"]),
        ("NoUPComps", ["2"]),
        ("LblUPComp1", ["Material"]),
        ("LblUPComp2", ["Geräte"]),
        ("LblTime", ["Lohn"]),
        ("Num", ["Yes", "Yes", "Yes"]),
    ],
)
def test_metadata_written(written, tag, expected):
    assert _texts(written, tag) == expected


def test_source_date_is_preserved_not_restamped(written):
    """The writer used to stamp datetime.now() over the document's own date."""
    assert "2026-08-13" in _texts(written, "Date")


def test_currency_label_written_in_both_places(written):
    assert len(_texts(written, "CurLbl")) == 2


# --- round trip -------------------------------------------------------------


def test_metadata_survives_round_trip(parsed, reparsed):
    assert reparsed.gaeb_info.vers_date == parsed.gaeb_info.vers_date
    assert reparsed.gaeb_info.time == parsed.gaeb_info.time
    assert reparsed.gaeb_info.prog_name == parsed.gaeb_info.prog_name
    assert reparsed.award.boq_id == parsed.award.boq_id
    assert reparsed.award.currency_label == parsed.award.currency_label

    before, after = parsed.award.boq.boq_info, reparsed.award.boq.boq_info
    assert after.no_up_comps == before.no_up_comps
    assert after.lbl_up_comps == before.lbl_up_comps
    assert after.lbl_time == before.lbl_time
    assert after.date == before.date
    assert [b.num for b in after.bkdn] == [b.num for b in before.bkdn]


def test_num_survives_round_trip_in_the_33_shape(parsed):
    """3.3 spells the flag as an attribute, not a child element."""
    xml = GAEBWriter().to_bytes(parsed, target_version=SourceVersion.DA_XML_33)[0].decode()
    root = etree.fromstring(xml.encode())
    levels = [
        e for e in root.iter()
        if etree.QName(e).localname in ("BoQLevel", "Item")
        and e.getparent() is not None
        and etree.QName(e.getparent()).localname == "BoQBkdn"
    ]
    assert levels and all(e.get("Num") == "Yes" for e in levels)

    again = GAEBParser().parse_string(xml)
    assert [b.num for b in again.award.boq.boq_info.bkdn] == [True, True, True]


def test_prog_name_no_longer_renamed(parsed, written):
    """ProgName used to be folded into prog_system_version and written as that."""
    assert _texts(written, "ProgName") == ["pyGAEB Fixture Builder V1.0.0"]
    assert parsed.gaeb_info.prog_system_version != parsed.gaeb_info.prog_name
