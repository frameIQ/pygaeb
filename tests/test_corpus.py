"""Real-file corpus run: every GAEB file in ``PYGAEB_CORPUS_DIR`` survives a round trip.

Each file is parsed, written back as DA XML 3.3 in its own exchange phase, and
parsed again; every item must come back with the same fields. Two more checks
per file: the written file passes the 3.3 schema (with ``PYGAEB_XSD_DIR`` set),
and the totals the file declares are the ones pyGAEB computes.

Real files carry copyrighted texts and personal data, so the corpus lives
outside the repository. One command gives a verdict per file and check::

    PYGAEB_CORPUS_DIR=~/gaeb-corpus PYGAEB_XSD_DIR=~/gaeb-xsd pytest tests/test_corpus.py -v
"""

from __future__ import annotations

import functools
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pygaeb import (
    ExchangePhase,
    GAEBDocument,
    GAEBParseError,
    GAEBParser,
    GAEBWriter,
    Item,
    SourceVersion,
)
from pygaeb.convert._rows import item_table
from pygaeb.parser.gaeb_parser import validate_xml
from pygaeb.validation import validate_totals

_CORPUS = os.environ.get("PYGAEB_CORPUS_DIR")
_XSD_DIR = os.environ.get("PYGAEB_XSD_DIR")

#: GAEB file names: DA XML ``.Xnn``, GAEB 90 ``.Dnn``, GAEB 2000 ``.Pnn`` (refused).
_GAEB_NAME = re.compile(r"\.[XDP]\d{2}[A-Z]?$", re.IGNORECASE)
#: Columns that are no part of the file: pyGAEB-only, or filled in by classification.
_NOT_COMPARED = frozenset({
    "bim_guid", "trade", "element_type", "sub_type",
    "classification_confidence", "classification_flag",
})
#: How many differences a failure lists before it stops.
_SHOWN = 25


def _corpus_root() -> Path:
    assert _CORPUS is not None
    return Path(_CORPUS).expanduser()


def _corpus_files() -> list[Any]:
    if not _CORPUS:
        return [pytest.param(None, marks=pytest.mark.skip(
            reason="set PYGAEB_CORPUS_DIR to a folder of real GAEB files",
        ))]
    root = _corpus_root()
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and _GAEB_NAME.search(p.name)
    )
    return [pytest.param(p, id=p.relative_to(root).as_posix()) for p in files]


_FILES = _corpus_files()


@functools.cache
def _parsed(path: Path) -> GAEBDocument:
    try:
        return GAEBParser.parse(path)
    except GAEBParseError as exc:
        if "not supported" in str(exc):
            pytest.skip(str(exc))
        raise


@functools.cache
def _written(path: Path) -> tuple[bytes, tuple[str, ...], ExchangePhase]:
    """The file written back as DA XML 3.3 in its own phase (a D-phase becomes X)."""
    doc = _parsed(path)
    phase = doc.exchange_phase.normalized()
    data, warnings = GAEBWriter.to_bytes(
        doc, phase=phase, target_version=SourceVersion.DA_XML_33,
    )
    return data, tuple(warnings), phase


def _key(row: dict[str, Any]) -> str:
    for column in ("full_oz", "item_id", "ele_no", "oz"):
        if row.get(column):
            index = row.get("rno_index")
            return f"{row[column]}[{index}]" if index else str(row[column])
    return "?"


def _rows(doc: GAEBDocument) -> list[dict[str, Any]]:
    """One row per item: the CSV export's columns, plus what a BoQ item adds."""
    table = item_table(doc)
    rows = [{c: v for c, v in row.items() if c not in _NOT_COMPARED} for row in table.rows]
    if doc.is_procurement:
        for row, item in zip(rows, doc.award.boq.iter_items(), strict=True):
            row.update(_procurement_extras(item))
    return rows


