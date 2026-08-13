"""Quantity determination (X31) lost items split across sibling <Itemlist> elements.

The QD body and category readers used `_find`, which returns only the first
match, so a body or category holding several <Itemlist> siblings kept the first
and silently dropped the rest. The award-side parser never had this because it
uses `_findall`.
"""

from __future__ import annotations

import re

import pytest

from pygaeb import GAEBParser

_BODY_RE = re.compile(r"<BoQBody>.*</BoQBody>", re.S)


def _item(oz: str) -> str:
    return (
        f'<Item ID="I{oz}" RNoPart="{oz}"><QtyDeterm><Qty>10.000</Qty>'
        f'<QDetermItem><QTakeoff Row="11 10.000 x"/></QDetermItem>'
        "</QtyDeterm></Item>"
    )


def _itemlist(*ozs: str) -> str:
    return "<Itemlist>" + "".join(_item(o) for o in ozs) + "</Itemlist>"


def _ctgy(rno: str, inner: str) -> str:
    return f'<BoQCtgy ID="C{rno}" RNoPart="{rno}">{inner}</BoQCtgy>'


@pytest.fixture
def qd_template() -> str:
    """The X31 sample from test_qty_support, with its BoQBody left substitutable."""
    from tests import test_qty_support

    for value in vars(test_qty_support).values():
        if isinstance(value, str) and "<GAEB" in value and "<QtyDeterm>" in value:
            return value
    raise AssertionError("no X31 sample found in test_qty_support")


def _parse_body(template: str, body: str):
    xml = _BODY_RE.sub(body, template, count=1)
    doc = GAEBParser().parse_string(xml, filename="t.X31")
    return doc.qty_determination


def _count(qd) -> int:
    return sum(
        len(c.items) + sum(len(s.items) for s in c.subcategories)
        for c in qd.boq.body.categories
    )


@pytest.mark.parametrize(
    ("name", "body", "expected"),
    [
        ("single itemlist", f"<BoQBody>{_itemlist('0010')}</BoQBody>", 1),
        ("single itemlist, 3 items",
         f"<BoQBody>{_itemlist('0010', '0020', '0030')}</BoQBody>", 3),
        ("two sibling itemlists at body level",
         f"<BoQBody>{_itemlist('0010')}{_itemlist('0020')}</BoQBody>", 2),
        ("three sibling itemlists at body level",
         f"<BoQBody>{_itemlist('0010')}{_itemlist('0020')}{_itemlist('0030')}</BoQBody>", 3),
        ("two sibling itemlists inside a category",
         f"<BoQBody>{_ctgy('01', _itemlist('0010') + _itemlist('0020'))}</BoQBody>", 2),
        ("category and loose itemlist together",
         f"<BoQBody>{_ctgy('01', _itemlist('0010'))}{_itemlist('0020')}</BoQBody>", 2),
    ],
)
def test_all_sibling_itemlists_are_read(qd_template, name, body, expected):
    assert _count(_parse_body(qd_template, body)) == expected


def test_unchanged_sample_still_parses(qd_template):
    """The untouched X31 sample must be unaffected by the _find -> _findall change."""
    doc = GAEBParser().parse_string(qd_template, filename="t.X31")
    assert _count(doc.qty_determination) == 3
