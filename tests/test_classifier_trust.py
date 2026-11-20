"""The classifier and extractor never serve a stale or failed answer, and keep
what people decided by hand.

The LLM is faked at ``classify_single_item`` / ``StructuredExtractor._call_llm``,
so the taxonomy check and the caching around the call run for real.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from pygaeb import GAEBDocument, GAEBParser
from pygaeb.cache import InMemoryCache
from pygaeb.classifier import LLMClassifier
from pygaeb.classifier.cache import compute_hash
from pygaeb.extractor import StructuredExtractor
from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import ClassificationResult, Item, RichText
from tests.conftest import SAMPLE_V33_XML
from tests.test_qty_support import X31_XML

AUTO = ClassificationFlag.AUTO_CLASSIFIED
REVIEW = ClassificationFlag.NEEDS_REVIEW
MANUAL = ClassificationFlag.MANUAL_OVERRIDE


class FakeLLM:
    """Stands in for ``classify_single_item``: counts calls, answers as told."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answer = ClassificationResult(trade="Structural", element_type="Wall", confidence=0.9)

    async def __call__(self, **kwargs: Any) -> ClassificationResult:
        self.calls.append(kwargs)
        return self.answer.model_copy()


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr("pygaeb.classifier.llm_backend.classify_single_item", fake)
    return fake


def _tender() -> GAEBDocument:
    # Three positions with three different texts: three questions on a cold cache.
    return GAEBParser.parse_bytes(SAMPLE_V33_XML.encode(), filename="tender.X83")


def _items(doc: GAEBDocument) -> list[Item]:
    return [i for i in doc.iter_items() if isinstance(i, Item)]


def _classify(doc: GAEBDocument, cache: InMemoryCache | None = None, **settings: Any) -> None:
    settings.setdefault("model", "test/model")
    # "is not None": an empty cache is falsy, and "or" would swap in a fresh one.
    backend = cache if cache is not None else InMemoryCache()
    LLMClassifier(cache=backend, **settings).enrich_sync(doc)


class TestCacheKey:
    def test_the_same_setup_is_served_from_the_cache(self, llm: FakeLLM) -> None:
        backend = InMemoryCache()
        _classify(_tender(), backend)
        _classify(_tender(), backend)
        assert len(llm.calls) == 3

    @pytest.mark.parametrize("change", [
        {"model": "test/other"},
        {"prompt_template": "Classify, briefly."},
        {"taxonomy": {"Structural": {"Wall": []}}},
    ])
    def test_a_different_setup_asks_again(self, llm: FakeLLM, change: dict[str, Any]) -> None:
        backend = InMemoryCache()
        _classify(_tender(), backend)
        _classify(_tender(), backend, **change)
        assert len(llm.calls) == 6

    def test_the_unit_is_part_of_the_question(self, llm: FakeLLM) -> None:
        doc = _tender()
        a, b, _ = _items(doc)
        b.short_text = a.short_text  # same words, same section, same unit: one question
        _classify(doc)
        assert len(llm.calls) == 2
        b.unit = "m3"
        llm.calls.clear()
        _classify(doc)
        assert len(llm.calls) == 3

    def test_the_section_is_part_of_the_question(self, llm: FakeLLM) -> None:
        doc = _tender()
        a, _, c = _items(doc)  # c sits in another section
        c.short_text, c.unit = a.short_text, a.unit
        _classify(doc)
        assert len(llm.calls) == 3

    def test_items_sharing_an_answer_get_their_own_copy(self, llm: FakeLLM) -> None:
        doc = _tender()
        a, b, _ = _items(doc)
        b.short_text = a.short_text
        _classify(doc)
        assert a.classification is not None and b.classification is not None
        assert a.classification is not b.classification


class TestFailures:
    def test_a_failed_call_is_asked_again_next_run(self, llm: FakeLLM) -> None:
        llm.answer = ClassificationResult(
            trade="Other", element_type="Unclassifiable", flag=ClassificationFlag.LLM_ERROR,
        )
        backend = InMemoryCache()
        _classify(_tender(), backend)
        _classify(_tender(), backend)
        assert len(llm.calls) == 6


class TestManualOverrides:
    def test_an_item_marked_by_hand_is_left_alone(self, llm: FakeLLM) -> None:
        doc = _tender()
        mine = _items(doc)[0]
        mine.classification = ClassificationResult(
            trade="Finishes", element_type="Door", confidence=1.0, flag=MANUAL,
        )
        LLMClassifier(model="test/model", cache=InMemoryCache()).enrich_sync(
            doc, force_reclassify=True,
        )
        assert mine.classification.trade == "Finishes"
        assert len(llm.calls) == 2

    def test_a_saved_override_wins_even_when_forced(self, llm: FakeLLM) -> None:
        classifier = LLMClassifier(model="test/model", cache=InMemoryCache())
        decided = _items(_tender())[0]
        decided.classification = ClassificationResult(
            trade="Finishes", element_type="Door", confidence=1.0,
        )
        classifier.cache.save_override(decided)

        fresh = _tender()
        classifier.enrich_sync(fresh, force_reclassify=True)
        same = _items(fresh)[0]
        assert same.classification is not None
        assert (same.classification.trade, same.classification.flag) == ("Finishes", MANUAL)
        assert len(llm.calls) == 2

    def test_a_saved_override_outlives_a_model_change(self, llm: FakeLLM) -> None:
        backend = InMemoryCache()
        decided = _items(_tender())[0]
        decided.classification = ClassificationResult(trade="Finishes", element_type="Door")
        LLMClassifier(model="test/a", cache=backend).cache.save_override(decided)

        fresh = _tender()
        _classify(fresh, backend, model="test/b")
        first = _items(fresh)[0].classification
        assert first is not None and first.trade == "Finishes"

    def test_an_override_saved_by_pygaeb_1_21_is_still_found(self, llm: FakeLLM) -> None:
        # 1.21 stored overrides under compute_hash(short, long[:300]) and the prompt version.
        classifier = LLMClassifier(model="test/model", cache=InMemoryCache())
        fresh = _tender()
        item = _items(fresh)[0]
        legacy = ClassificationResult(trade="Finishes", element_type="Door", flag=MANUAL)
        key = compute_hash(item.short_text, item.long_text_plain[:300])
        classifier.cache.put(key, "v1", legacy, is_override=True)

        classifier.enrich_sync(fresh)
        assert item.classification is not None and item.classification.trade == "Finishes"


