"""Tests for DocumentAPI, multi-lot documents, repr, parse_string/parse_bytes, configure."""

from __future__ import annotations

from decimal import Decimal

from pygaeb.api.document_api import DocumentAPI
from pygaeb.cache import SQLiteCache
from pygaeb.config import configure, get_settings, reset_settings
from pygaeb.convert.to_json import to_json_string
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument
from pygaeb.models.enums import ItemType, SourceVersion
from pygaeb.models.item import ClassificationResult, Item
from pygaeb.parser import GAEBParser

from .conftest import SAMPLE_V33_XML


class TestDocumentAPI:
    def test_boq_access(self, sample_document):
        api = DocumentAPI(sample_document)
        assert api.boq is sample_document.award.boq

    def test_lots(self, sample_document):
        api = DocumentAPI(sample_document)
        assert len(api.lots) == 1

    def test_not_multi_lot(self, sample_document):
        api = DocumentAPI(sample_document)
        assert api.is_multi_lot is False

    def test_iter_items_all(self, sample_document):
        api = DocumentAPI(sample_document)
        items = list(api.iter_items())
        assert len(items) == 3

    def test_iter_items_by_lot(self, sample_document):
        api = DocumentAPI(sample_document)
        items = list(api.iter_items(lot_index=0))
        assert len(items) == 3

    def test_iter_items_invalid_lot(self, sample_document):
        api = DocumentAPI(sample_document)
        items = list(api.iter_items(lot_index=99))
        assert len(items) == 0

    def test_get_item(self, sample_document):
        api = DocumentAPI(sample_document)
        item = api.get_item("01.01.0010")
        assert item is not None
        assert "Innenwand" in item.short_text

    def test_get_item_missing(self, sample_document):
        api = DocumentAPI(sample_document)
        assert api.get_item("does-not-exist") is None

    def test_iter_hierarchy(self, sample_document):
        api = DocumentAPI(sample_document)
        entries = list(api.iter_hierarchy())
        assert len(entries) > 0
        depths = [e[0] for e in entries]
        assert 0 in depths

    def test_filter_by_item_type(self, sample_document):
        api = DocumentAPI(sample_document)
        normals = api.filter_items(item_type=ItemType.NORMAL)
        assert len(normals) == 3

    def test_filter_by_min_total(self, sample_document):
        api = DocumentAPI(sample_document)
        expensive = api.filter_items(min_total=Decimal("50000"))
        assert len(expensive) == 2

    def test_filter_by_predicate(self, sample_document):
        api = DocumentAPI(sample_document)
        result = api.filter_items(predicate=lambda i: "Innenwand" in i.short_text)
        assert len(result) == 1

    def test_filter_by_classification(self, sample_document):
        api = DocumentAPI(sample_document)
        classified = api.filter_items(has_classification=True)
        assert len(classified) == 0
        unclassified = api.filter_items(has_classification=False)
        assert len(unclassified) == 3

    def test_filter_by_trade(self):
        items = [
            Item(
                oz="01",
                classification=ClassificationResult(trade="Structural"),
            ),
            Item(oz="02"),
        ]
        ctgy = BoQCtgy(rno="01", items=items)
        lot = Lot(rno="1", body=BoQBody(categories=[ctgy]))
        doc = GAEBDocument(award=AwardInfo(boq=BoQ(lots=[lot])))
        api = DocumentAPI(doc)
        result = api.filter_items(trade="Structural")
        assert len(result) == 1
        assert result[0].oz == "01"

    def test_summary(self, sample_document):
        api = DocumentAPI(sample_document)
        s = api.summary()
        assert s["total_items"] == 3
        assert s["source_version"] == "3.3"
        assert s["exchange_phase"] == "X83"
        assert s["is_multi_lot"] is False
        assert s["lots"] == 1


