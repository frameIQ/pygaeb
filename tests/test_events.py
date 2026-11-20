"""Every lifecycle event fires, with the payload the extensibility guide lists."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pygaeb import GAEBParseError, GAEBParser, GAEBValidationError, GAEBWriter, ValidationMode
from pygaeb.cache import InMemoryCache
from pygaeb.classifier import LLMClassifier
from pygaeb.events import EventType, clear_subscribers, on_event
from pygaeb.models.item import ClassificationResult
from tests.conftest import SAMPLE_V33_XML

Heard = dict[EventType, list[dict[str, Any]]]


@pytest.fixture
def heard() -> Iterator[Heard]:
    """Record every event. Subscribers are process-wide, so clean up both ways."""
    clear_subscribers()
    log: Heard = {event: [] for event in EventType}
    for event in EventType:
        on_event(event, lambda payload, event=event: log[event].append(payload))
    yield log
    clear_subscribers()


def _with_duplicate_oz(tmp_path: Path) -> Path:
    # Two items numbered 0010 in one lot: a structural ERROR.
    f = tmp_path / "tender.X86"
    f.write_text(SAMPLE_V33_XML.replace('RNoPart="0020"', 'RNoPart="0010"'), encoding="utf-8")
    return f


class TestParseEvents:
    def test_a_parse_announces_start_and_completion(self, heard: Heard, sample_v33_file) -> None:
        GAEBParser.parse(sample_v33_file)
        assert heard[EventType.PARSE_STARTED] == [{"file": str(sample_v33_file)}]
        assert heard[EventType.PARSE_COMPLETED][0]["item_count"] > 0
        assert heard[EventType.PARSE_FAILED] == []

    def test_parse_bytes_announces_the_filename_hint(self, heard: Heard) -> None:
        GAEBParser.parse_bytes(SAMPLE_V33_XML.encode(), filename="upload.X86")
        assert heard[EventType.PARSE_STARTED] == [{"file": "upload.X86"}]

    def test_a_failed_parse_says_why(self, heard: Heard, tmp_path: Path) -> None:
        with pytest.raises(GAEBParseError):
            GAEBParser.parse(tmp_path / "missing.X83")
        failed = heard[EventType.PARSE_FAILED]
        assert [f["error"] for f in failed] == ["GAEBParseError"]
        assert "File not found" in failed[0]["message"]
        assert heard[EventType.PARSE_COMPLETED] == []


class TestValidationEvents:
    def test_lenient_parse_reports_errors_and_completes(
        self, heard: Heard, tmp_path: Path,
    ) -> None:
        GAEBParser.parse(_with_duplicate_oz(tmp_path))
        failed = heard[EventType.VALIDATION_FAILED]
        assert len(failed) == 1
        assert failed[0]["mode"] == "lenient"
        assert failed[0]["error_count"] >= 1
        assert heard[EventType.PARSE_COMPLETED]

    def test_strict_parse_reports_errors_before_it_raises(
        self, heard: Heard, tmp_path: Path,
    ) -> None:
        with pytest.raises(GAEBValidationError):
            GAEBParser.parse(_with_duplicate_oz(tmp_path), validation=ValidationMode.STRICT)
        assert heard[EventType.VALIDATION_FAILED][0]["mode"] == "strict"
        assert [f["error"] for f in heard[EventType.PARSE_FAILED]] == ["GAEBValidationError"]

    def test_a_clean_file_reports_no_validation_failure(
        self, heard: Heard, sample_v33_file,
    ) -> None:
        GAEBParser.parse(sample_v33_file)
        assert heard[EventType.VALIDATION_FAILED] == []


class TestWriteEvents:
    def test_a_write_announces_start_and_completion(
        self, heard: Heard, sample_v33_file, tmp_path: Path,
    ) -> None:
        doc = GAEBParser.parse(sample_v33_file)
        out = tmp_path / "out.X86"
        warnings = GAEBWriter.write(doc, out)
        started = heard[EventType.WRITE_STARTED]
        completed = heard[EventType.WRITE_COMPLETED]
        assert [s["file"] for s in started] == [str(out)]
        assert completed[0]["file"] == str(out)
        assert completed[0]["version"] == "3.3"
        assert completed[0]["item_count"] == doc.item_count
        assert completed[0]["warning_count"] == len(warnings)
        assert completed[0]["data_loss"] is False

    def test_to_bytes_reports_its_size_and_no_file(self, heard: Heard, sample_v33_file) -> None:
        doc = GAEBParser.parse(sample_v33_file)
        xml, _ = GAEBWriter.to_bytes(doc)
        completed = heard[EventType.WRITE_COMPLETED]
        assert completed[0]["file"] is None
        assert completed[0]["size"] == len(xml)

    def test_checking_against_the_schema_is_not_a_write(
        self, heard: Heard, sample_v33_file, tmp_path: Path,
    ) -> None:
        doc = GAEBParser.parse(sample_v33_file)
        GAEBWriter.validate_against_xsd(doc, xsd_dir=tmp_path)  # empty folder: no schema
        assert heard[EventType.WRITE_STARTED] == []
        assert heard[EventType.WRITE_COMPLETED] == []


class TestClassificationEvent:
    def test_counts_llm_calls_then_cache_hits(
        self, heard: Heard, sample_v33_file, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_llm(self: LLMClassifier, item: Any) -> ClassificationResult:
            return ClassificationResult(trade="Structural", element_type="Wall", confidence=0.9)

        monkeypatch.setattr(LLMClassifier, "_classify_item", fake_llm)
        doc = GAEBParser.parse(sample_v33_file)
        classifier = LLMClassifier(model="test/model", cache=InMemoryCache())

        classifier.enrich_sync(doc)
        first = heard[EventType.CLASSIFICATION_COMPLETED][0]
        assert first["model"] == "test/model"
        assert first["item_count"] == doc.item_count
        assert first["llm_calls"] == first["unique_texts"]
        assert first["cache_hits"] == 0
        assert first["errors"] == 0

        classifier.enrich_sync(doc)
        second = heard[EventType.CLASSIFICATION_COMPLETED][1]
        assert second["cache_hits"] == second["unique_texts"]
        assert second["llm_calls"] == 0