class TestItemsWithoutText:
    def test_a_quantity_document_is_skipped_not_crashed(self, llm: FakeLLM) -> None:
        doc = GAEBParser.parse_bytes(X31_XML.encode(), filename="takeoff.X31")
        _classify(doc)
        assert llm.calls == []


class TestTaxonomy:
    def test_the_built_in_prompt_flags_a_trade_it_did_not_offer(self, llm: FakeLLM) -> None:
        llm.answer = ClassificationResult(trade="Carpentry", element_type="Stair", confidence=0.95)
        doc = _tender()
        _classify(doc)
        assert {i.classification.flag for i in _items(doc) if i.classification} == {REVIEW}

    def test_the_built_in_prompt_takes_any_element_type(self, llm: FakeLLM) -> None:
        # Its element types are examples, not a closed list.
        llm.answer = ClassificationResult(trade="Structural", element_type="Stair", confidence=0.95)
        doc = _tender()
        _classify(doc)
        assert {i.classification.flag for i in _items(doc) if i.classification} == {AUTO}

    @pytest.mark.parametrize(("element", "sub", "flag"), [
        ("Window", "", REVIEW),
        ("Door", "Glass Door", REVIEW),
        ("Door", "Fire Door", AUTO),
        ("Door", "", AUTO),
    ])
    def test_a_custom_taxonomy_is_checked_to_the_sub_type(
        self, llm: FakeLLM, element: str, sub: str, flag: ClassificationFlag,
    ) -> None:
        llm.answer = ClassificationResult(
            trade="Doors", element_type=element, sub_type=sub, confidence=0.95,
        )
        doc = _tender()
        _classify(doc, taxonomy={"Doors": {"Door": ["Fire Door"]}})
        assert {i.classification.flag for i in _items(doc) if i.classification} == {flag}

    def test_a_custom_prompt_sets_its_own_rules(self, llm: FakeLLM) -> None:
        llm.answer = ClassificationResult(trade="Anything", element_type="Goes", confidence=0.95)
        doc = _tender()
        _classify(doc, prompt_template="Classify by my own trades.")
        assert {i.classification.flag for i in _items(doc) if i.classification} == {AUTO}


class Spec(BaseModel):
    width_mm: int | None = None


def _door(tail: str) -> Item:
    # The first 300 characters are the same for every door; only the tail differs.
    return Item(
        oz="0010", short_text="Tür", unit="Stk", long_text=RichText.from_plain("x" * 300 + tail),
    )


class TestExtractionRequests:
    @pytest.fixture
    def asked(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        messages: list[str] = []

        async def fake(self: Any, schema: Any, system_prompt: str, user_message: str) -> Spec:
            messages.append(user_message)
            return Spec(width_mm=900)

        monkeypatch.setattr(StructuredExtractor, "_call_llm", fake)
        return messages

    def test_the_whole_long_text_is_part_of_the_key(self, asked: list[str]) -> None:
        extractor = StructuredExtractor(model="test/model", cache=InMemoryCache())
        asyncio.run(extractor.extract_items([_door("Breite 900")], schema=Spec))
        asyncio.run(extractor.extract_items([_door("Breite 1000")], schema=Spec))
        assert len(asked) == 2

    def test_the_same_request_is_served_from_the_cache(self, asked: list[str]) -> None:
        extractor = StructuredExtractor(model="test/model", cache=InMemoryCache())
        asyncio.run(extractor.extract_items([_door("Breite 900")], schema=Spec))
        asyncio.run(extractor.extract_items([_door("Breite 900")], schema=Spec))
        assert len(asked) == 1

    def test_the_model_is_part_of_the_key(self, asked: list[str]) -> None:
        backend = InMemoryCache()
        door = _door("Breite 900")
        asyncio.run(StructuredExtractor(model="test/a", cache=backend).extract_items([door], Spec))
        asyncio.run(StructuredExtractor(model="test/b", cache=backend).extract_items([door], Spec))
        assert len(asked) == 2

    def test_a_failed_extraction_is_asked_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        async def failing(self: Any, schema: Any, system_prompt: str, user_message: str) -> None:
            calls.append(user_message)
            return None

        monkeypatch.setattr(StructuredExtractor, "_call_llm", failing)
        extractor = StructuredExtractor(model="test/model", cache=InMemoryCache())
        results = asyncio.run(extractor.extract_items([_door("Breite 900")], schema=Spec))
        asyncio.run(extractor.extract_items([_door("Breite 900")], schema=Spec))
        assert results[0][1] == Spec()
        assert len(calls) == 2
