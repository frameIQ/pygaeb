"""Phase-aware XSD lookup and validation (``pygaeb.parser.gaeb_parser``).

The GAEB distribution ships one schema per exchange phase; picking "any .xsd in
the folder" validated against the wrong phase. These cover the resolver's
layouts and the structured ``validate_xml`` result, using tiny hand-written
schemas — the official files are not bundled.
"""

from __future__ import annotations

from pathlib import Path

from pygaeb import ExchangePhase, GAEBParser, GAEBWriter, SourceVersion
from pygaeb.config import reset_settings
from pygaeb.parser.gaeb_parser import XsdResult, resolve_schema, validate_xml

MINI_XSD = """\
<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">
  <xs:element name="GAEB">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="A" type="xs:string"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MINI_XSD, encoding="utf-8")
    return path


class TestResolveSchema:
    def test_flat_official_layout(self, tmp_path: Path) -> None:
        wanted = _touch(tmp_path / "GAEB_DA_XML_83_3.3_2021-05.xsd")
        _touch(tmp_path / "GAEB_DA_XML_84_3.3_2021-05.xsd")
        _touch(tmp_path / "GAEB_DA_XML_Lib_3.3_2021-05.xsd")

        assert resolve_schema(tmp_path, SourceVersion.DA_XML_33, ExchangePhase.X83) == wanted
        # D-phases resolve to their X form.
        assert resolve_schema(tmp_path, SourceVersion.DA_XML_33, ExchangePhase.D83) == wanted

    def test_per_version_subdirectory(self, tmp_path: Path) -> None:
        wanted = _touch(tmp_path / "v33" / "GAEB_DA_XML_84_3.3_2021-05.xsd")
        assert resolve_schema(tmp_path, SourceVersion.DA_XML_33, ExchangePhase.X84) == wanted

    def test_legacy_single_file_fallback(self, tmp_path: Path) -> None:
        only = _touch(tmp_path / "v32" / "anything.xsd")
        assert resolve_schema(tmp_path, SourceVersion.DA_XML_32, ExchangePhase.X83) == only

        _touch(tmp_path / "v32" / "another.xsd")
        # Two unnamed files: no way to tell which phase — refuse to guess.
        assert resolve_schema(tmp_path, SourceVersion.DA_XML_32, ExchangePhase.X83) is None

    def test_missing_directory_or_phase(self, tmp_path: Path) -> None:
        assert resolve_schema(tmp_path / "nope", SourceVersion.DA_XML_33, ExchangePhase.X83) is None
        _touch(tmp_path / "GAEB_DA_XML_83_3.3_2021-05.xsd")
        assert resolve_schema(tmp_path, SourceVersion.DA_XML_33, ExchangePhase.X86) is None


class TestValidateXml:
    def test_reports_structured_errors(self, tmp_path: Path) -> None:
        _touch(tmp_path / "GAEB_DA_XML_83_3.3_test.xsd")

        v33, x83 = SourceVersion.DA_XML_33, ExchangePhase.X83
        good = validate_xml(b"<GAEB><A>x</A></GAEB>", v33, x83, tmp_path)
        assert isinstance(good, XsdResult)
        assert good.valid and good.errors == []

        bad = validate_xml(b"<GAEB><B/></GAEB>", v33, x83, tmp_path)
        assert bad is not None and not bad.valid
        assert bad.errors and "B" in bad.errors[0].message
        assert bad.errors[0].line == 1

    def test_none_when_nothing_configured(self) -> None:
        reset_settings()
        assert validate_xml(b"<GAEB/>", SourceVersion.DA_XML_33, ExchangePhase.X83) is None

    def test_writer_helper_returns_none_without_schema(self, sample_document) -> None:
        reset_settings()
        assert GAEBWriter.validate_against_xsd(sample_document) is None


class TestParserIntegration:
    def test_skip_message_names_version_and_phase(self, sample_v33_file, tmp_path: Path) -> None:
        doc = GAEBParser.parse(sample_v33_file, xsd_dir=str(tmp_path))
        infos = [r.message for r in doc.validation_results if "XSD" in r.message]
        assert infos and "3.3" in infos[0] and "X83" in infos[0]

    def test_schema_violations_become_warnings(self, sample_v33_file, tmp_path: Path) -> None:
        _touch(tmp_path / "GAEB_DA_XML_83_3.3_test.xsd")
        doc = GAEBParser.parse(sample_v33_file, xsd_dir=str(tmp_path))
        msgs = [
            r.message for r in doc.validation_results
            if r.message.startswith("XSD validation:")
        ]
        assert msgs, "the mini schema rejects a real GAEB root, so warnings are expected"