def _procurement_extras(item: Item) -> dict[str, Any]:
    return {
        "rno_index": item.rno_index,
        "qty_tbd": item.qty_tbd,
        "not_applicable": item.not_applicable,
        "alternative_group": item.alternative_group,
        "up_breakdown_required": item.up_breakdown_required,
        "vat": item.vat,
        "discount_pct": item.discount_pct,
        # Line breaks and indentation are layout; the words are content.
        "long_text": " ".join(item.long_text_plain.split()),
    }


def _same(a: object, b: object) -> bool:
    # Decimal("4.000") == Decimal("4"): the scale a writer chooses is not content.
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return a == b
    return a == b


def _differences(original: GAEBDocument, again: GAEBDocument) -> list[str]:
    found: list[str] = []
    if again.document_kind != original.document_kind:
        found.append(f"document kind {original.document_kind.value} → "
                     f"{again.document_kind.value}")
    rows_a, rows_b = _rows(original), _rows(again)
    keys_a, keys_b = [_key(r) for r in rows_a], [_key(r) for r in rows_b]
    if keys_a != keys_b:
        missing = [k for k in keys_a if k not in set(keys_b)]
        extra = [k for k in keys_b if k not in set(keys_a)]
        found.append(f"{len(rows_a)} items → {len(rows_b)}; lost {missing[:10]}, "
                     f"gained {extra[:10]}, or the order changed")
        return found
    for key, row_a, row_b in zip(keys_a, rows_a, rows_b, strict=True):
        for column, value in row_a.items():
            if not _same(value, row_b.get(column)):
                found.append(f"{key} {column}: {value!r} → {row_b.get(column)!r}")
    if not _same(original.grand_total, again.grand_total):
        found.append(f"grand total {original.grand_total} → {again.grand_total}")
    return found


def _report(differences: list[str], warnings: tuple[str, ...]) -> str:
    lines = differences[:_SHOWN]
    if len(differences) > _SHOWN:
        lines.append(f"… and {len(differences) - _SHOWN} more")
    if warnings:
        lines.append("writer warnings:")
        lines.extend(f"  {w}" for w in warnings[:10])
    return "\n".join(lines)


@pytest.mark.skipif(not _CORPUS, reason="set PYGAEB_CORPUS_DIR to a folder of real GAEB files")
def test_the_corpus_has_gaeb_files() -> None:
    root = _corpus_root()
    assert root.is_dir(), f"PYGAEB_CORPUS_DIR={_CORPUS} is not a folder"
    assert _FILES, f"no GAEB files (.Xnn, .Dnn, .Pnn) under {root}"


@pytest.mark.parametrize("path", _FILES)
def test_a_round_trip_keeps_every_item(path: Path) -> None:
    original = _parsed(path)
    data, warnings, phase = _written(path)
    again = GAEBParser.parse_bytes(data, filename=f"round-trip.{phase.value}")
    differences = _differences(original, again)
    assert not differences, _report(differences, warnings)


@pytest.mark.parametrize("path", _FILES)
def test_the_written_file_is_schema_valid(path: Path) -> None:
    if not (_XSD_DIR and Path(_XSD_DIR).is_dir()):
        pytest.skip("set PYGAEB_XSD_DIR to the 2021-05 schema folder")
    data, _, phase = _written(path)
    result = validate_xml(data, SourceVersion.DA_XML_33, phase, _XSD_DIR)
    if result is None:
        pytest.skip(f"no DA XML 3.3 schema for {phase.value} in PYGAEB_XSD_DIR")
    assert result.valid, "\n".join(
        f"line {e.line}: {e.message}" for e in result.errors[:_SHOWN]
    )


@pytest.mark.parametrize("path", _FILES)
def test_the_declared_totals_reproduce(path: Path) -> None:
    doc = _parsed(path)
    if doc.exchange_phase.normalized() is ExchangePhase.X84:
        pytest.skip("a bid restates neither the Zuordnungszahl nor the Bedarfsposition "
                    "markers, so only its tender can tell which positions count")
    mismatches = [r.message for r in validate_totals(doc)]
    assert not mismatches, "\n".join(mismatches)
