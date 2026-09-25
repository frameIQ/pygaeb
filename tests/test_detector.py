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


def _synthetic_order_document(namespace: str, items: int) -> str:
    """Build a DA XML style X93 document from scratch (no real GAEB content).

    ``items`` positions of a few hundred bytes each; 400 items give roughly
    250 KB, i.e. well over the 32 KB chunk lxml's iterparse feeds libxml2.
    """
    body = "\n".join(
        f'  <OrderItem ID="ID{i}">\n'
        f"   <Qty>1.00</Qty>\n"
        f"   <QU>ST</QU>\n"
        f"   <Description><CompleteText><DetailTxt><Text>\n"
        + "\n".join(
            f"    <span>Synthetic item {i} line {j} lorem ipsum dolor sit amet</span><br/>"
            for j in range(8)
        )
        + "\n   </Text></DetailTxt></CompleteText></Description>\n"
        "  </OrderItem>"
        for i in range(1, items + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<GAEB xmlns="{namespace}">\n'
        " <GAEBInfo>\n"
        "  <Version>3.1</Version>\n"
        "  <VersDate>2010-09</VersDate>\n"
        "  <Date>2026-01-01</Date>\n"
        "  <Time>00:00:00</Time>\n"
        "  <ProgSystem>synthetic</ProgSystem>\n"
        "  <ProgName>synthetic</ProgName>\n"
        " </GAEBInfo>\n"
        " <Order>\n"
        "  <DP>93</DP>\n"
        f"{body}\n"
        " </Order>\n"
        "</GAEB>\n"
    )


class TestDetectorStopsAfterHeader:
    """Regression tests for GH-44 (heap corruption via elem.clear() on start events).

    The corruption itself only surfaces under a debug allocator, so the reliable
    guard is the number of iterparse events the detector consumes: it must stop
    right after the header (root, GAEBInfo, first phase element) no matter
    whether the namespace is known.
    """

    @staticmethod
    def _count_events(monkeypatch):
        import pygaeb.detector.version_detector as vd

        seen: list[str] = []
        real = vd.safe_iterparse

        def counting(*args, **kwargs):
            for event, elem in real(*args, **kwargs):
                seen.append(elem.tag)
                yield event, elem

        monkeypatch.setattr(vd, "safe_iterparse", counting)
        return seen

    def test_unknown_namespace_large_file(self, tmp_path, monkeypatch):
        xml = _synthetic_order_document("http://www.gaeb.de/GAEB_DA_XML/209912", 400)
        f = tmp_path / "unknown.X93"
        f.write_text(xml, encoding="utf-8")
        assert f.stat().st_size > 200_000

        seen = self._count_events(monkeypatch)
        route = detect_version(f)

        # root + GAEBInfo + its six children + Order: the loop must not go on
        # into the 400 OrderItems.
        assert len(seen) == 9
        assert seen[-1].endswith("}Order")
        assert route.namespace == "http://www.gaeb.de/GAEB_DA_XML/209912"
        # Unknown namespace: either the extension fallback (3.3) or, once the
        # detector reads <Version>, the declared 3.1. The event count is the guard.
        assert route.version in (SourceVersion.DA_XML_31, SourceVersion.DA_XML_33)
        assert route.exchange_phase == ExchangePhase.X93

    def test_known_namespace_stops_at_root(self, tmp_path, monkeypatch):
        xml = _synthetic_order_document("http://www.gaeb.de/GAEB_DA_XML/200706", 400)
        f = tmp_path / "known.X93"
        f.write_text(xml, encoding="utf-8")

        seen = self._count_events(monkeypatch)
        route = detect_version(f)

        assert len(seen) == 1
        assert route.version == SourceVersion.DA_XML_31

    def test_no_gaeb_header_hits_event_cap(self, tmp_path, monkeypatch):
        import pygaeb.detector.version_detector as vd

        rows = "\n".join(f"<row id='{i}'><v>{i}</v></row>" for i in range(2000))
        f = tmp_path / "foreign.X83"
        f.write_text(f"<data>{rows}</data>", encoding="utf-8")

        seen = self._count_events(monkeypatch)
        route = detect_version(f)

        assert len(seen) == vd._MAX_HEADER_EVENTS
        assert any("stopped version detection" in w for w in route.warnings)
        assert route.version == SourceVersion.DA_XML_33


class TestNamespace200706:
    """DA XML 3.1 files (GXML Toolbox, Version 3.1 / VersDate 2010-09) use .../200706."""

    def test_maps_to_da_xml_31(self, tmp_path):
        f = tmp_path / "settlement.X93"
        f.write_text(
            _synthetic_order_document("http://www.gaeb.de/GAEB_DA_XML/200706", 1),
            encoding="utf-8",
        )
        route = detect_version(f)
        assert route.version == SourceVersion.DA_XML_31
        assert route.track == ParserTrack.TRACK_B
        assert route.exchange_phase == ExchangePhase.X93
        assert route.namespace == "http://www.gaeb.de/GAEB_DA_XML/200706"
        assert route.warnings == []

    def test_x94_extension(self, tmp_path):
        f = tmp_path / "invoice.X94"
        f.write_text(
            _synthetic_order_document("http://www.gaeb.de/GAEB_DA_XML/200706", 1),
            encoding="utf-8",
        )
        route = detect_version(f)
        assert route.version == SourceVersion.DA_XML_31
        assert route.exchange_phase == ExchangePhase.X94
