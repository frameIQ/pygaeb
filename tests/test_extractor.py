"""Tests for the structured extraction module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pygaeb.extractor.builtin_schemas import DoorSpec, PipeSpec, WallSpec, WindowSpec
from pygaeb.extractor.extraction_cache import ExtractionCache
from pygaeb.extractor.extraction_prompt import (
    build_extraction_prompt,
    build_extraction_user_message,
)
from pygaeb.extractor.schema_utils import (
    compute_completeness,
    compute_extraction_cache_key,
    compute_schema_hash,
    get_field_descriptions,
    get_schema_name,
    schema_field_summary,
)
from pygaeb.extractor.structured_extractor import _filter_items
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument
from pygaeb.models.item import ClassificationResult, ExtractionResult, Item

# --- Test schemas ---

class SimpleDoor(BaseModel):
    door_type: str = Field("", description="single or double")
    width_mm: int | None = Field(None, description="Width in mm")
    fire_rating: str | None = Field(None, description="Fire class")
    glazing: bool = Field(False, description="Has glass")


class TinySchema(BaseModel):
    name: str = ""
    value: int = 0


# --- Schema utils tests ---

class TestSchemaHash:
    def test_deterministic(self):
        h1 = compute_schema_hash(SimpleDoor)
        h2 = compute_schema_hash(SimpleDoor)
        assert h1 == h2

    def test_different_schemas_different_hash(self):
        h1 = compute_schema_hash(SimpleDoor)
        h2 = compute_schema_hash(TinySchema)
        assert h1 != h2

    def test_hash_length(self):
        h = compute_schema_hash(SimpleDoor)
        assert len(h) == 16

    def test_cache_key_combines_hashes(self):
        item_hash = "abc123"
        schema_hash = "def456"
        key = compute_extraction_cache_key(item_hash, schema_hash)
        assert len(key) == 64  # SHA-256 hex digest


class TestSchemaName:
    def test_simple_name(self):
        assert get_schema_name(SimpleDoor) == "SimpleDoor"

    def test_builtin_name(self):
        assert get_schema_name(DoorSpec) == "DoorSpec"


class TestFieldDescriptions:
    def test_extracts_descriptions(self):
        descs = get_field_descriptions(SimpleDoor)
        assert "door_type" in descs
        assert "single or double" in descs["door_type"]
        assert "Width in mm" in descs["width_mm"]

    def test_all_fields_present(self):
        descs = get_field_descriptions(SimpleDoor)
        assert len(descs) == 4

    def test_builtin_schema_descriptions(self):
        descs = get_field_descriptions(DoorSpec)
        assert len(descs) == 12


class TestCompleteness:
    def test_fully_populated(self):
        instance = SimpleDoor(
            door_type="single",
            width_mm=900,
            fire_rating="T30",
            glazing=True,
        )
        score = compute_completeness(instance)
        assert score == 1.0

    def test_empty_defaults(self):
        instance = SimpleDoor()
        score = compute_completeness(instance)
        assert score == 0.0

    def test_partial(self):
        instance = SimpleDoor(door_type="single", fire_rating="T30")
        score = compute_completeness(instance)
        assert 0.4 <= score <= 0.6

    def test_boolean_true_counts(self):
        instance = SimpleDoor(glazing=True)
        score = compute_completeness(instance)
        assert score > 0.0

    def test_boolean_false_is_default(self):
        instance = SimpleDoor(glazing=False)
        score = compute_completeness(instance)
        # glazing=False is the default, doesn't count as populated
        assert score == 0.0


class TestSchemaFieldSummary:
    def test_short_schema(self):
        summary = schema_field_summary(TinySchema)
        assert "name" in summary
        assert "value" in summary

    def test_long_schema(self):
        summary = schema_field_summary(DoorSpec)
        assert "..." in summary
        assert "12 fields" in summary


# --- Extraction prompt tests ---

class TestExtractionPrompt:
    def test_includes_element_type(self):
        prompt = build_extraction_prompt(SimpleDoor, element_type="Door")
        assert "Door" in prompt

    def test_includes_trade(self):
        prompt = build_extraction_prompt(SimpleDoor, trade="Finishes")
        assert "Finishes" in prompt

    def test_includes_field_descriptions(self):
        prompt = build_extraction_prompt(SimpleDoor, element_type="Door")
        assert "single or double" in prompt
        assert "Width in mm" in prompt
        assert "Fire class" in prompt

    def test_german_context(self):
        prompt = build_extraction_prompt(SimpleDoor)
        assert "German" in prompt
        assert "DIN" in prompt


class TestExtractionUserMessage:
    def test_basic_message(self):
        msg = build_extraction_user_message(
            hierarchy_path="Ausbau > Türen",
            short_text="Innentür T30 einflügelig",
            long_text="Holztür mit Stahlzarge",
            unit="Stk",
        )
        assert "Ausbau > Türen" in msg
        assert "Innentür T30" in msg
        assert "Holztür" in msg
        assert "Stk" in msg

    def test_empty_fields_omitted(self):
        msg = build_extraction_user_message(
            hierarchy_path="",
            short_text="Door item",
            long_text="",
            unit="",
        )
        assert "Long text" not in msg
        assert "Unit" not in msg


# --- Extraction cache tests ---

class TestExtractionCache:
    """Test ExtractionCache with default InMemoryCache backend."""

    def test_put_and_get(self):
        cache = ExtractionCache()
        data = {"door_type": "single", "width_mm": 900}
        cache.put("key1", "DoorSpec", "hash1", data, 0.75)

        result = cache.get("key1")
        assert result is not None
        retrieved_data, completeness = result
        assert retrieved_data["door_type"] == "single"
        assert retrieved_data["width_mm"] == 900
        assert completeness == 0.75

    def test_cache_miss(self):
        cache = ExtractionCache()
        assert cache.get("nonexistent") is None

    def test_overwrite(self):
        cache = ExtractionCache()
        cache.put("key1", "DoorSpec", "hash1", {"v": 1}, 0.5)
        cache.put("key1", "DoorSpec", "hash1", {"v": 2}, 0.9)

        result = cache.get("key1")
        assert result is not None
        data, completeness = result
        assert data["v"] == 2
        assert completeness == 0.9

    def test_stats(self):
        cache = ExtractionCache()
        cache.put("k1", "DoorSpec", "h1", {"a": 1}, 0.8)
        cache.put("k2", "DoorSpec", "h1", {"b": 2}, 0.6)
        cache.put("k3", "WallSpec", "h2", {"c": 3}, 0.9)

        stats = cache.stats()
        assert len(stats) == 2
        door_stat = next(s for s in stats if s["schema_name"] == "DoorSpec")
        assert door_stat["count"] == 2
        assert door_stat["avg_completeness"] == 0.70

    def test_clear_by_schema(self):
        cache = ExtractionCache()
        cache.put("k1", "DoorSpec", "h1", {}, 0.5)
        cache.put("k2", "WallSpec", "h2", {}, 0.5)
        cache.clear(schema_name="DoorSpec")

        assert cache.get("k1") is None
        assert cache.get("k2") is not None


# --- Item filtering tests ---

class TestFilterItems:
    def _make_doc(self, items: list[Item]) -> GAEBDocument:
        ctgy = BoQCtgy(items=items)
        body = BoQBody(categories=[ctgy])
        lot = Lot(body=body)
        return GAEBDocument(award=AwardInfo(boq=BoQ(lots=[lot])))

    def test_filter_by_element_type(self):
        items = [
            Item(oz="0010", classification=ClassificationResult(
                trade="Finishes", element_type="Door", confidence=0.9)),
            Item(oz="0020", classification=ClassificationResult(
                trade="Finishes", element_type="Window", confidence=0.9)),
            Item(oz="0030", classification=ClassificationResult(
                trade="Structural", element_type="Wall", confidence=0.9)),
        ]
        doc = self._make_doc(items)
        result = _filter_items(doc, element_type="Door")
        assert len(result) == 1
        assert result[0].oz == "0010"

    def test_filter_by_trade(self):
        items = [
            Item(oz="0010", classification=ClassificationResult(
                trade="Finishes", element_type="Door", confidence=0.9)),
            Item(oz="0020", classification=ClassificationResult(
                trade="Finishes", element_type="Window", confidence=0.9)),
            Item(oz="0030", classification=ClassificationResult(
                trade="Structural", element_type="Wall", confidence=0.9)),
        ]
        doc = self._make_doc(items)
        result = _filter_items(doc, trade="Finishes")
        assert len(result) == 2

    def test_filter_by_sub_type(self):
        items = [
            Item(oz="0010", classification=ClassificationResult(
                trade="Finishes", element_type="Door",
                sub_type="Fire Door", confidence=0.9)),
            Item(oz="0020", classification=ClassificationResult(
                trade="Finishes", element_type="Door",
                sub_type="Single Door", confidence=0.9)),
        ]
        doc = self._make_doc(items)
        result = _filter_items(doc, sub_type="Fire Door")
        assert len(result) == 1
        assert result[0].oz == "0010"

    def test_filter_combined(self):
        items = [
            Item(oz="0010", classification=ClassificationResult(
                trade="MEP-Plumbing", element_type="Pipe", confidence=0.9)),
            Item(oz="0020", classification=ClassificationResult(
                trade="MEP-Plumbing", element_type="Valve", confidence=0.9)),
        ]
        doc = self._make_doc(items)
        result = _filter_items(doc, trade="MEP-Plumbing", element_type="Pipe")
        assert len(result) == 1

    def test_unclassified_items_excluded(self):
        items = [
            Item(oz="0010", classification=None),
            Item(oz="0020", classification=ClassificationResult(
                trade="Finishes", element_type="Door", confidence=0.9)),
        ]
        doc = self._make_doc(items)
        result = _filter_items(doc, element_type="Door")
        assert len(result) == 1

    def test_no_filters_returns_all_classified(self):
        items = [
            Item(oz="0010", classification=ClassificationResult(
                trade="Finishes", element_type="Door", confidence=0.9)),
            Item(oz="0020", classification=ClassificationResult(
                trade="Structural", element_type="Wall", confidence=0.9)),
            Item(oz="0030", classification=None),
        ]
        doc = self._make_doc(items)
        result = _filter_items(doc)
        assert len(result) == 2


# --- ExtractionResult model tests ---

class TestExtractionResult:
    def test_basic_creation(self):
        er = ExtractionResult(
            schema_name="DoorSpec",
            schema_hash="abc123",
            data={"door_type": "single", "fire_rating": "T30"},
            completeness=0.5,
        )
        assert er.schema_name == "DoorSpec"
        assert er.data["door_type"] == "single"
        assert er.completeness == 0.5

    def test_completeness_clamped(self):
        er = ExtractionResult(completeness=1.5)
        assert er.completeness == 1.0

    def test_item_extractions_dict(self):
        item = Item(oz="0010")
        item.extractions["DoorSpec"] = ExtractionResult(
            schema_name="DoorSpec",
            data={"door_type": "single"},
            completeness=0.3,
        )
        assert "DoorSpec" in item.extractions
        assert item.extractions["DoorSpec"].data["door_type"] == "single"

    def test_multiple_extractions_on_same_item(self):
        item = Item(oz="0010")
        item.extractions["DoorSpec"] = ExtractionResult(
            schema_name="DoorSpec", data={"door_type": "single"}, completeness=0.3)
        item.extractions["FireSpec"] = ExtractionResult(
            schema_name="FireSpec", data={"rating": "T30"}, completeness=0.5)
        assert len(item.extractions) == 2


# --- Built-in schemas tests ---

class TestBuiltinSchemas:
    def test_door_spec_fields(self):
        door = DoorSpec()
        assert hasattr(door, "door_type")
        assert hasattr(door, "fire_rating")
        assert hasattr(door, "glazing")
        assert len(DoorSpec.model_fields) == 12

    def test_window_spec_fields(self):
        window = WindowSpec()
        assert hasattr(window, "window_type")
        assert hasattr(window, "u_value")
        assert len(WindowSpec.model_fields) == 10

    def test_wall_spec_fields(self):
        wall = WallSpec()
        assert hasattr(wall, "wall_type")
        assert hasattr(wall, "load_bearing")
        assert len(WallSpec.model_fields) == 10

    def test_pipe_spec_fields(self):
        pipe = PipeSpec()
        assert hasattr(pipe, "pipe_type")
        assert hasattr(pipe, "diameter_mm")
        assert len(PipeSpec.model_fields) == 10

    def test_all_have_descriptions(self):
        for schema in [DoorSpec, WindowSpec, WallSpec, PipeSpec]:
            for name, field_info in schema.model_fields.items():
                assert field_info.description, (
                    f"{schema.__name__}.{name} missing Field(description=...)"
                )

    def test_schemas_are_instructor_compatible(self):
        """All schemas should produce valid JSON schemas for instructor."""
        for schema in [DoorSpec, WindowSpec, WallSpec, PipeSpec]:
            json_schema = schema.model_json_schema()
            assert "properties" in json_schema
            assert "title" in json_schema
