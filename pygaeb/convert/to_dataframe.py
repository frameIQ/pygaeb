"""Export GAEBDocument items to a pandas DataFrame: the CSV table, in memory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pygaeb.convert._rows import DATE_COLUMNS, DECIMAL_COLUMNS, FLOAT_COLUMNS, item_table
from pygaeb.models.document import GAEBDocument

if TYPE_CHECKING:
    import pandas as pd


def to_dataframe(doc: GAEBDocument, *, exact: bool = False) -> pd.DataFrame:
    """One row per item, with the columns ``to_csv`` writes for the document's kind.

    Amounts are floats, so sums, ``describe()`` and plots work as usual; a sum can
    show a binary remainder such as ``1755.0000000000002`` until it is rounded.
    Pass ``exact=True`` to keep pyGAEB's ``Decimal`` values for cent-exact work.

    Requires pandas: ``pip install pyGAEB[pandas]``.
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError(
            "DataFrame export requires pandas. Install with: pip install pyGAEB[pandas]"
        ) from e

    table = item_table(doc)
    df = pd.DataFrame(table.rows, columns=table.columns)
    floats = FLOAT_COLUMNS if exact else FLOAT_COLUMNS | DECIMAL_COLUMNS
    for column in table.columns:
        if column in floats:
            df[column] = df[column].astype("float64")
        elif column in DATE_COLUMNS:
            df[column] = pd.to_datetime(df[column])
    return df
