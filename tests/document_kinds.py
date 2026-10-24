"""One small sample per document kind, for tests that must hold for every kind.

Each entry is ``(xml, filename)``; the filename tells the parser the exchange phase.
"""

from __future__ import annotations

from pathlib import Path

from pygaeb import GAEBParser, GAEBWriter, SourceVersion
from tests.test_cost_support import X50_XML, X52_XML
from tests.test_findings_v141 import TRADE_WITH_CTLG
from tests.test_qty_support import X31_XML
from tests.test_trade_parser import TRADE_X94_XML, TRADE_X96_XML

FIXTURES = Path(__file__).parent / "fixtures"


def _award_in_da_xml_20() -> str:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    xml, _ = GAEBWriter.to_bytes(doc, target_version=SourceVersion.DA_XML_20)
    return xml.decode("utf-8")


DOCUMENT_KINDS: dict[str, tuple[str, str]] = {
    "X31 quantities": (X31_XML, "sample.X31"),
    "X50 cost elements": (X50_XML, "sample.X50"),
    "X52 cost BoQ": (X52_XML, "sample.X52"),
    "X83 tender": ((FIXTURES / "gaebxml.x83").read_text(encoding="utf-8"), "sample.X83"),
    "X86 award with markups": (
        (FIXTURES / "synthetic_33.X86").read_text(encoding="utf-8"), "sample.X86",
    ),
    "X86 award in DA XML 2.0": (_award_in_da_xml_20(), "sample.X86"),
    "X93 trade": (TRADE_WITH_CTLG, "sample.X93"),
    "X94 trade": (TRADE_X94_XML, "sample.X94"),
    "X96 trade": (TRADE_X96_XML, "sample.X96"),
}
