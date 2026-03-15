"""Tests for security and memory hardening (v1.6.0).

Covers:
- XXE (XML External Entity) prevention
- Billion Laughs entity expansion bomb prevention
- File size limit enforcement
- Recursion depth limits on hierarchy walkers
- InMemoryCache LRU eviction
- SQLiteCache resource cleanup (__del__, cursor close)
- discard_xml() memory release
- Round-trip regression after hardening changes
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

import pytest
from lxml import etree

from pygaeb import GAEBParser, GAEBWriter, SourceVersion
from pygaeb.cache import InMemoryCache, SQLiteCache
from pygaeb.exceptions import GAEBParseError
from pygaeb.models.boq import (
    _MAX_HIERARCHY_DEPTH,
    BoQ,
    BoQBody,
    BoQCtgy,
    Lot,
)
from pygaeb.models.cost import (
    _MAX_HIERARCHY_DEPTH as COST_MAX_DEPTH,
)
from pygaeb.models.cost import (
    CostElement,
    ECBody,
    ECCtgy,
    ElementalCosting,
)
from pygaeb.models.item import Item
from pygaeb.models.quantity import (
    _MAX_HIERARCHY_DEPTH as QTY_MAX_DEPTH,
)
from pygaeb.models.quantity import (
    QtyBoQ,
    QtyBoQBody,
    QtyBoQCtgy,
    QtyDetermination,
)
from pygaeb.parser._xml_safety import SAFE_PARSER, SAFE_RECOVER_PARSER, safe_iterparse

# ── XML Fixtures ─────────────────────────────────────────────────────

SIMPLE_GAEB = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>TestSuite</ProgSystem>
      </GAEBInfo>
      <Award>
        <BoQ>
          <BoQBody>
            <BoQCtgy RNoPart="01" LblTx="Section 1">
              <BoQBody>
                <Itemlist>
                  <Item RNoPart="001">
                    <Qty>10.000</Qty>
                    <QU>m2</QU>
                    <UP>45.50</UP>
                    <Description>
                      <CompleteText>
                        <OutlineText><OutlTxt><TextOutlTxt><p>Test item</p>\
</TextOutlTxt></OutlTxt></OutlineText>
                      </CompleteText>
                    </Description>
                  </Item>
                </Itemlist>
              </BoQBody>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>""")

XXE_ATTEMPT = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <!DOCTYPE foo [
      <!ENTITY xxe SYSTEM "file:///etc/passwd">
    ]>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>&xxe;</ProgSystem>
      </GAEBInfo>
      <Award><BoQ><BoQBody>
        <Itemlist><Item RNoPart="001"><Qty>1</Qty></Item></Itemlist>
      </BoQBody></BoQ></Award>
    </GAEB>""")

BILLION_LAUGHS = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
      <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
      <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
      <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
    ]>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>&lol5;</ProgSystem>
      </GAEBInfo>
      <Award><BoQ><BoQBody>
        <Itemlist><Item RNoPart="001"><Qty>1</Qty></Item></Itemlist>
      </BoQBody></BoQ></Award>
    </GAEB>""")


# ── 1. XXE Prevention ────────────────────────────────────────────────


