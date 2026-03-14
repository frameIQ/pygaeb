"""Tests for format detection, version detection, and encoding repair."""



from pygaeb.detector.encoding_repair import repair_encoding
from pygaeb.detector.format_detector import FormatFamily, detect_format
from pygaeb.detector.version_detector import ParserTrack, detect_version
from pygaeb.models.enums import ExchangePhase, SourceVersion


class TestFormatDetector:
    def test_detects_xml(self, sample_v33_file):
        assert detect_format(sample_v33_file) == FormatFamily.DA_XML

    def test_detects_xml_from_extension(self, tmp_path):
        f = tmp_path / "test.X83"
        f.write_bytes(b"not xml content here")
        assert detect_format(f) == FormatFamily.DA_XML

    def test_unknown_format(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("random content")
        assert detect_format(f) == FormatFamily.UNKNOWN


class TestVersionDetector:
    def test_detects_v33(self, sample_v33_file):
        route = detect_version(sample_v33_file)
        assert route.version == SourceVersion.DA_XML_33
        assert route.track == ParserTrack.TRACK_B

    def test_detects_v20(self, sample_v20_file):
        route = detect_version(sample_v20_file)
        assert route.version == SourceVersion.DA_XML_20
        assert route.track == ParserTrack.TRACK_A

    def test_phase_from_extension(self, sample_v33_file):
        route = detect_version(sample_v33_file)
        assert route.exchange_phase == ExchangePhase.X83

    def test_d83_extension_phase(self, sample_v20_file):
        route = detect_version(sample_v20_file)
        assert route.exchange_phase == ExchangePhase.D83


class TestEncodingRepair:
    def test_utf8_passthrough(self):
        text, _enc = repair_encoding(b"Hello World")
        assert text == "Hello World"

    def test_strip_utf8_bom(self):
        raw = b"\xef\xbb\xbfHello"
        text, enc = repair_encoding(raw)
        assert text == "Hello"
        assert enc == "utf-8-sig"

    def test_windows_1252_repair(self):
        raw = "Mörtel für Mauerwerk".encode("windows-1252")
        text, _enc = repair_encoding(raw)
        assert "Mörtel" in text or "rtel" in text

    def test_binary_detection(self):
        raw = "Simple ASCII text\n".encode("ascii")
        text, _enc = repair_encoding(raw, is_xml=False)
        assert "Simple ASCII text" in text
