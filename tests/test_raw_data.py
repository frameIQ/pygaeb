"""``collect_raw_data``: the child elements of an item that pyGAEB did not read.

The parsers record every element they read, so ``raw_data`` holds exactly the rest,
for every document kind.
"""

from __future__ import annotations

import re
from textwrap import dedent

import pytest
from lxml import etree

from pygaeb import GAEBParser
from tests.document_kinds import DOCUMENT_KINDS

# Start tags of the elements that become items; ``Position`` is the DA XML 2.x name.
ITEM_START = re.compile(r"<(?:Item|Position|MarkupItem|OrderItem|CostElement)\b[^>]*(?<!/)>")

VENDOR_ITEM = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <BoQ>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <Itemlist>
                <Item RNoPart="0010">
                  <!-- exported by a vendor tool -->
                  <Qty>10.000</Qty>
                  <QU>m2</QU>
                  <UP>45.50</UP>
                  <Provis>WithTotal</Provis>
                  <HourIt>Yes</HourIt>
                  <Plain>text</Plain>
                  <Empty/>
                  <Tag>a</Tag>
                  <Tag>b</Tag>
                  <Nested Kind="x"><Part>1</Part><Part>2</Part></Nested>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")


def _with_vendor_element(xml: str) -> str:
    """Put an element no GAEB schema defines first inside every item."""
    return ITEM_START.sub(lambda m: m.group(0) + "<VendorNote>pyGAEB</VendorNote>", xml)


@pytest.mark.parametrize("kind", list(DOCUMENT_KINDS))
def test_every_document_kind_collects_exactly_the_unread_elements(kind: str) -> None:
    xml, filename = DOCUMENT_KINDS[kind]
    doc = GAEBParser.parse_string(
        _with_vendor_element(xml), filename=filename, collect_raw_data=True,
    )

    items = list(doc.iter_items())
    assert items
    # Nothing the parser reads leaks in: markup fields, trade prices, quantity rows.
    assert [item.raw_data for item in items] == [{"VendorNote": "pyGAEB"}] * len(items)


def test_values_keep_what_the_element_holds() -> None:
    doc = GAEBParser.parse_string(VENDOR_ITEM, filename="vendor.X86", collect_raw_data=True)
    raw = next(doc.iter_items()).raw_data

    assert raw is not None
    assert raw["Plain"] == "text"
    assert raw["Empty"] is None
    assert raw["Tag"] == ["a", "b"]
    nested = etree.fromstring(raw["Nested"])
    assert nested.get("Kind") == "x"
    assert [part.text for part in nested] == ["1", "2"]


def test_standard_elements_pygaeb_does_not_read_are_collected_too() -> None:
    doc = GAEBParser.parse_string(VENDOR_ITEM, filename="vendor.X86", collect_raw_data=True)
    raw = next(doc.iter_items()).raw_data or {}

    assert raw["HourIt"] == "Yes"
    assert not {"Qty", "QU", "UP", "Provis"} & raw.keys()


def test_raw_data_stays_empty_without_the_option() -> None:
    xml, filename = DOCUMENT_KINDS["X94 trade"]
    doc = GAEBParser.parse_string(_with_vendor_element(xml), filename=filename)

    assert all(item.raw_data is None for item in doc.iter_items())
