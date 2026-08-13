"""Content held without a body wrapper, or split across sibling bodies.

Two shapes that lost data across document kinds:
  - elements sitting directly under a category, with no BoQBody/ECBody wrapper
  - several sibling body elements under one category, where only the first was
    read. pyGAEB <=1.14.0 wrote files in exactly that shape (fixed writer-side
    in 1.14.1), so archived files still need to load completely.
"""

from __future__ import annotations

import re

import pytest

from pygaeb import GAEBParser

# --- award BoQ (X8x) -------------------------------------------------------

_BOQ = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2"><GAEBInfo>'
    "<Version>3.2</Version><Date>2026-08-13</Date><ProgSystem>t</ProgSystem>"
    "</GAEBInfo><PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>"
    "<Award><DP>83</DP><Cur>EUR</Cur><BoQ><BoQInfo><Name>LV</Name>"
    '<BoQBkdn><BoQLevel Length="2"/><Item Length="4"/></BoQBkdn></BoQInfo>'
    "<BoQBody>{body}</BoQBody></BoQ></Award></GAEB>"
)


def _itemlist(*ozs: str) -> str:
    return "<Itemlist>" + "".join(
        f'<Item RNoPart="{o}"><Qty>1.000</Qty><QU>Stk</QU></Item>' for o in ozs
    ) + "</Itemlist>"


def _boq_items(body: str) -> int:
    doc = GAEBParser().parse_string(_BOQ.format(body=body))
    return len(list(doc.award.boq.iter_items()))


@pytest.mark.parametrize(
    ("name", "body", "expected"),
    [
        ("one BoQBody",
         f'<BoQCtgy RNoPart="01"><BoQBody>{_itemlist("0010")}</BoQBody></BoQCtgy>', 1),
        ("two sibling BoQBody elements",
         f'<BoQCtgy RNoPart="01"><BoQBody>{_itemlist("0010")}</BoQBody>'
         f'<BoQBody>{_itemlist("0020")}</BoQBody></BoQCtgy>', 2),
        ("three sibling BoQBody elements",
         f'<BoQCtgy RNoPart="01"><BoQBody>{_itemlist("0010")}</BoQBody>'
         f'<BoQBody>{_itemlist("0020")}</BoQBody>'
         f'<BoQBody>{_itemlist("0030")}</BoQBody></BoQCtgy>', 3),
        ("itemlist directly under the category",
         f'<BoQCtgy RNoPart="01">{_itemlist("0010")}</BoQCtgy>', 1),
        ("subcategories split across sibling bodies",
         '<BoQCtgy RNoPart="01">'
         f'<BoQBody><BoQCtgy RNoPart="11"><BoQBody>{_itemlist("0010")}'
         "</BoQBody></BoQCtgy></BoQBody>"
         f'<BoQBody><BoQCtgy RNoPart="12"><BoQBody>{_itemlist("0020")}'
         "</BoQBody></BoQCtgy></BoQBody>"
         "</BoQCtgy>", 2),
    ],
)
def test_boq_reads_every_body(name, body, expected):
    assert _boq_items(body) == expected


# --- elemental costing (X50/X51) -------------------------------------------

_EC_BODY_RE = re.compile(r"<ECBody>.*</ECBody>", re.S)


@pytest.fixture
def ec_template() -> str:
    from tests import test_cost_support

    for value in vars(test_cost_support).values():
        if isinstance(value, str) and "<GAEB" in value and "<ECBody>" in value:
            return value
    raise AssertionError("no X50 sample found in test_cost_support")


def _cost_element(no: str) -> str:
    return (
        f"<CostElement><EleNo>{no}</EleNo><Descr>E{no}</Descr>"
        "<Qty>1.000</Qty><QU>m2</QU><UP>10.00</UP></CostElement>"
    )


def _ec_count(ec) -> int:
    def walk(body) -> int:
        return len(body.cost_elements) + sum(
            walk(c.body) for c in body.categories if c.body
        )

    return walk(ec.body)


@pytest.mark.parametrize(
    ("name", "body", "expected"),
    [
        ("ctgy > ECBody > CostElement",
         f"<ECBody><ECCtgy><EleNo>01</EleNo><ECBody>{_cost_element('1')}</ECBody>"
         "</ECCtgy></ECBody>", 1),
        ("cost element directly under the category",
         f"<ECBody><ECCtgy><EleNo>01</EleNo>{_cost_element('1')}</ECCtgy></ECBody>", 1),
        ("two sibling ECBody elements",
         f"<ECBody><ECCtgy><EleNo>01</EleNo><ECBody>{_cost_element('1')}</ECBody>"
         f"<ECBody>{_cost_element('2')}</ECBody></ECCtgy></ECBody>", 2),
        ("nested categories with no wrappers",
         "<ECBody><ECCtgy><EleNo>01</EleNo><ECCtgy><EleNo>02</EleNo>"
         f"{_cost_element('1')}</ECCtgy></ECCtgy></ECBody>", 1),
    ],
)
def test_cost_reads_every_body(ec_template, name, body, expected):
    xml = _EC_BODY_RE.sub(body, ec_template, count=1)
    doc = GAEBParser().parse_string(xml, filename="t.X50")
    assert _ec_count(doc.elemental_costing) == expected


def test_leaf_cost_category_keeps_body_none(ec_template):
    """A category with no content must stay body=None, or the writer emits <ECBody/>."""
    xml = _EC_BODY_RE.sub(
        "<ECBody><ECCtgy><EleNo>01</EleNo><Descr>empty</Descr></ECCtgy></ECBody>",
        ec_template,
        count=1,
    )
    doc = GAEBParser().parse_string(xml, filename="t.X50")
    assert doc.elemental_costing.body.categories[0].body is None