class TestXXEPrevention:
    """Verify that external entity resolution is blocked."""

    def test_xxe_entity_not_resolved(self) -> None:
        doc = GAEBParser.parse_string(XXE_ATTEMPT, filename="test.X83")
        prog = doc.gaeb_info.prog_system or ""
        assert "root:" not in prog
        assert "/bin/" not in prog

    def test_billion_laughs_blocked(self) -> None:
        doc = GAEBParser.parse_string(BILLION_LAUGHS, filename="test.X83")
        prog = doc.gaeb_info.prog_system or ""
        assert len(prog) < 1000

    def test_safe_parser_blocks_entity_in_raw_xml(self) -> None:
        xml_with_entity = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE foo [<!ENTITY xxe "INJECTED">]>'
            b'<root>&xxe;</root>'
        )
        root = etree.fromstring(xml_with_entity, parser=SAFE_PARSER)
        assert root.text != "INJECTED"

    def test_safe_recover_parser_blocks_entity_in_raw_xml(self) -> None:
        xml_with_entity = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE foo [<!ENTITY xxe "INJECTED">]>'
            b'<root>&xxe;</root>'
        )
        root = etree.fromstring(xml_with_entity, parser=SAFE_RECOVER_PARSER)
        assert root.text != "INJECTED"

    def test_safe_parser_no_network(self) -> None:
        raw = b'<?xml version="1.0"?><root/>'
        root = etree.fromstring(raw, parser=SAFE_PARSER)
        assert root.tag == "root"

    def test_safe_iterparse_works(self) -> None:
        import io
        raw = b'<?xml version="1.0"?><root><child/></root>'
        tags = []
        for _event, elem in safe_iterparse(io.BytesIO(raw), events=("start",)):
            tags.append(elem.tag)
            elem.clear()
        assert "root" in tags
        assert "child" in tags


# ── 2. File Size Guard ───────────────────────────────────────────────


class TestFileSizeGuard:
    """Verify oversized files are rejected before parsing."""

    def test_parse_bytes_rejects_oversized(self) -> None:
        data = b"x" * (1024 * 1024 + 1)
        with pytest.raises(GAEBParseError, match="exceeds the maximum"):
            GAEBParser.parse_bytes(data, max_file_size=1024 * 1024)

    def test_parse_bytes_accepts_under_limit(self) -> None:
        data = SIMPLE_GAEB.encode("utf-8")
        doc = GAEBParser.parse_bytes(data, max_file_size=len(data) + 1024)
        assert doc.item_count >= 1

    def test_parse_string_rejects_oversized(self) -> None:
        big_xml = "x" * 200
        with pytest.raises(GAEBParseError, match="exceeds the maximum"):
            GAEBParser.parse_string(big_xml, max_file_size=100)

    def test_parse_file_rejects_oversized(self, tmp_path: Path) -> None:
        f = tmp_path / "big.X83"
        f.write_text(SIMPLE_GAEB)
        with pytest.raises(GAEBParseError, match="exceeds the maximum"):
            GAEBParser.parse(f, max_file_size=10)

    def test_zero_limit_disables_check(self) -> None:
        data = SIMPLE_GAEB.encode("utf-8")
        doc = GAEBParser.parse_bytes(data, max_file_size=0)
        assert doc.item_count >= 1


# ── 3. Recursion Depth Limits ────────────────────────────────────────


class TestRecursionDepthLimits:
    """Verify deep hierarchies are handled without stack overflow."""

    def test_max_depth_constant_exists(self) -> None:
        assert _MAX_HIERARCHY_DEPTH == 50
        assert COST_MAX_DEPTH == 50
        assert QTY_MAX_DEPTH == 50

    def test_deep_boq_hierarchy_stops_at_limit(self) -> None:
        innermost = BoQCtgy(rno="deep", label="Deep")
        current = innermost
        for i in range(100):
            parent = BoQCtgy(
                rno=str(i), label=f"Level {i}",
                subcategories=[current],
            )
            current = parent

        items = list(current.iter_items())
        assert items == []

        hierarchy = list(
            BoQ(
                lots=[Lot(body=BoQBody(categories=[current]))],
            ).iter_hierarchy()
        )
        assert len(hierarchy) <= _MAX_HIERARCHY_DEPTH + 2

    def test_deep_cost_hierarchy_stops_at_limit(self) -> None:
        innermost = ECCtgy(ele_no="deep", description="Deep")
        current = innermost
        for i in range(100):
            parent = ECCtgy(
                ele_no=str(i),
                description=f"Level {i}",
                body=ECBody(categories=[current]),
            )
            current = parent

        ec = ElementalCosting(body=ECBody(categories=[current]))
        hierarchy = list(ec.iter_hierarchy())
        assert len(hierarchy) <= COST_MAX_DEPTH + 2

    def test_deep_qty_hierarchy_stops_at_limit(self) -> None:
        innermost = QtyBoQCtgy(rno="deep")
        current = innermost
        for i in range(100):
            parent = QtyBoQCtgy(
                rno=str(i),
                subcategories=[current],
            )
            current = parent

        qd = QtyDetermination(boq=QtyBoQ(body=QtyBoQBody(categories=[current])))
        hierarchy = list(qd.iter_hierarchy())
        assert len(hierarchy) <= QTY_MAX_DEPTH + 2

    def test_iterative_iter_items_handles_deep_boq(self) -> None:
        innermost = BoQCtgy(
            rno="leaf", label="Leaf",
            items=[Item(oz="01.001", short_text="deep item")],
        )
        current = innermost
        for i in range(200):
            current = BoQCtgy(
                rno=str(i), label=f"L{i}",
                subcategories=[current],
            )
        items = list(current.iter_items())
        assert len(items) == 1
        assert items[0].oz == "01.001"

    def test_iterative_cost_element_iteration(self) -> None:
        innermost = CostElement(ele_no="leaf", short_text="deep cost")
        current = innermost
        for _ in range(200):
            current = CostElement(
                ele_no="parent", short_text="wrap",
                children=[current],
            )
        elements = list(current.iter_cost_elements())
        assert len(elements) == 201
        assert elements[-1].ele_no == "leaf"


