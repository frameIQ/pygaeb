"""A GAEB file reads the same whatever encoding it was saved in.

pyGAEB decodes the bytes itself, then hands lxml UTF-8. Until 1.20.0 the
file's own declaration (ISO-8859-1, UTF-16, ...) went along with those bytes,
so lxml decoded them a second time and garbled every non-ASCII character.
"""

from __future__ import annotations

import codecs
from pathlib import Path
from typing import Any

import pytest

from pygaeb.detector.encoding_repair import declare_utf8, repair_encoding
from pygaeb.detector.format_detector import FormatFamily, detect_format
from pygaeb.detector.version_detector import detect_version
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import SourceVersion
from pygaeb.parser import GAEBParser

FIXTURE = Path(__file__).parent / "fixtures" / "gaebxml.x83"
SHORT = "Baustelleneinrichtung"
# Umlauts, €, a letter beyond Latin-1, and typographic dash, quotes and apostrophe.
TEXT = f"{SHORT} Größe 25 € Ω – „Zoll“ it’s"  # noqa: RUF001 — typographic marks are the point
XML = FIXTURE.read_text(encoding="utf-8").replace(SHORT, TEXT, 1)

ANY_GAEB_XSD = """\
<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="{namespace}" elementFormDefault="qualified">
  <xs:element name="GAEB">
    <xs:complexType>
      <xs:sequence>
        <xs:any processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _declared(label: str) -> str:
    return XML.replace('encoding="utf-8"', f'encoding="{label}"', 1)


def _single_byte(codec: str, label: str) -> bytes:
    # Characters the codec lacks become character references, as exporters write them.
    return _declared(label).encode(codec, "xmlcharrefreplace")


SAVED_AS = {
    "UTF-8": XML.encode("utf-8"),
    "UTF-8 with BOM": codecs.BOM_UTF8 + XML.encode("utf-8"),
    "ISO-8859-1": _single_byte("latin-1", "ISO-8859-1"),
    "ISO-8859-15": _single_byte("iso-8859-15", "ISO-8859-15"),
    "Windows-1252": _single_byte("cp1252", "windows-1252"),
    "UTF-16 LE with BOM": codecs.BOM_UTF16_LE + _declared("UTF-16").encode("utf-16-le"),
    "UTF-16 BE with BOM": codecs.BOM_UTF16_BE + _declared("UTF-16").encode("utf-16-be"),
    "UTF-16 LE without BOM": _declared("UTF-16").encode("utf-16-le"),
    "UTF-16 BE without BOM": _declared("UTF-16").encode("utf-16-be"),
    "UTF-32 LE with BOM": codecs.BOM_UTF32_LE + _declared("UTF-32").encode("utf-32-le"),
    # Wrong labels found in real exports
    "UTF-8 labelled UTF-16": _declared("utf-16").encode("utf-8"),
    "Windows-1252 labelled UTF-8": XML.encode("cp1252", "xmlcharrefreplace"),
    "UTF-8 labelled ISO-8859-1": _declared("ISO-8859-1").encode("utf-8"),
}


def _snapshot(doc: GAEBDocument) -> dict[str, Any]:
    return doc.model_dump(mode="json", exclude={"source_file"})


@pytest.fixture(scope="module")
def reference() -> dict[str, Any]:
    return _snapshot(GAEBParser.parse_string(XML, "tender.X83"))


class TestEveryEncodingReadsTheSame:
    @pytest.mark.parametrize("saved_as", SAVED_AS)
    def test_parse(self, saved_as: str, tmp_path: Path, reference: dict[str, Any]) -> None:
        path = tmp_path / "tender.X83"
        path.write_bytes(SAVED_AS[saved_as])

        from_file = GAEBParser.parse(path)
        from_bytes = GAEBParser.parse_bytes(SAVED_AS[saved_as], "tender.X83")

        assert next(iter(from_file.iter_items())).short_text == TEXT
        assert _snapshot(from_file) == reference
        assert _snapshot(from_bytes) == reference

    @pytest.mark.parametrize("saved_as", SAVED_AS)
    def test_version_detection(self, saved_as: str, tmp_path: Path) -> None:
        path = tmp_path / "tender.X83"
        path.write_bytes(SAVED_AS[saved_as])

        route = detect_version(path)

        assert route.version == SourceVersion.DA_XML_32
        assert route.warnings == []

    @pytest.mark.parametrize("label", ["ISO-8859-1", "windows-1252", "UTF-16"])
    def test_parse_string_ignores_the_declared_encoding(
        self, label: str, reference: dict[str, Any],
    ) -> None:
        doc = GAEBParser.parse_string(_declared(label), "tender.X83")
        assert _snapshot(doc) == reference

    def test_utf16_file_without_a_gaeb_extension_is_xml(self, tmp_path: Path) -> None:
        path = tmp_path / "tender.xml"
        path.write_bytes(SAVED_AS["UTF-16 LE with BOM"])
        assert detect_format(path) == FormatFamily.DA_XML

    def test_xsd_validation_reads_a_utf16_file(
        self, tmp_path: Path, reference: dict[str, Any],
    ) -> None:
        schema = tmp_path / "GAEB_DA_XML_83_3.2_test.xsd"
        schema.write_text(
            ANY_GAEB_XSD.format(namespace=reference["raw_namespace"]), encoding="utf-8",
        )
        path = tmp_path / "tender.X83"
        path.write_bytes(SAVED_AS["UTF-16 LE with BOM"])

        doc = GAEBParser.parse(path, xsd_dir=str(tmp_path))

        assert [r.message for r in doc.validation_results if "XSD" in r.message] == []


class TestRepairEncoding:
    @pytest.mark.parametrize(("raw", "encoding"), [
        (b'<?xml version="1.0"?><a>x</a>', "utf-8"),
        (codecs.BOM_UTF8 + b"<a>x</a>", "utf-8-sig"),
        (b'<?xml version="1.0" encoding="ISO-8859-1"?><a>\xe4</a>', "iso8859-1"),
        (codecs.BOM_UTF16_LE + "<a>ä</a>".encode("utf-16-le"), "utf-16-le"),
        ("<?xml version='1.0' encoding='utf-16'?><a>ä</a>".encode(), "utf-8"),
        (b'<?xml version="1.0" encoding="UTF-8"?><a>\xe4</a>', "repaired"),
        ("<a>GrÃ¶ÃŸe</a>".encode(), "repaired-ftfy"),
    ])
    def test_reports_the_encoding_used(self, raw: bytes, encoding: str) -> None:
        assert repair_encoding(raw)[1] == encoding

    def test_declaration_names_utf8_afterwards(self) -> None:
        raw = b"<?xml version='1.0' encoding='ISO-8859-1' standalone='yes'?><a>\xe4</a>"
        text, _encoding = repair_encoding(raw)
        assert text == "<?xml version='1.0' encoding='UTF-8' standalone='yes'?><a>ä</a>"

    def test_keeps_typography(self) -> None:
        xml = "<a>„Zoll“ ‚x‘ it’s ﬁ ＡＢ</a>"  # noqa: RUF001 — what ftfy used to rewrite
        assert repair_encoding(xml.encode())[0] == xml

    def test_still_repairs_garbled_text(self) -> None:
        garbled = "<a>GrÃ¶ÃŸe 25 â‚¬</a>"  # noqa: RUF001 — UTF-8 read as Windows-1252
        assert repair_encoding(garbled.encode())[0] == "<a>Größe 25 €</a>"

    @pytest.mark.parametrize("text", [
        "<a>no declaration</a>",
        '<?xml version="1.0"?><a/>',
        '<a>encoding="latin-1" in content</a>',
    ])
    def test_declare_utf8_leaves_text_without_an_encoding_label(self, text: str) -> None:
        assert declare_utf8(text) == text
