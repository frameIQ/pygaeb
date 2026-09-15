"""BVBS certification round trips against the official GAEB DA XML 3.3 XSDs.

Mirrors the export steps of the BVBS Prüfkriterien (AVA, Bauausführung,
Texterstellung): read a BVBS Prüfdatei, write the phase the exam asks for,
and validate the result against that phase's schema.

The Prüfdateien and the XSDs are copyrighted and not part of the repository.
Point ``PYGAEB_BVBS_FIXTURES`` at a folder holding the BVBS 3.3 files as
``ava/tender.X81`` etc. and ``PYGAEB_XSD_DIR`` at the ``2021-05`` schema
folder; without both, every test here is skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from lxml import etree

from pygaeb import ExchangePhase, GAEBParser, GAEBWriter, SourceVersion, __version__
from pygaeb.parser.gaeb_parser import validate_xml

_FIXTURES = os.environ.get("PYGAEB_BVBS_FIXTURES")
_XSD_DIR = os.environ.get("PYGAEB_XSD_DIR")

pytestmark = pytest.mark.skipif(
    not (_FIXTURES and Path(_FIXTURES).is_dir() and _XSD_DIR and Path(_XSD_DIR).is_dir()),
    reason="set PYGAEB_BVBS_FIXTURES and PYGAEB_XSD_DIR to run the BVBS conformance matrix",
)

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic_33.X86"

# (source file relative to PYGAEB_BVBS_FIXTURES, phase to export) — one row per
# export step in the Prüfkriterien.
CASES: list[tuple[str, ExchangePhase]] = [
    ("ava/tender.X81", ExchangePhase.X81),            # AVA 2.1
    ("ava/award.X86", ExchangePhase.X86),             # AVA 3.2
    ("ava/award.X86", ExchangePhase.X84),             # AVA 3.3
    ("ava/award.X86", ExchangePhase.X83),             # AVA 3.4
    ("ava/tender.X81", ExchangePhase.X83),
    ("construction/bid.X83", ExchangePhase.X84),      # Bauausführung 1.22
    ("construction/bid.X83", ExchangePhase.X83),
    ("construction/alt_bid.X84", ExchangePhase.X84),
    ("text_creation/tender.X81", ExchangePhase.X81),  # Texterstellung 2.1
    ("text_creation/tender.X81", ExchangePhase.X83),
    ("text_creation/negotiation.X82", ExchangePhase.X82),
]
SYNTHETIC_CASES = [ExchangePhase.X81, ExchangePhase.X83, ExchangePhase.X84, ExchangePhase.X86]
_ID_BEARERS = frozenset({"BoQ", "BoQCtgy", "Item", "MarkupItem", "Remark", "PerfDescr"})


def _ids(xml: bytes) -> list[str]:
    root = etree.fromstring(xml)
    return [
        e.get("ID") for e in root.iter()
        if not callable(e.tag)
        and etree.QName(e).localname in _ID_BEARERS
    ]


def _header(xml: bytes) -> dict[str, str | None]:
    root = etree.fromstring(xml)
    info = next(e for e in root if etree.QName(e).localname == "GAEBInfo")
    return {etree.QName(c).localname: c.text for c in info}


def _assert_valid(xml: bytes, phase: ExchangePhase, label: str) -> None:
    result = validate_xml(xml, SourceVersion.DA_XML_33, phase, _XSD_DIR)
    assert result is not None, f"no schema for {phase.value} under {_XSD_DIR}"
    if not result.valid:
        head = "\n".join(f"  L{e.line}: {e.message}" for e in result.errors[:10])
        pytest.fail(f"{label} -> {phase.value}: {len(result.errors)} schema error(s)\n{head}")


@pytest.mark.parametrize(("source", "phase"), CASES, ids=[f"{s}->{p.value}" for s, p in CASES])
def test_bvbs_export_validates(source: str, phase: ExchangePhase) -> None:
    path = Path(_FIXTURES or "") / source
    if not path.exists():
        pytest.skip(f"{source} not present")

    doc = GAEBParser.parse(path)
    _assert_valid(path.read_bytes(), doc.exchange_phase, f"source {source}")

    xml, _ = GAEBWriter.to_bytes(doc, phase=phase)
    _assert_valid(xml, phase, source)

    header = _header(xml)
    assert header["Version"] == "3.3"
    assert header["VersDate"] == "2021-05"
    assert header["ProgSystem"] == f"pyGAEB {__version__}"

    ids = _ids(xml)
    assert len(ids) == len(set(ids)) and all(ids)

    again = GAEBParser.parse_bytes(xml, filename=f"again.{phase.value}")
    assert again.item_count == doc.item_count

    key = lambda b: (b.bkdn_type, b.length, b.label, b.num, b.alignment)  # noqa: E731
    assert [key(b) for b in again.award.boq.boq_info.bkdn] == [
        key(b) for b in doc.award.boq.boq_info.bkdn
    ]

    if phase != ExchangePhase.X84:
        assert [i.provis for i in again.iter_items()] == [i.provis for i in doc.iter_items()]
    if phase == doc.exchange_phase:
        source_ids = {
            i.id for i in doc.iter_items() if i.id
        }
        assert source_ids <= set(ids)

    second, _ = GAEBWriter.to_bytes(again, phase=phase)
    assert second == xml


@pytest.mark.parametrize("phase", SYNTHETIC_CASES, ids=[p.value for p in SYNTHETIC_CASES])
def test_synthetic_fixture_validates(phase: ExchangePhase) -> None:
    doc = GAEBParser.parse(SYNTHETIC)
    _assert_valid(SYNTHETIC.read_bytes(), ExchangePhase.X86, "synthetic source")
    xml, _ = GAEBWriter.to_bytes(doc, phase=phase)
    _assert_valid(xml, phase, "synthetic")
