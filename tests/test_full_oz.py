"""Tests for Item.full_oz — the complete ordinal number (Ordnungszahl).

The parser stores only the leaf ``RNoPart`` in ``Item.oz``; ``full_oz`` joins
the ancestor category/lot chain (``oz_path``) to produce the human-facing
number such as ``"01.02.0004"``.
"""

from __future__ import annotations

from textwrap import dedent

from pygaeb import BoQTree, GAEBParser
from pygaeb.models.item import Item

NESTED = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo><Cur>EUR</Cur></AwardInfo>
        <BoQ>
          <BoQInfo>
            <BoQBkdn>
              <BoQLevel Length="2"/>
              <BoQLevel Length="2"/>
              <Item Length="4"/>
            </BoQBkdn>
          </BoQInfo>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <LblTx>Rohbau</LblTx>
              <BoQBody>
                <BoQCtgy RNoPart="02">
                  <LblTx>Mauerwerk</LblTx>
                  <Itemlist>
                    <Item RNoPart="0004">
                      <ShortText>Deep item</ShortText>
                      <Qty>1</Qty><QU>m2</QU>
                    </Item>
                  </Itemlist>
                </BoQCtgy>
              </BoQBody>
            </BoQCtgy>
            <BoQCtgy RNoPart="02">
              <LblTx>Ausbau</LblTx>
              <Itemlist>
                <Item RNoPart="0010">
                  <ShortText>Shallow item</ShortText>
                  <Qty>1</Qty><QU>pcs</QU>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")

# Multi-lot file (LOT breakdown level present) — lot RNoPart prefixes the OZ.
MULTI_LOT = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo><Cur>EUR</Cur></AwardInfo>
        <BoQ>
          <BoQInfo>
            <BoQBkdn>
              <Lot Length="2"/>
              <BoQLevel Length="2"/>
              <Item Length="4"/>
            </BoQBkdn>
          </BoQInfo>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <LblTx>Lot One</LblTx>
              <BoQBody>
                <BoQCtgy RNoPart="03">
                  <LblTx>Section</LblTx>
                  <Itemlist>
                    <Item RNoPart="0001"><ShortText>A</ShortText><Qty>1</Qty></Item>
                  </Itemlist>
                </BoQCtgy>
              </BoQBody>
            </BoQCtgy>
            <BoQCtgy RNoPart="02">
              <LblTx>Lot Two</LblTx>
              <BoQBody>
                <BoQCtgy RNoPart="05">
                  <LblTx>Section</LblTx>
                  <Itemlist>
                    <Item RNoPart="0002"><ShortText>B</ShortText><Qty>1</Qty></Item>
                  </Itemlist>
                </BoQCtgy>
              </BoQBody>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")


class TestFullOz:
    def test_nested_full_oz(self) -> None:
        doc = GAEBParser.parse_string(NESTED)
        by_text = {i.short_text: i for i in doc.award.boq.iter_items()}
        assert by_text["Deep item"].full_oz == "01.02.0004"
        assert by_text["Deep item"].oz == "0004"
        assert by_text["Deep item"].oz_path == ["01", "02"]

    def test_shallow_full_oz(self) -> None:
        doc = GAEBParser.parse_string(NESTED)
        by_text = {i.short_text: i for i in doc.award.boq.iter_items()}
        assert by_text["Shallow item"].full_oz == "02.0010"

    def test_custom_separator(self) -> None:
        doc = GAEBParser.parse_string(NESTED)
        item = next(i for i in doc.award.boq.iter_items() if i.oz == "0004")
        assert item.full_oz_with("-") == "01-02-0004"

    def test_multi_lot_oz_includes_lot(self) -> None:
        doc = GAEBParser.parse_string(MULTI_LOT)
        ozs = {i.short_text: i.full_oz for i in doc.award.boq.iter_items()}
        assert ozs == {"A": "01.03.0001", "B": "02.05.0002"}

    def test_full_oz_falls_back_to_leaf_for_built_item(self) -> None:
        # Programmatically built items have no ancestor chain.
        item = Item(oz="0099")
        assert item.full_oz == "0099"

    def test_full_oz_survives_roundtrip_dump(self) -> None:
        doc = GAEBParser.parse_string(NESTED)
        item = next(i for i in doc.award.boq.iter_items() if i.oz == "0004")
        restored = Item.model_validate(item.model_dump())
        assert restored.full_oz == "01.02.0004"

    def test_tree_find_item_by_leaf_or_full_oz(self) -> None:
        # Parsed items keep a leaf oz; the tree must resolve either form.
        doc = GAEBParser.parse_string(NESTED)
        tree = BoQTree(doc.award.boq)
        assert tree.find_item("01.02.0004") is tree.find_item("0004")
        assert tree.find_item("01.02.0004").item.short_text == "Deep item"
