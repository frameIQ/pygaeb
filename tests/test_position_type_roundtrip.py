"""Field-level round-trip tests for position type, qty splits, and long text.

These guard the three write-path defects that made a €50,000 bid export as €121,000:

1. ``item_type`` was never serialized → every Bedarfs-/Alternativ-/Zuschlagsposition
   became a Normalposition on write, and its price silently joined the total.
2. ``qty_splits`` were never serialized.
3. Long text re-wrapped itself on every round trip (compounding nesting) and plaintext
   long texts were dropped entirely.

The pre-existing ``test_writer.py`` round-trip asserted only project_no, currency, and
item *count* — it passed while all three defects fired. These assert at the field level.
"""

from __future__ import annotations

from decimal import Decimal

from pygaeb import ExchangePhase, GAEBParser, GAEBWriter
from pygaeb.models.enums import ItemType
from pygaeb.models.item import QtySplit


def _roundtrip(xml: bytes, times: int = 1):
    """Parse → write X86 → re-parse, ``times`` times. Returns (doc, warnings).

    X86 (contract) carries prices *and* position-type markers; the X84 bid
    schema has no markers at all, so it cannot round-trip them (see
    ``TestX84HasNoMarkers``).
    """
    doc = GAEBParser.parse_bytes(xml)
    warnings: list[str] = []
    for _ in range(times):
        out, warns = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X86)
        warnings = warns
        doc = GAEBParser.parse_bytes(out)
    return doc, warnings


# A window tender with a normal position, a Bedarfsposition (real <Provis>, excluded
# from the sum), and a Pauschalposition (real <LumpSumItem>, included).
TENDER_WITH_TYPES = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version><Date>2026-07-21</Date></GAEBInfo>
  <Award><DP>83</DP><PrjInfo><NameProject>Musterprojekt</NameProject><Cur>EUR</Cur></PrjInfo>
    <BoQ><BoQInfo><Name>LV</Name><LblBoQ>Fenster</LblBoQ></BoQInfo>
      <BoQBody><BoQCtgy RNoPart="01"><LblTx>Fenster</LblTx><BoQBody><Itemlist>
        <Item RNoPart="0010"><ShortText>Fenster 2-fach</ShortText>
          <Qty>100.000</Qty><QU>St</QU><UP>500.00</UP><IT>50000.00</IT></Item>
        <Item RNoPart="0020"><Provis/><ShortText>Bedarf: Sonnenschutz</ShortText>
          <Qty>20.000</Qty><QU>St</QU><UP>300.00</UP><IT>6000.00</IT></Item>
        <Item RNoPart="0030"><LumpSumItem/><ShortText>Pauschal: BE</ShortText>
          <Qty>1.000</Qty><QU>psch</QU><UP>2000.00</UP><IT>2000.00</IT></Item>
      </Itemlist></BoQBody></BoQCtgy></BoQBody></BoQ></Award></GAEB>"""


class TestPositionTypeSerialization:
    def test_real_markers_parsed(self):
        """Real GAEB <Provis>/<LumpSumItem> map to the right ItemType on import."""
        doc = GAEBParser.parse_bytes(TENDER_WITH_TYPES)
        types = {i.oz.split(".")[-1]: i.item_type for i in doc.iter_items()}
        assert types["0010"] == ItemType.NORMAL
        assert types["0020"] == ItemType.EVENTUAL   # <Provis> — was mis-read as NORMAL
        assert types["0030"] == ItemType.LUMP_SUM

    def test_types_survive_roundtrip(self):
        doc, _ = _roundtrip(TENDER_WITH_TYPES)
        types = {i.oz.split(".")[-1]: i.item_type for i in doc.iter_items()}
        assert types["0020"] == ItemType.EVENTUAL
        assert types["0030"] == ItemType.LUMP_SUM

    def test_real_elements_present_in_output(self):
        doc = GAEBParser.parse_bytes(TENDER_WITH_TYPES)
        out, _ = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X86)
        # Both markers carry a schema-typed value: tgProvis / tgYesNo.
        assert b"<Provis>WithoutTotal</Provis>" in out
        assert b"<LumpSumItem>Yes</LumpSumItem>" in out


class TestX84HasNoMarkers:
    def test_x84_drops_markers_with_a_note(self):
        doc = GAEBParser.parse_bytes(TENDER_WITH_TYPES)
        out, warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X84)
        assert b"<Provis" not in out
        assert b"<LumpSumItem" not in out
        assert any("position marker not written" in w and "X84" in w for w in warnings)

    def test_total_excludes_bedarfsposition_across_roundtrips(self):
        """The regression guard: Bedarfsposition price must never enter the sum.

        Before the fix this exported all three as Normal → 50000+6000+2000 = 58000.
        Correct: 50000 (normal) + 2000 (lump sum) + 0 (Provis excluded) = 52000, stable.
        """
        original = GAEBParser.parse_bytes(TENDER_WITH_TYPES)
        assert original.computed_grand_total == Decimal("52000.00")
        doc, _ = _roundtrip(TENDER_WITH_TYPES, times=3)
        assert doc.computed_grand_total == Decimal("52000.00")


class TestNonInteropWarning:
    """Types without a confirmed real serialization round-trip, but the writer warns."""

    ALT = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version><Date>2026-07-21</Date></GAEBInfo>
  <Award><DP>83</DP><PrjInfo><NameProject>P</NameProject><Cur>EUR</Cur></PrjInfo>
    <BoQ><BoQInfo><Name>LV</Name><LblBoQ>X</LblBoQ></BoQInfo>
      <BoQBody><BoQCtgy RNoPart="01"><LblTx>X</LblTx><BoQBody><Itemlist>
        <Item RNoPart="0010"><AlternativeItem/><ShortText>Alt: 3-fach</ShortText>
          <Qty>100.000</Qty><QU>St</QU><UP>650.00</UP><IT>65000.00</IT></Item>
      </Itemlist></BoQBody></BoQCtgy></BoQBody></BoQ></Award></GAEB>"""

    def test_alternative_roundtrips_and_stays_excluded(self):
        doc, _ = _roundtrip(self.ALT)
        item = next(doc.iter_items())
        assert item.item_type == ItemType.ALTERNATIVE
        assert not item.item_type.affects_total
        assert doc.computed_grand_total == Decimal("0.00")

    def test_alternative_emits_non_interop_warning(self):
        doc = GAEBParser.parse_bytes(self.ALT)
        _, warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X86)
        assert any("not read by other AVA software" in w for w in warnings)


