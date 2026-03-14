"""Tests for the GAEB parser — DA XML 3.x and 2.x."""

from decimal import Decimal

import pytest

from pygaeb.exceptions import GAEBParseError
from pygaeb.models.enums import (
    SourceVersion,
    ValidationMode,
)
from pygaeb.parser import GAEBParser


class TestV3Parser:
    def test_parse_basic_v33(self, sample_v33_file):
        doc = GAEBParser.parse(sample_v33_file)
        assert doc.source_version == SourceVersion.DA_XML_33
        assert doc.gaeb_info.version == "3.3"
        assert doc.gaeb_info.prog_system == "TestSuite"

    def test_parse_award_info(self, sample_v33_file):
        doc = GAEBParser.parse(sample_v33_file)
        assert doc.award.project_no == "PRJ-001"
        assert doc.award.project_name == "Test Project"
        assert doc.award.client == "Test Client GmbH"
        assert doc.award.currency == "EUR"

    def test_parse_items(self, sample_v33_file):
        doc = GAEBParser.parse(sample_v33_file)
        items = list(doc.award.boq.iter_items())
        assert len(items) == 3

    def test_parse_first_item(self, sample_v33_file):
        doc = GAEBParser.parse(sample_v33_file)
        items = list(doc.award.boq.iter_items())
        item = items[0]
        assert item.oz == "0010"
        assert "Mauerwerk" in item.short_text
        assert item.qty == Decimal("1170.000")
        assert item.unit == "m2"
        assert item.unit_price == Decimal("45.50")
        assert item.total_price == Decimal("53235.00")

    def test_parse_grand_total(self, sample_v33_file):
        doc = GAEBParser.parse(sample_v33_file)
        expected = Decimal("53235.00") + Decimal("57834.00") + Decimal("11250.00")
        assert doc.grand_total == expected

    def test_parse_categories(self, sample_v33_file):
        doc = GAEBParser.parse(sample_v33_file)
        lots = doc.award.boq.lots
        assert len(lots) == 1
        categories = lots[0].body.categories
        assert len(categories) == 2
        assert categories[0].label == "Rohbau"
        assert categories[1].label == "Ausbau"


class TestV2Parser:
    def test_parse_basic_v20(self, sample_v20_file):
        doc = GAEBParser.parse(sample_v20_file)
        assert doc.source_version == SourceVersion.DA_XML_20

    def test_parse_german_elements(self, sample_v20_file):
        doc = GAEBParser.parse(sample_v20_file)
        assert doc.award.project_no == "PRJ-002"
        assert doc.award.project_name == "Altbau Sanierung"
        assert doc.award.currency == "EUR"

    def test_parse_german_items(self, sample_v20_file):
        doc = GAEBParser.parse(sample_v20_file)
        items = list(doc.award.boq.iter_items())
        assert len(items) == 1
        item = items[0]
        assert item.oz == "0010"
        assert "Abbruch" in item.short_text
        assert item.qty == Decimal("350.000")
        assert item.unit == "m3"


class TestMalformedXML:
    def test_recovery_mode(self, malformed_file):
        doc = GAEBParser.parse(malformed_file)
        warnings = [
            r for r in doc.validation_results
            if "recover" in r.message.lower() or "saniti" in r.message.lower()
        ]
        assert len(warnings) > 0

    def test_still_parses_items(self, malformed_file):
        doc = GAEBParser.parse(malformed_file)
        items = list(doc.award.boq.iter_items())
        assert len(items) >= 1


class TestFileNotFound:
    def test_raises_on_missing_file(self):
        with pytest.raises(GAEBParseError, match="File not found"):
            GAEBParser.parse("/nonexistent/path.X83")


class TestStrictValidation:
    def test_strict_mode_raises_on_error(self, sample_v33_file, tmp_path):
        bad_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version></GAEBInfo>
  <Award>
    <AwardInfo><Cur>EUR</Cur></AwardInfo>
    <BoQ><BoQBody></BoQBody></BoQ>
  </Award>
</GAEB>
"""
        f = tmp_path / "empty.X83"
        f.write_text(bad_xml, encoding="utf-8")
        doc = GAEBParser.parse(f, validation=ValidationMode.LENIENT)
        assert doc is not None
