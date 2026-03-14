"""Tests for OZ resolver — hierarchy segment splitting."""


from pygaeb.models.boq import BoQBkdn
from pygaeb.models.enums import BkdnType
from pygaeb.parser.xml_v3.oz_resolver import (
    build_hierarchy_path,
    format_oz,
    resolve_oz,
)


class TestResolveOZ:
    def test_basic_three_level(self):
        bkdn = [
            BoQBkdn(bkdn_type=BkdnType.LOT, length=2),
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.ITEM, length=4),
        ]
        result = resolve_oz("01.02.0030", bkdn)
        assert result == ["01", "02", "0030"]

    def test_no_bkdn_falls_back_to_dots(self):
        result = resolve_oz("01.02.0030", [])
        assert result == ["01", "02", "0030"]

    def test_single_level(self):
        bkdn = [BoQBkdn(bkdn_type=BkdnType.ITEM, length=4)]
        result = resolve_oz("0010", bkdn)
        assert result == ["0010"]

    def test_oz_without_dots(self):
        bkdn = [
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.ITEM, length=4),
        ]
        result = resolve_oz("010010", bkdn)
        assert result == ["01", "0010"]

    def test_short_oz(self):
        bkdn = [
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.ITEM, length=4),
        ]
        result = resolve_oz("01", bkdn)
        assert result == ["01"]


class TestFormatOZ:
    def test_default_separator(self):
        assert format_oz(["01", "02", "0030"]) == "01.02.0030"

    def test_custom_separator(self):
        assert format_oz(["01", "02", "0030"], "-") == "01-02-0030"


class TestBuildHierarchyPath:
    def test_basic_path(self):
        bkdn = [
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.ITEM, length=4),
        ]
        labels = {"01": "Rohbau", "01.02": "Mauerwerk"}
        path = build_hierarchy_path("01.02.0030", bkdn, labels)
        assert path == ["Rohbau", "Mauerwerk"]

    def test_missing_labels_fallback(self):
        bkdn = [
            BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=2),
            BoQBkdn(bkdn_type=BkdnType.ITEM, length=4),
        ]
        path = build_hierarchy_path("01.0030", bkdn, {})
        assert path == ["01"]
