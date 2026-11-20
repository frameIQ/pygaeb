"""A GAEB file says what it is: its version and exchange phase come from the file.

The file name used to decide the phase, and ``parse_bytes``/``parse_string``
assumed ``input.X83``: an award uploaded as bytes became a tender, a trade or
cost file an empty BoQ, and a conversion then wrote it without prices while
reporting no loss. The namespace alone decided the version, so BVBS's 3.1
files, which carry the 2.0 namespace, read as 2.0. GAEB 90 phases (``D83``)
reached the writer as they were and named a namespace no schema has.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pygaeb import (
    BoQBuilder,
    ExchangePhase,
    GAEBConverter,
    GAEBParser,
    GAEBWriter,
    SourceVersion,
)
from pygaeb.detector.format_detector import ParserTrack
from pygaeb.detector.version_detector import ParseRoute, detect_route
from pygaeb.models.enums import DocumentKind, ValidationSeverity
from pygaeb.writer.version_registry import WRITABLE_VERSIONS
from tests.conftest import SAMPLE_V20_XML, SAMPLE_V33_XML
from tests.document_kinds import DOCUMENT_KINDS, FIXTURES
from tests.test_qty_support import X31_XML
from tests.test_trade_parser import TRADE_X96_XML

DA86_33 = "http://www.gaeb.de/GAEB_DA_XML/DA86/3.3"
NS_200407 = "http://www.gaeb.de/GAEB_DA_XML/200407"

#: A minimal GAEB 90 file, as in test_tier23_features.
GAEB90 = "\n".join([
    "00" + "PRJ-001".ljust(20) + "Testprojekt".ljust(58),
    "01" + "01".ljust(8) + "Rohbau".ljust(70),
    "02" + "01.0010".ljust(14) + " " * 64,
    "03" + "Mauerwerk KS".ljust(78),
    "05" + "100,000".ljust(14) + "m2".ljust(10) + " " * 54,
    "06" + "45,50".ljust(14) + " " * 64,
    "07" + "4550,00".ljust(14) + " " * 64,
    "99" + " " * 78,
])


def _award(
    namespace: str = DA86_33, version: str | None = "3.3", dp: str | None = None,
) -> str:
    """The sample award with another namespace, <Version> and <DP>."""
    xml = SAMPLE_V33_XML.replace(DA86_33, namespace)
    xml = xml.replace(
        "<Version>3.3</Version>", f"<Version>{version}</Version>" if version else "",
    )
    if dp is not None:
        xml = xml.replace("<Award>", f"<Award>\n    <DP>{dp}</DP>", 1)
    return xml


def _route(xml: str, filename: str | None = None) -> ParseRoute:
    return detect_route(xml.encode("utf-8"), filename)


class TestTheVersion:
    def test_a_bvbs_31_file_is_31(self) -> None:
        # BVBS's 3.1 Prüfdateien: the 2.0 namespace, <Version>3.1</Version>.
        route = _route(_award(NS_200407, "3.1", "86"))
        assert route.version == SourceVersion.DA_XML_31
        assert route.track == ParserTrack.TRACK_B
        assert route.exchange_phase == ExchangePhase.X86
        assert route.warnings == []

    def test_a_shared_namespace_without_version_is_a_guess_and_says_so(self) -> None:
        route = _route(_award(NS_200407, None, "86"))
        assert route.version == SourceVersion.DA_XML_20
        assert route.warnings == [
            f"GAEBInfo has no <Version>, and {NS_200407} serves several versions; "
            "read as 2.0",
        ]

    def test_the_namespace_outranks_version(self) -> None:
        route = _route(_award("http://www.gaeb.de/GAEB_DA_XML/DA86/3.2", "3.3"))
        assert route.version == SourceVersion.DA_XML_32
        assert route.warnings == [
            "<Version> says 3.3 but the namespace "
            "http://www.gaeb.de/GAEB_DA_XML/DA86/3.2 is 3.2; read as 3.2",
        ]

    def test_an_unknown_version_reads_as_33_and_says_so(self) -> None:
        # DA XML 3.4 used to read as 3.3 without a word.
        route = _route(_award("http://www.gaeb.de/GAEB_DA_XML/DA86/3.4", "3.4"))
        assert route.version == SourceVersion.DA_XML_33
        assert any("3.4" in w and "not read" in w for w in route.warnings)

    def test_german_element_names_are_2x(self) -> None:
        xml = SAMPLE_V20_XML.replace("<Version>2.0</Version>", "<Version>3.1</Version>")
        route = _route(xml)
        assert route.version == SourceVersion.DA_XML_20
        assert route.track == ParserTrack.TRACK_A
        assert any("2.x element names" in w for w in route.warnings)

    @pytest.mark.parametrize(
        "version", sorted(WRITABLE_VERSIONS, key=lambda v: v.value), ids=lambda v: v.value,
    )
    def test_every_version_pygaeb_writes_reads_back_as_itself(
        self, version: SourceVersion,
    ) -> None:
        # The writer uses the 2.0 namespace for 2.0 to 3.0, so 2.1 and 3.0 read
        # back as 2.0 while only the namespace counted.
        doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
        data, _ = GAEBWriter.to_bytes(doc, target_version=version)
        again = GAEBParser.parse_bytes(data)
        assert again.source_version == version
        assert again.exchange_phase == ExchangePhase.X86
        assert again.item_count == doc.item_count


class TestThePhase:
    def test_the_namespace_names_it(self) -> None:
        route = _route(_award("http://www.gaeb.de/GAEB_DA_XML/DA84/3.3"))
        assert route.exchange_phase == ExchangePhase.X84

    def test_dp_names_it_where_the_namespace_does_not(self) -> None:
        assert _route(_award(NS_200407, "3.1", "84")).exchange_phase == ExchangePhase.X84

    def test_dp_refines_the_namespace(self) -> None:
        route = _route(_award("http://www.gaeb.de/GAEB_DA_XML/DA83/3.3", dp="83Z"))
        assert route.exchange_phase == ExchangePhase.X83Z
        assert route.warnings == []

    def test_dp_contradicting_the_namespace_loses_and_says_so(self) -> None:
        route = _route(_award(dp="84"))
        assert route.exchange_phase == ExchangePhase.X86
        assert route.warnings == [
            f"<DP> says X84 but the namespace {DA86_33} is X86; read as X86",
        ]

    def test_older_pygaeb_wrote_a_gaeb_90_phase_into_dp(self) -> None:
        assert _route(_award(NS_200407, "3.0", "D83")).exchange_phase == ExchangePhase.X83

    def test_an_order_confirmation_reads_as_the_award(self) -> None:
        # X87, Auftragsbestätigung, has no model yet. It used to read as a tender.
        route = _route(_award("http://www.gaeb.de/GAEB_DA_XML/DA87/3.3", dp="87"))
        assert route.exchange_phase == ExchangePhase.X86
        assert route.warnings == [
            "Phase 87 (Auftragsbestätigung, the award confirmed) is not supported; "
            "read as X86",
        ]

    def test_an_unknown_trade_phase_reads_as_an_order(self) -> None:
        xml = TRADE_X96_XML.replace("<DP>96</DP>", "<DP>98</DP>")
        xml = xml.replace("/DA96/", "/DA98/")
        route = _route(xml)
        assert route.exchange_phase == ExchangePhase.X96
        assert any("98" in w for w in route.warnings)

    def test_a_phase_of_another_kind_is_ignored(self) -> None:
        # An award cannot be a trade order, whatever its <DP> says.
        route = _route(_award(NS_200407, "3.1", "96"))
        assert route.exchange_phase == ExchangePhase.X83
        assert any("no phase of a procurement document" in w for w in route.warnings)

    def test_nothing_declared_reads_as_a_tender_and_says_so(self) -> None:
        route = _route(_award(NS_200407, "3.1"))
        assert route.exchange_phase == ExchangePhase.X83
        assert route.warnings == [
            "The file declares no exchange phase (no <DP>, no phase in its namespace); "
            "read as X83",
        ]

    def test_without_a_declaration_the_name_gives_the_phase_quietly(self) -> None:
        route = _route(_award(NS_200407, "3.1"), "contract.X86")
        assert route.exchange_phase == ExchangePhase.X86
        assert route.warnings == []

    def test_a_d31_name_reads_a_quantity_file(self) -> None:
        # .D31 used to miss the dispatcher's sets and run the procurement parser.
        xml = X31_XML.replace("http://www.gaeb.de/GAEB_DA_XML/DA31/3.3", NS_200407)
        xml = xml.replace("<DP>31</DP>", "")
        doc = GAEBParser.parse_string(xml, filename="measured.D31")
        assert doc.exchange_phase == ExchangePhase.X31
        assert doc.document_kind == DocumentKind.QUANTITY
        assert doc.item_count > 0


class TestBytesWithoutAName:
    @pytest.mark.parametrize("kind", list(DOCUMENT_KINDS))
    def test_every_kind_reads_as_it_does_with_its_name(self, kind: str) -> None:
        # Bytes of trade, cost and quantity files read as empty BoQs, and awards
        # as tenders, before the content decided.
        xml, filename = DOCUMENT_KINDS[kind]
        named = GAEBParser.parse_string(xml, filename=filename)
        unnamed = GAEBParser.parse_bytes(xml.encode("utf-8"))
        assert unnamed.exchange_phase == named.exchange_phase
        assert unnamed.document_kind == named.document_kind
        assert unnamed.item_count == named.item_count > 0
        assert unnamed.grand_total == named.grand_total

    def test_the_source_file_is_the_name_given_or_none(self) -> None:
        data = SAMPLE_V33_XML.encode("utf-8")
        assert GAEBParser.parse_bytes(data).source_file is None
        assert GAEBParser.parse_bytes(data, filename="a.X86").source_file == "a.X86"
        assert GAEBParser.parse_string(SAMPLE_V33_XML).source_file is None

    def test_gaeb_90_bytes_need_a_name_for_their_phase(self) -> None:
        doc = GAEBParser.parse_bytes(GAEB90.encode("utf-8"))
        assert doc.exchange_phase == ExchangePhase.X83
        assert any(
            r.message.startswith("GAEB 90 data without a file name gives no phase")
            for r in doc.validation_results
        )
        named = GAEBParser.parse_bytes(GAEB90.encode("utf-8"), filename="old.D86")
        assert named.exchange_phase == ExchangePhase.D86


def test_detection_warnings_are_findings(tmp_path: Path) -> None:
    # They were only logged.
    f = tmp_path / "tender.X83"
    f.write_text(SAMPLE_V33_XML, encoding="utf-8")
    doc = GAEBParser.parse(f)
    assert doc.exchange_phase == ExchangePhase.X86
    warnings = [r.message for r in doc.validation_results
                if r.severity is ValidationSeverity.WARNING]
    assert "The file name says X83, the file itself X86; read as X86" in warnings


class TestWriting:
    def test_a_gaeb_90_phase_is_written_as_its_da_xml_phase(self) -> None:
        # D83 used to give the DA86 namespace (the fallback) and <DP>D83</DP>.
        doc = GAEBParser.parse_string(SAMPLE_V33_XML)
        data, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.D83)
        assert b"/DA83/3.3" in data
        assert b"<DP>83</DP>" in data
        assert b"D83" not in data

    def test_a_phase_of_another_kind_is_refused(self) -> None:
        award = GAEBParser.parse_string(SAMPLE_V33_XML)
        with pytest.raises(ValueError, match="cannot be written as X93, a trade phase"):
            GAEBWriter.to_bytes(award, phase=ExchangePhase.X93)
        order = GAEBParser.parse_string(TRADE_X96_XML)
        with pytest.raises(ValueError, match="cannot be written as X86, a procurement phase"):
            GAEBWriter.to_bytes(order, phase=ExchangePhase.X86)


class TestConverting:
    def test_a_gaeb_90_tender_converts_to_a_da_xml_tender(self, tmp_path: Path) -> None:
        # The documented convert("old.D83", "new.X83") wrote the DA86 namespace
        # and <DP>D83</DP>, which no schema accepts.
        source = tmp_path / "old.D83"
        source.write_text(GAEB90, encoding="utf-8")
        output = tmp_path / "new.X83"
        report = GAEBConverter.convert(source, output)
        assert report.source_phase == ExchangePhase.D83
        assert report.target_phase == ExchangePhase.X83
        text = output.read_text(encoding="utf-8")
        assert "/DA83/3.3" in text
        assert "<DP>83</DP>" in text
        assert not any("is named as" in w for w in report.warnings)
        assert GAEBParser.parse(output).exchange_phase == ExchangePhase.X83

    def test_converting_to_another_phase_reports_what_it_leaves_out(
        self, tmp_path: Path,
    ) -> None:
        # Prices have no place in a tender; has_data_loss used to stay False.
        source = tmp_path / "award.X86"
        source.write_text(SAMPLE_V33_XML, encoding="utf-8")
        report = GAEBConverter.convert(
            source, tmp_path / "tender.X83", target_phase=ExchangePhase.X83,
        )
        assert report.has_data_loss
        assert {w.split(" ")[0] for w in report.fields_dropped} == {"UP", "IT"}

    def test_an_output_name_of_another_phase_is_pointed_out(self, tmp_path: Path) -> None:
        source = tmp_path / "award.X86"
        source.write_text(SAMPLE_V33_XML, encoding="utf-8")
        report = GAEBConverter.convert(source, tmp_path / "out.X83")
        assert report.target_phase == ExchangePhase.X86
        assert not report.has_data_loss
        assert (
            "out.X83 is named as X83 but holds X86; pass "
            "target_phase=ExchangePhase.X83 to write a X83"
        ) in report.warnings

    def test_gaeb_90_bytes_take_their_phase_from_source_filename(self) -> None:
        data, report = GAEBConverter.convert_bytes(
            GAEB90.encode("utf-8"), source_filename="old.D86",
        )
        assert report.source_phase == ExchangePhase.D86
        assert report.target_phase == ExchangePhase.X86
        assert b"<DP>86</DP>" in data


class TestBuilding:
    def test_a_gaeb_90_phase_builds_its_da_xml_phase(self) -> None:
        builder = BoQBuilder(phase="D83")
        builder.add_category("01", "Rohbau").add_item("01.0010", "Wand", qty=1, unit="m2")
        assert builder.build().exchange_phase == ExchangePhase.X83

    def test_other_kinds_are_refused(self) -> None:
        with pytest.raises(ValueError, match="X93 is a trade phase"):
            BoQBuilder(phase="X93")
