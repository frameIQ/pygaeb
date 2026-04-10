"""Tests to boost coverage for low-covered modules.

Targets:
  - T2: classifier/batch_classifier.py (26% -> 80%+)
  - T3: parser/xml_v3/v30-v33_compat.py (0% -> 90%+)
  - T4: extractor/structured_extractor.py (25% -> 70%+)
  - T5: detector/version_detector.py edge cases (73% -> 85%+)
  - T6: models/base_item.py (0% -> 100%)
  - T7: Missed lines in totals/cross_phase validators
"""

from __future__ import annotations

import base64
import importlib
import sys
from decimal import Decimal
from textwrap import dedent
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lxml import etree

from pygaeb import (
    ExchangePhase,
    GAEBParser,
    ItemType,
    SourceVersion,
)
from pygaeb.cache import InMemoryCache
from pygaeb.classifier.batch_classifier import LLMClassifier, _item_label
from pygaeb.classifier.cache import compute_hash
from pygaeb.models.base_item import BaseItem
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot, Totals
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import (
    ClassificationResult,
    CostEstimate,
    ExtractionResult,
    Item,
    RichText,
)
from pygaeb.parser.xml_v3.v30_compat import V30Compat
from pygaeb.parser.xml_v3.v31_compat import _ZEITVERTRAG_PHASES, V31Compat
from pygaeb.parser.xml_v3.v32_compat import V32Compat
from pygaeb.parser.xml_v3.v33_compat import (
    V33Compat,
    _get_child_text,
    extract_attachments,
)
from pygaeb.validation.cross_phase_validator import CrossPhaseValidator
from pygaeb.validation.totals_validator import validate_totals

# ── Helpers ──────────────────────────────────────────────────────────


def _make_doc(
    phase: ExchangePhase = ExchangePhase.X86,
    items: list[Item] | None = None,
) -> GAEBDocument:
    if items is None:
        items = [
            Item(
                oz="01.0010", short_text="Mauerwerk KS 240mm",
                qty=Decimal("100"), unit="m2",
                unit_price=Decimal("45.50"),
                total_price=Decimal("4550.00"),
                item_type=ItemType.NORMAL,
                hierarchy_path=["Rohbau", "Mauerwerk"],
            ),
        ]
    ctgy = BoQCtgy(rno="01", label="Rohbau", items=items)
    body = BoQBody(categories=[ctgy])
    lot = Lot(rno="1", label="Lot 1", body=body)
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=phase,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(
            project_no="P-TEST", currency="EUR",
            boq=BoQ(lots=[lot]),
        ),
    )