class TestQtySplitRoundtrip:
    def test_qty_splits_survive(self):
        """tgQtySplit is (QtyPcnt | Qty) + CtlgAssign: the quantity round-trips,
        the pyGAEB-only label/unit do not (the writer says so)."""
        doc = GAEBParser.parse_bytes(TENDER_WITH_TYPES)
        item = next(i for i in doc.iter_items() if i.oz.endswith("0010"))
        item.qty_splits = [
            QtySplit(label="EG", qty=Decimal("60"), unit="St"),
            QtySplit(label="OG", qty=Decimal("40"), unit="St"),
        ]
        out, warnings = GAEBWriter.to_bytes(doc, phase=ExchangePhase.X86)
        assert b"<QtySplit" in out
        assert any("QtySplit label/unit" in w for w in warnings)
        reparsed = GAEBParser.parse_bytes(out)
        splits = next(i for i in reparsed.iter_items() if i.oz.endswith("0010")).qty_splits
        assert [s.qty for s in splits] == [Decimal("60"), Decimal("40")]


class TestLongTextRoundtrip:
    RICH = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
  <GAEBInfo><Version>3.3</Version><Date>2026-07-21</Date></GAEBInfo>
  <Award><DP>83</DP><PrjInfo><NameProject>P</NameProject><Cur>EUR</Cur></PrjInfo>
    <BoQ><BoQInfo><Name>LV</Name><LblBoQ>X</LblBoQ></BoQInfo>
      <BoQBody><BoQCtgy RNoPart="01"><LblTx>X</LblTx><BoQBody><Itemlist>
        <Item RNoPart="0010"><ShortText>Fenster</ShortText>
          <Qty>1.000</Qty><QU>St</QU><UP>500.00</UP><IT>500.00</IT>
          <LongText><span>Kunststofffenster,</span><span>Uw 1,3 W/m2K</span></LongText></Item>
      </Itemlist></BoQBody></BoQCtgy></BoQBody></BoQ></Award></GAEB>"""

    def test_long_text_does_not_compound(self):
        doc1, _ = _roundtrip(self.RICH, times=1)
        raw1 = next(doc1.iter_items()).long_text.raw_html
        doc3, _ = _roundtrip(self.RICH, times=3)
        raw3 = next(doc3.iter_items()).long_text.raw_html
        # length stable across round trips — no nesting layer added each time
        assert raw1 == raw3
        assert "<longtext" not in raw3.lower()

    def test_plain_text_long_text_survives(self):
        plain = self.RICH.replace(
            b"<span>Kunststofffenster,</span><span>Uw 1,3 W/m2K</span>",
            b"Kunststofffenster, Uw 1,3",
        )
        doc, _ = _roundtrip(plain, times=2)
        lt = next(doc.iter_items()).long_text
        assert lt is not None
        assert "Kunststofffenster" in lt.plain_text