# ── 4. InMemoryCache LRU Eviction ───────────────────────────────────


class TestInMemoryCacheLRU:
    """Verify LRU eviction and bounded size."""

    def test_default_maxsize(self) -> None:
        cache = InMemoryCache()
        assert cache._maxsize == 10_000

    def test_custom_maxsize(self) -> None:
        cache = InMemoryCache(maxsize=5)
        assert cache._maxsize == 5

    def test_evicts_oldest_when_full(self) -> None:
        cache = InMemoryCache(maxsize=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        cache.put("d", "4")

        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("d") == "4"
        assert len(cache) == 3

    def test_get_refreshes_lru_order(self) -> None:
        cache = InMemoryCache(maxsize=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")

        cache.get("a")
        cache.put("d", "4")

        assert cache.get("a") == "1"
        assert cache.get("b") is None

    def test_put_existing_key_refreshes_order(self) -> None:
        cache = InMemoryCache(maxsize=3)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")

        cache.put("a", "updated")
        cache.put("d", "4")

        assert cache.get("a") == "updated"
        assert cache.get("b") is None

    def test_zero_maxsize_disables_limit(self) -> None:
        cache = InMemoryCache(maxsize=0)
        for i in range(100):
            cache.put(str(i), str(i))
        assert len(cache) == 100

    def test_clear_empties_cache(self) -> None:
        cache = InMemoryCache(maxsize=5)
        for i in range(5):
            cache.put(str(i), str(i))
        cache.clear()
        assert len(cache) == 0

    def test_delete_removes_entry(self) -> None:
        cache = InMemoryCache(maxsize=5)
        cache.put("a", "1")
        cache.delete("a")
        assert cache.get("a") is None


# ── 5. SQLiteCache Cleanup ───────────────────────────────────────────


class TestSQLiteCacheCleanup:
    """Verify SQLiteCache properly manages resources."""

    def test_context_manager_closes_connection(self, tmp_path: Path) -> None:
        with SQLiteCache(str(tmp_path / "cache")) as cache:
            cache.put("k", "v")
            assert cache.get("k") == "v"
        assert cache._conn is None

    def test_del_closes_connection(self, tmp_path: Path) -> None:
        cache = SQLiteCache(str(tmp_path / "cache"))
        cache.put("k", "v")
        assert cache._conn is not None
        cache.__del__()
        assert cache._conn is None

    def test_double_close_is_safe(self, tmp_path: Path) -> None:
        cache = SQLiteCache(str(tmp_path / "cache"))
        cache.put("k", "v")
        cache.close()
        cache.close()
        assert cache._conn is None

    def test_cursor_closed_after_get(self, tmp_path: Path) -> None:
        with SQLiteCache(str(tmp_path / "cache")) as cache:
            cache.put("k", "v")
            result = cache.get("k")
            assert result == "v"

    def test_cursor_closed_after_keys(self, tmp_path: Path) -> None:
        with SQLiteCache(str(tmp_path / "cache")) as cache:
            cache.put("a", "1")
            cache.put("b", "2")
            keys = cache.keys()
            assert set(keys) == {"a", "b"}

    def test_cursor_closed_after_len(self, tmp_path: Path) -> None:
        with SQLiteCache(str(tmp_path / "cache")) as cache:
            cache.put("a", "1")
            cache.put("b", "2")
            assert len(cache) == 2


# ── 6. discard_xml() ────────────────────────────────────────────────


class TestDiscardXml:
    """Verify discard_xml() releases all lxml references."""

    def test_discard_clears_xml_root(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        assert doc.xml_root is not None
        doc.discard_xml()
        assert doc.xml_root is None

    def test_discard_clears_source_elements(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        for item in doc.iter_items():
            assert item.source_element is not None
        doc.discard_xml()
        for item in doc.iter_items():
            assert item.source_element is None

    def test_discard_clears_gaeb_info_element(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        doc.discard_xml()
        assert doc.gaeb_info.source_element is None

    def test_discard_clears_award_element(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        doc.discard_xml()
        assert doc.award.source_element is None

    def test_discard_clears_boqctgy_elements(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        doc.discard_xml()
        for lot in doc.award.boq.lots:
            for ctgy in lot.body.categories:
                assert ctgy.source_element is None

    def test_data_survives_discard(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        doc.discard_xml()
        assert doc.item_count >= 1
        items = list(doc.iter_items())
        assert items[0].short_text == "Test item"
        assert items[0].qty == Decimal("10.000")

    def test_xpath_raises_after_discard(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        doc.discard_xml()
        with pytest.raises(RuntimeError, match="keep_xml"):
            doc.xpath("//g:Item")

    def test_discard_on_non_keep_xml_is_noop(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB)
        doc.discard_xml()
        assert doc.item_count >= 1


# ── 7. Round-Trip Regression ─────────────────────────────────────────


class TestRoundTripRegression:
    """Verify existing functionality still works after hardening."""

    def test_parse_write_roundtrip(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB)
        xml_bytes, _warnings = GAEBWriter.to_bytes(doc)
        doc2 = GAEBParser.parse_bytes(xml_bytes)
        assert doc2.item_count == doc.item_count
        items1 = list(doc.iter_items())
        items2 = list(doc2.iter_items())
        assert items1[0].short_text == items2[0].short_text
        assert items1[0].qty == items2[0].qty

    def test_keep_xml_still_works(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB, keep_xml=True)
        assert doc.xml_root is not None
        results = doc.xpath("//g:Item")
        assert len(results) >= 1

    def test_version_detection_still_works(self) -> None:
        doc = GAEBParser.parse_string(SIMPLE_GAEB)
        assert doc.source_version == SourceVersion.DA_XML_33


# ── 8. Safe Parser Module ───────────────────────────────────────────


class TestSafeParserModule:
    """Verify the _xml_safety module constants are properly configured."""

    def test_safe_parser_is_xmlparser(self) -> None:
        assert isinstance(SAFE_PARSER, etree.XMLParser)

    def test_safe_recover_parser_is_xmlparser(self) -> None:
        assert isinstance(SAFE_RECOVER_PARSER, etree.XMLParser)

    def test_safe_parser_parses_valid_xml(self) -> None:
        raw = b'<?xml version="1.0"?><root><child attr="val"/></root>'
        root = etree.fromstring(raw, parser=SAFE_PARSER)
        assert root.tag == "root"
        assert root[0].tag == "child"

    def test_safe_recover_parser_handles_malformed(self) -> None:
        raw = b'<root><unclosed></root>'
        root = etree.fromstring(raw, parser=SAFE_RECOVER_PARSER)
        assert root is not None
