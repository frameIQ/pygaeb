"""``to_dataframe``: the ``to_csv`` table as a pandas DataFrame."""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pygaeb import GAEBParser, to_csv, to_dataframe
from pygaeb.convert._rows import DATE_COLUMNS, DECIMAL_COLUMNS, item_table
from pygaeb.models.document import GAEBDocument
from tests.document_kinds import DOCUMENT_KINDS

pd = pytest.importorskip("pandas")

FIXTURES = Path(__file__).parent / "fixtures"


def _parse(kind: str) -> GAEBDocument:
    xml, filename = DOCUMENT_KINDS[kind]
    return GAEBParser.parse_string(xml, filename=filename)


def _as_csv_text(value: Any) -> str:
    """A DataFrame cell written the way ``to_csv`` writes the same value."""
    if value is None or (not isinstance(value, (str, Decimal)) and pd.isna(value)):
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@pytest.mark.parametrize("kind", list(DOCUMENT_KINDS))
def test_every_document_kind_matches_its_csv(kind: str, tmp_path: Path) -> None:
    doc = _parse(kind)
    out = tmp_path / "items.csv"
    to_csv(doc, out)
    with out.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
        csv_columns = reader.fieldnames

    df = to_dataframe(doc, exact=True)
    assert list(df.columns) == csv_columns
    assert [
        {k: _as_csv_text(v) for k, v in row.items()} for row in df.to_dict("records")
    ] == csv_rows


def test_amounts_are_floats_that_rebuild_the_grand_total() -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    df = to_dataframe(doc)

    assert all(df[c].dtype == "float64" for c in df.columns if c in DECIMAL_COLUMNS)
    counted = df.loc[df["affects_total"], "total_price"].sum()
    assert round(counted, 2) == float(doc.grand_total) == 1755.0


def test_exact_keeps_decimals() -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    df = to_dataframe(doc, exact=True)

    assert isinstance(df["total_price"][0], Decimal)
    assert df.loc[df["affects_total"], "total_price"].sum() == Decimal("1755.00")


def test_typed_columns_keep_their_type_without_any_value() -> None:
    tender = to_dataframe(GAEBParser.parse(FIXTURES / "gaebxml.x83"))
    assert tender["markup_base"].isna().all()
    assert tender["markup_base"].dtype == "float64"

    trade = to_dataframe(_parse("X93 trade"))
    assert trade["delivery_date"].isna().all()
    assert pd.api.types.is_datetime64_any_dtype(trade["delivery_date"])


@pytest.mark.parametrize("kind", list(DOCUMENT_KINDS))
def test_every_decimal_and_date_column_is_declared(kind: str) -> None:
    # A new Decimal column left out of DECIMAL_COLUMNS would stay untyped in the DataFrame.
    for row in item_table(_parse(kind)).rows:
        for column, value in row.items():
            if isinstance(value, Decimal):
                assert column in DECIMAL_COLUMNS
            if isinstance(value, datetime):
                assert column in DATE_COLUMNS


def test_without_pandas_the_error_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pandas", None)
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")

    with pytest.raises(ImportError, match=r"pyGAEB\[pandas\]"):
        to_dataframe(doc)