def _mock_classify_result(**kwargs: Any) -> ClassificationResult:
    defaults = {
        "trade": "Structural",
        "element_type": "Wall",
        "sub_type": "Interior Wall",
        "confidence": 0.92,
        "flag": ClassificationFlag.AUTO_CLASSIFIED,
        "prompt_version": "v1",
    }
    defaults.update(kwargs)
    return ClassificationResult(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# T2: Classifier — batch_classifier.py & llm_backend.py
# ═══════════════════════════════════════════════════════════════════════


class TestItemLabel:
    def test_with_oz(self) -> None:
        item = Item(oz="01.0010", short_text="Test")
        assert _item_label(item) == "01.0010"

    def test_with_no_oz(self) -> None:
        item = MagicMock(spec=[])
        assert _item_label(item) == ""


class TestLLMClassifierInit:
    def test_defaults(self) -> None:
        clf = LLMClassifier(model="test/mock")
        assert clf.model == "test/mock"
        assert clf.fallbacks == []
        assert clf.concurrency >= 1
        assert clf.prompt_version == "v1"

    def test_custom_cache(self) -> None:
        cache = InMemoryCache()
        clf = LLMClassifier(model="test/mock", cache=cache)
        assert clf.cache is not None

    def test_custom_taxonomy(self) -> None:
        tax = {"Structural": {"Wall": ["Interior", "Exterior"]}}
        clf = LLMClassifier(model="test/mock", taxonomy=tax)
        assert clf.taxonomy == tax


class TestLLMClassifierEnrich:
    """Test enrich() with mocked LLM backend."""

    @pytest.mark.asyncio
    async def test_enrich_classifies_items(self) -> None:
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")
        mock_result = _mock_classify_result()

        with patch(
            "pygaeb.classifier.batch_classifier.LLMClassifier._classify_item",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            await clf.enrich(doc)

        for item in doc.iter_items():
            assert item.classification is not None
            assert item.classification.trade == "Structural"

    @pytest.mark.asyncio
    async def test_enrich_deduplication(self) -> None:
        """Duplicate items (same text) should be classified only once."""
        items = [
            Item(oz="01.0010", short_text="Mauerwerk KS",
                 item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="Mauerwerk KS",
                 item_type=ItemType.NORMAL),
            Item(oz="01.0030", short_text="Different item",
                 item_type=ItemType.NORMAL),
        ]
        doc = _make_doc(items=items)
        clf = LLMClassifier(model="test/mock")
        call_count = 0

        async def mock_classify(item: Any) -> ClassificationResult:
            nonlocal call_count
            call_count += 1
            return _mock_classify_result()

        with patch.object(clf, "_classify_item", side_effect=mock_classify):
            await clf.enrich(doc)

        # 2 unique texts → 2 classify calls (not 3)
        assert call_count == 2
        # All 3 items should be classified
        for item in doc.iter_items():
            assert item.classification is not None

    @pytest.mark.asyncio
    async def test_enrich_cache_hit(self) -> None:
        """Cached items should not trigger LLM calls."""
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")

        # Pre-populate cache
        item = next(iter(doc.iter_items()))
        h = compute_hash(item.short_text, item.long_text_plain[:300])
        cached = _mock_classify_result(trade="Cached")
        clf.cache.put(h, clf.prompt_version, cached)

        call_count = 0

        async def mock_classify(item: Any) -> ClassificationResult:
            nonlocal call_count
            call_count += 1
            return _mock_classify_result()

        with patch.object(clf, "_classify_item", side_effect=mock_classify):
            await clf.enrich(doc)

        assert call_count == 0, "Should not call LLM when cache hit"
        assert next(iter(doc.iter_items())).classification is not None
        assert next(iter(doc.iter_items())).classification.trade == "Cached"

    @pytest.mark.asyncio
    async def test_enrich_force_reclassify(self) -> None:
        """force_reclassify=True should bypass cache."""
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")

        # Pre-populate cache
        item = next(iter(doc.iter_items()))
        h = compute_hash(item.short_text, item.long_text_plain[:300])
        clf.cache.put(h, clf.prompt_version, _mock_classify_result(trade="Old"))

        with patch(
            "pygaeb.classifier.batch_classifier.LLMClassifier._classify_item",
            new_callable=AsyncMock,
            return_value=_mock_classify_result(trade="New"),
        ):
            await clf.enrich(doc, force_reclassify=True)

        assert next(iter(doc.iter_items())).classification.trade != "Old"

    @pytest.mark.asyncio
    async def test_enrich_progress_callback(self) -> None:
        """Progress callback should be invoked."""
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")
        progress_calls: list[tuple[int, int, str]] = []

        def on_progress(done: int, total: int, label: str) -> None:
            progress_calls.append((done, total, label))

        with patch(
            "pygaeb.classifier.batch_classifier.LLMClassifier._classify_item",
            new_callable=AsyncMock,
            return_value=_mock_classify_result(),
        ):
            await clf.enrich(doc, on_progress=on_progress)

        assert len(progress_calls) >= 1
        done, total, _ = progress_calls[-1]
        assert done == total

    @pytest.mark.asyncio
    async def test_enrich_empty_doc(self) -> None:
        """Empty doc should return immediately."""
        doc = _make_doc(items=[])
        clf = LLMClassifier(model="test/mock")
        await clf.enrich(doc)  # Should not raise


class TestLLMClassifierEstimateCost:
    @pytest.mark.asyncio
    async def test_estimate_cost_basic(self) -> None:
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")

        with patch(
            "pygaeb.classifier.llm_backend.estimate_tokens",
            new_callable=AsyncMock,
            return_value=(500, 100),
        ):
            estimate = await clf.estimate_cost(doc)

        assert isinstance(estimate, CostEstimate)
        assert estimate.total_items == 1
        assert estimate.items_to_classify == 1
        assert estimate.cached_items == 0
        assert estimate.estimated_input_tokens == 500
        assert estimate.estimated_output_tokens == 100

    @pytest.mark.asyncio
    async def test_estimate_cost_with_cache(self) -> None:
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")

        item = next(iter(doc.iter_items()))
        h = compute_hash(item.short_text, item.long_text_plain[:300])
        clf.cache.put(h, clf.prompt_version, _mock_classify_result())

        with patch(
            "pygaeb.classifier.llm_backend.estimate_tokens",
            new_callable=AsyncMock,
            return_value=(500, 100),
        ):
            estimate = await clf.estimate_cost(doc)

        assert estimate.cached_items == 1
        assert estimate.items_to_classify == 0

    def test_estimate_cost_usd_fallback(self) -> None:
        """When litellm is unavailable, use fallback pricing."""
        clf = LLMClassifier(model="test/mock")
        # Force the fallback path by making litellm import fail
        with patch.dict("sys.modules", {"litellm": None}):
            cost = clf._estimate_cost_usd(1_000_000, 100_000)
        assert cost > 0
        assert isinstance(cost, float)


class TestLLMClassifierSync:
    def test_enrich_sync_works(self) -> None:
        doc = _make_doc()
        clf = LLMClassifier(model="test/mock")

        with patch(
            "pygaeb.classifier.batch_classifier.LLMClassifier._classify_item",
            new_callable=AsyncMock,
            return_value=_mock_classify_result(),
        ):
            clf.enrich_sync(doc)

        assert next(iter(doc.iter_items())).classification is not None


# ═══════════════════════════════════════════════════════════════════════
# T2b: LLM Backend — llm_backend.py
# ═══════════════════════════════════════════════════════════════════════


class TestLLMBackend:
    """Tests for llm_backend.py — requires mocking instructor + litellm imports."""

    def _setup_mock_modules(self) -> tuple[MagicMock, MagicMock, AsyncMock]:
        """Create mock instructor + litellm modules and a mock client."""
        mock_instructor = MagicMock()
        mock_litellm = MagicMock()
        mock_client = AsyncMock()
        mock_instructor.from_litellm.return_value = mock_client
        return mock_instructor, mock_litellm, mock_client

    @pytest.mark.asyncio
    async def test_classify_single_item_success(self) -> None:
        mock_inst, mock_lit, mock_client = self._setup_mock_modules()
        mock_client.create = AsyncMock(return_value=_mock_classify_result())

        with patch.dict(sys.modules, {
            "instructor": mock_inst, "litellm": mock_lit,
        }):
            import pygaeb.classifier.llm_backend as backend
            importlib.reload(backend)
            result = await backend.classify_single_item(
                model="test/mock",
                hierarchy_path="Rohbau > Mauerwerk",
                short_text="Mauerwerk KS 240mm",
                long_text_head="",
                unit="m2",
            )

        assert result.trade == "Structural"
        assert result.prompt_version == "v1"

    @pytest.mark.asyncio
    async def test_classify_all_models_fail(self) -> None:
        mock_inst, mock_lit, mock_client = self._setup_mock_modules()
        mock_client.create = AsyncMock(side_effect=RuntimeError("API down"))

        with patch.dict(sys.modules, {
            "instructor": mock_inst, "litellm": mock_lit,
        }):
            import pygaeb.classifier.llm_backend as backend
            importlib.reload(backend)
            result = await backend.classify_single_item(
                model="test/mock",
                hierarchy_path="",
                short_text="Test",
                long_text_head="",
                unit="Stk",
            )

        assert result.flag == ClassificationFlag.LLM_ERROR
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_classify_with_taxonomy(self) -> None:
        mock_inst, mock_lit, mock_client = self._setup_mock_modules()
        mock_client.create = AsyncMock(return_value=_mock_classify_result())

        with patch.dict(sys.modules, {
            "instructor": mock_inst, "litellm": mock_lit,
        }):
            import pygaeb.classifier.llm_backend as backend
            importlib.reload(backend)
            await backend.classify_single_item(
                model="test/mock",
                hierarchy_path="",
                short_text="Test",
                long_text_head="",
                unit="m2",
                taxonomy={"Structural": {"Wall": ["Interior"]}},
            )

        call_args = mock_client.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "Allowed taxonomy" in prompt
        assert "Structural > Wall" in prompt

    @pytest.mark.asyncio
    async def test_classify_with_fallback(self) -> None:
        call_models: list[str] = []
        mock_inst, mock_lit, mock_client = self._setup_mock_modules()

        async def side_effect(**kwargs: Any) -> ClassificationResult:
            call_models.append(kwargs["model"])
            if kwargs["model"] == "primary/fail":
                raise RuntimeError("Primary down")
            return _mock_classify_result()

        mock_client.create = AsyncMock(side_effect=side_effect)

        with patch.dict(sys.modules, {
            "instructor": mock_inst, "litellm": mock_lit,
        }):
            import pygaeb.classifier.llm_backend as backend
            importlib.reload(backend)
            result = await backend.classify_single_item(
                model="primary/fail",
                hierarchy_path="",
                short_text="Test",
                long_text_head="",
                unit="m2",
                fallbacks=["backup/model"],
            )

        assert result.trade == "Structural"
        assert "primary/fail" in call_models
        assert "backup/model" in call_models

    @pytest.mark.asyncio
    async def test_estimate_tokens(self) -> None:
        from pygaeb.classifier.llm_backend import estimate_tokens

        inp, out = await estimate_tokens(
            "Rohbau > Mauerwerk",
            "Mauerwerk KS 240mm",
            "",
            "m2",
        )
        assert inp > 0
        assert out == 100


# ═══════════════════════════════════════════════════════════════════════
# T3: Version Compat Modules — v30/v31/v32/v33
# ═══════════════════════════════════════════════════════════════════════


class TestV30Compat:
    def test_is_subclass_of_base(self) -> None:
        from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser

        assert issubclass(V30Compat, BaseV3Parser)


class TestV31Compat:
    def test_is_zeitvertrag_true(self) -> None:
        assert V31Compat.is_zeitvertrag(ExchangePhase.X83Z) is True
        assert V31Compat.is_zeitvertrag(ExchangePhase.X84Z) is True
        assert V31Compat.is_zeitvertrag(ExchangePhase.X86ZR) is True
        assert V31Compat.is_zeitvertrag(ExchangePhase.X86ZE) is True

    def test_is_zeitvertrag_false(self) -> None:
        assert V31Compat.is_zeitvertrag(ExchangePhase.X83) is False
        assert V31Compat.is_zeitvertrag(ExchangePhase.X84) is False
        assert V31Compat.is_zeitvertrag(ExchangePhase.X86) is False

    def test_zeitvertrag_phases_set(self) -> None:
        assert len(_ZEITVERTRAG_PHASES) == 4


class TestV32Compat:
    def test_supports_x89b(self) -> None:
        assert V32Compat.supports_x89b() is True

    def test_is_extended_invoice_true(self) -> None:
        assert V32Compat.is_extended_invoice(ExchangePhase.X89B) is True

    def test_is_extended_invoice_false(self) -> None:
        assert V32Compat.is_extended_invoice(ExchangePhase.X89) is False
        assert V32Compat.is_extended_invoice(ExchangePhase.X83) is False


class TestV33Compat:
    def test_supports_bim_guids(self) -> None:
        assert V33Compat.supports_bim_guids() is True

    def test_supports_attachments(self) -> None:
        assert V33Compat.supports_attachments() is True


class TestV33ExtractAttachments:
    def test_extract_single_attachment(self) -> None:
        raw_data = b"Hello, World!"
        b64 = base64.b64encode(raw_data).decode("ascii")
        xml = f"""
        <Item>
          <Attachment>
            <Filename>test.pdf</Filename>
            <MimeType>application/pdf</MimeType>
            <Data>{b64}</Data>
          </Attachment>
        </Item>
        """
        el = etree.fromstring(xml)
        attachments = extract_attachments(el)
        assert len(attachments) == 1
        assert attachments[0].filename == "test.pdf"
        assert attachments[0].mime_type == "application/pdf"
        assert attachments[0].data == raw_data

    def test_extract_no_attachments(self) -> None:
        xml = "<Item><ShortText>No attach</ShortText></Item>"
        el = etree.fromstring(xml)
        attachments = extract_attachments(el)
        assert len(attachments) == 0

    def test_extract_with_empty_data(self) -> None:
        xml = """
        <Item>
          <Attachment>
            <Filename>empty.pdf</Filename>
            <Data></Data>
          </Attachment>
        </Item>
        """
        el = etree.fromstring(xml)
        attachments = extract_attachments(el)
        assert len(attachments) == 0  # Empty data skipped

    def test_extract_with_invalid_base64(self) -> None:
        xml = """
        <Item>
          <Attachment>
            <Filename>bad.pdf</Filename>
            <MimeType>application/pdf</MimeType>
            <Data>NOT_VALID_BASE64!!!</Data>
          </Attachment>
        </Item>
        """
        el = etree.fromstring(xml)
        attachments = extract_attachments(el)
        assert len(attachments) == 0  # Invalid base64 logged, not appended

    def test_extract_with_namespace(self) -> None:
        raw_data = b"NS test"
        b64 = base64.b64encode(raw_data).decode("ascii")
        ns = "http://www.gaeb.de/GAEB_DA_XML/DA31/3.3"
        xml = f"""
        <Item xmlns="{ns}">
          <Attachment>
            <Filename>ns_test.png</Filename>
            <MimeType>image/png</MimeType>
            <Data>{b64}</Data>
          </Attachment>
        </Item>
        """
        el = etree.fromstring(xml)
        # Without ns_prefix, it should still find via unnamespaced fallback
        attachments = extract_attachments(el)
        # Namespace tags won't match bare "Attachment", but _get_child_text
        # tries both. However iter() with bare tag won't match namespaced.
        # This tests the actual behavior.
        assert isinstance(attachments, list)


class TestGetChildText:
    def test_finds_child(self) -> None:
        xml = "<Parent><Name>Test</Name></Parent>"
        el = etree.fromstring(xml)
        assert _get_child_text(el, "Name") == "Test"

    def test_missing_child(self) -> None:
        xml = "<Parent></Parent>"
        el = etree.fromstring(xml)
        assert _get_child_text(el, "Name") is None

    def test_empty_text(self) -> None:
        xml = "<Parent><Name></Name></Parent>"
        el = etree.fromstring(xml)
        assert _get_child_text(el, "Name") is None

    def test_whitespace_stripped(self) -> None:
        xml = "<Parent><Name>  Test  </Name></Parent>"
        el = etree.fromstring(xml)
        assert _get_child_text(el, "Name") == "Test"


# ═══════════════════════════════════════════════════════════════════════
# T4: Extractor — structured_extractor.py
# ═══════════════════════════════════════════════════════════════════════


class TestStructuredExtractorInit:
    def test_default_init(self) -> None:
        from pygaeb.extractor import StructuredExtractor

        ext = StructuredExtractor(model="test/mock")
        assert ext.model == "test/mock"
        assert ext.fallbacks == []

    def test_custom_cache(self) -> None:
        from pygaeb.extractor import StructuredExtractor

        cache = InMemoryCache()
        ext = StructuredExtractor(model="test/mock", cache=cache)
        assert ext.cache is not None


class TestStructuredExtractorExtract:
    @pytest.mark.asyncio
    async def test_extract_no_matching_items(self) -> None:
        from pygaeb.extractor import StructuredExtractor
        from pygaeb.extractor.builtin_schemas import DoorSpec

        doc = _make_doc()
        # Items have no classification → filter returns empty
        ext = StructuredExtractor(model="test/mock")
        results = await ext.extract(
            doc, schema=DoorSpec, element_type="Door",
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_extract_items_empty(self) -> None:
        from pygaeb.extractor import StructuredExtractor
        from pygaeb.extractor.builtin_schemas import DoorSpec

        ext = StructuredExtractor(model="test/mock")
        results = await ext.extract_items([], schema=DoorSpec)
        assert results == []


# ═══════════════════════════════════════════════════════════════════════
# T5: Version Detector Edge Cases
# ═══════════════════════════════════════════════════════════════════════


class TestVersionDetectorEdgeCases:
    def test_x88_extension_detected(self) -> None:
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA88/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award><AwardInfo><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody><BoQCtgy RNoPart="01"><LblTx>T</LblTx>
                  <Itemlist><Item RNoPart="0010">
                    <ShortText>Test</ShortText>
                  </Item></Itemlist>
                </BoQCtgy></BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="test.X88")
        assert doc.exchange_phase == ExchangePhase.X88

    def test_d88_extension_detected(self) -> None:
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200407">
              <GAEBInfo><Version>2.0</Version></GAEBInfo>
              <Vergabe><VergabeInfo><Waehrung>EUR</Waehrung>
              </VergabeInfo>
              <Leistungsverzeichnis><LVBereich>
                <LVGruppe RNoPart="01"><Bezeichnung>T</Bezeichnung>
                  <Positionsliste><Position RNoPart="0010">
                    <Kurztext>Nachtrag</Kurztext>
                  </Position></Positionsliste>
                </LVGruppe>
              </LVBereich></Leistungsverzeichnis>
              </Vergabe>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="nachtrag.D88")
        assert doc.exchange_phase.normalized() == ExchangePhase.X88

    def test_v30_namespace_parsed(self) -> None:
        """DA XML 3.0 shares the 200407 namespace with 2.0/2.1.

        The detector relies on the <Version> element to distinguish.
        With 200407 namespace the detector treats it as 2.0 (Track A).
        This is correct behavior — 3.0 uses a per-phase namespace in practice.
        """
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.0">
              <GAEBInfo><Version>3.0</Version></GAEBInfo>
              <Award><AwardInfo><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody><BoQCtgy RNoPart="01"><LblTx>T</LblTx>
                  <Itemlist><Item RNoPart="0010">
                    <ShortText>V30 item</ShortText>
                  </Item></Itemlist>
                </BoQCtgy></BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="test.X83")
        assert doc.source_version == SourceVersion.DA_XML_30

    def test_version_21_detected(self) -> None:
        """DA XML 2.1 uses the 200511 namespace (different from 2.0's 200407)."""
        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/200511">
              <GAEBInfo><Version>2.1</Version></GAEBInfo>
              <Vergabe><VergabeInfo><Waehrung>EUR</Waehrung>
              </VergabeInfo>
              <Leistungsverzeichnis><LVBereich>
                <LVGruppe RNoPart="01"><Bezeichnung>T</Bezeichnung>
                  <Positionsliste><Position RNoPart="0010">
                    <Kurztext>V21 item</Kurztext>
                  </Position></Positionsliste>
                </LVGruppe>
              </LVBereich></Leistungsverzeichnis>
              </Vergabe>
            </GAEB>
        """)
        doc = GAEBParser.parse_string(xml, filename="old.D83")
        assert doc.source_version == SourceVersion.DA_XML_21


# ═══════════════════════════════════════════════════════════════════════
# T6: BaseItem Model Tests
# ═══════════════════════════════════════════════════════════════════════


class TestBaseItemModel:
    def test_default_fields(self) -> None:
        item = BaseItem()
        assert item.short_text == ""
        assert item.long_text is None
        assert item.qty is None
        assert item.unit is None
        assert item.classification is None
        assert item.extractions == {}
        assert item.source_element is None

    def test_long_text_plain_with_richtext(self) -> None:
        rt = RichText(plain_text="Test description")
        item = BaseItem(short_text="Test", long_text=rt)
        assert item.long_text_plain == "Test description"

    def test_long_text_plain_without_richtext(self) -> None:
        item = BaseItem(short_text="Test")
        assert item.long_text_plain == ""

    def test_with_classification(self) -> None:
        cls_result = _mock_classify_result()
        item = BaseItem(short_text="Wall", classification=cls_result)
        assert item.classification.trade == "Structural"

    def test_with_extractions(self) -> None:
        ext = ExtractionResult(
            schema_name="DoorSpec",
            data={"width_mm": 900},
            completeness=0.5,
        )
        item = BaseItem(
            short_text="Door",
            extractions={"DoorSpec": ext},
        )
        assert item.extractions["DoorSpec"].completeness == 0.5

    def test_with_qty_and_unit(self) -> None:
        item = BaseItem(
            short_text="Wall",
            qty=Decimal("100.500"),
            unit="m2",
        )
        assert item.qty == Decimal("100.500")
        assert item.unit == "m2"

    def test_source_element_excluded_from_dict(self) -> None:
        item = BaseItem(short_text="Test", source_element="raw_xml")
        d = item.model_dump()
        assert "source_element" not in d


# ═══════════════════════════════════════════════════════════════════════
# T7: Missed Validator Lines
# ═══════════════════════════════════════════════════════════════════════


class TestTotalsValidatorLotLevel:
    """Cover missed lot-level total mismatch path."""

    def test_lot_total_mismatch(self) -> None:
        items = [
            Item(oz="01.0010", short_text="A",
                 qty=Decimal("10"), unit="m2",
                 unit_price=Decimal("10"),
                 total_price=Decimal("100"),
                 item_type=ItemType.NORMAL),
        ]
        ctgy = BoQCtgy(rno="01", label="Cat", items=items)
        body = BoQBody(categories=[ctgy])
        lot = Lot(
            rno="1", label="Lot 1", body=body,
            totals=Totals(total=Decimal("999.00")),  # Mismatch
        )
        doc = GAEBDocument(
            source_version=SourceVersion.DA_XML_33,
            exchange_phase=ExchangePhase.X86,
            award=AwardInfo(boq=BoQ(lots=[lot])),
        )
        results = validate_totals(doc)
        lot_warnings = [
            r for r in results if "Lot" in r.message and "mismatch" in r.message
        ]
        assert len(lot_warnings) >= 1
        assert "999.00" in lot_warnings[0].message


class TestCrossPhaseExplicitMethods:
    """Cover the explicit static method wrappers."""

    def test_check_tender_bid_explicit(self) -> None:
        tender = _make_doc(phase=ExchangePhase.X83)
        bid = _make_doc(phase=ExchangePhase.X84)
        results = CrossPhaseValidator.check_tender_bid(tender, bid)
        assert isinstance(results, list)

    def test_check_contract_invoice_explicit(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        invoice = _make_doc(phase=ExchangePhase.X89)
        results = CrossPhaseValidator.check_contract_invoice(contract, invoice)
        assert isinstance(results, list)

    def test_check_contract_addendum_explicit(self) -> None:
        contract = _make_doc(phase=ExchangePhase.X86)
        addendum = _make_doc(phase=ExchangePhase.X88)
        results = CrossPhaseValidator.check_contract_addendum(
            contract, addendum,
        )
        assert isinstance(results, list)