class TestMultiLot:
    def test_is_multi_lot(self, multi_lot_document):
        assert multi_lot_document.award.boq.is_multi_lot is True

    def test_total_items(self, multi_lot_document):
        assert multi_lot_document.item_count == 3

    def test_grand_total_excludes_eventual(self, multi_lot_document):
        assert multi_lot_document.grand_total == Decimal("20400.00")

    def test_lot_subtotals(self, multi_lot_document):
        lots = multi_lot_document.award.boq.lots
        assert lots[0].subtotal == Decimal("6000.00")
        assert lots[1].subtotal == Decimal("14400.00")

    def test_iter_items_per_lot(self, multi_lot_document):
        api = DocumentAPI(multi_lot_document)
        lot0 = list(api.iter_items(lot_index=0))
        lot1 = list(api.iter_items(lot_index=1))
        assert len(lot0) == 1
        assert len(lot1) == 2

    def test_same_oz_different_lots(self, multi_lot_document):
        items = list(multi_lot_document.award.boq.iter_items())
        ozs = [i.oz for i in items]
        assert ozs.count("01.0010") == 2


class TestRepr:
    def test_item_repr(self):
        item = Item(oz="01.01.0010", short_text="Mauerwerk", total_price=Decimal("53235"))
        r = repr(item)
        assert "01.01.0010" in r
        assert "Mauerwerk" in r
        assert "53235" in r

    def test_item_repr_long_text_truncated(self):
        item = Item(oz="01", short_text="A" * 60)
        r = repr(item)
        assert "..." in r

    def test_boq_repr(self, sample_document):
        r = repr(sample_document.award.boq)
        assert "lots=1" in r
        assert "items=3" in r

    def test_lot_repr(self, sample_document):
        r = repr(sample_document.award.boq.lots[0])
        assert "Default" in r

    def test_document_repr(self, sample_document):
        r = repr(sample_document)
        assert "3.3" in r
        assert "X83" in r
        assert "items=3" in r


class TestParseStringAndBytes:
    def test_parse_string(self, tmp_path):
        doc = GAEBParser.parse_string(SAMPLE_V33_XML, filename="tender.X83")
        assert doc.item_count == 3
        assert doc.source_version == SourceVersion.DA_XML_33

    def test_parse_bytes(self, tmp_path):
        raw = SAMPLE_V33_XML.encode("utf-8")
        doc = GAEBParser.parse_bytes(raw, filename="tender.X83")
        assert doc.item_count == 3

    def test_parse_bytes_preserves_values(self, tmp_path):
        raw = SAMPLE_V33_XML.encode("utf-8")
        doc = GAEBParser.parse_bytes(raw, filename="tender.X83")
        item = doc.award.boq.get_item("0010")
        assert item is not None
        assert item.unit_price == Decimal("45.50")


class TestConfigure:
    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_default_settings(self):
        s = get_settings()
        assert s.classifier_concurrency == 5
        assert s.log_level == "WARNING"

    def test_configure_overrides(self):
        s = configure(classifier_concurrency=10, log_level="DEBUG")
        assert s.classifier_concurrency == 10
        assert s.log_level == "DEBUG"

    def test_configure_partial(self):
        configure(classifier_concurrency=20)
        s = get_settings()
        assert s.classifier_concurrency == 20
        assert s.log_level == "WARNING"


class TestSQLiteCacheContextManager:
    def test_context_manager(self, tmp_path):
        with SQLiteCache(str(tmp_path)) as cache:
            cache.put("k", "v")
            assert cache.get("k") == "v"
        cache2 = SQLiteCache(str(tmp_path))
        assert cache2.get("k") == "v"
        cache2.close()


class TestToJsonString:
    def test_to_json_string(self, sample_document):
        json_str = to_json_string(sample_document)
        assert "Mauerwerk Innenwand" in json_str
        assert "PRJ-001" in json_str

    def test_json_string_excludes_attachments(self, sample_document):
        json_str = to_json_string(sample_document, include_attachments=False)
        assert '"data"' not in json_str
