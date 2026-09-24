"""``<Ctlg>`` — what a position's catalogue assignment actually refers to.

A ``<CtlgAssign>`` carries an opaque ``CtlgID`` and a code, so ``331`` means
nothing on its own. The declaration is what says that id is *cost group
DIN 276-06* and the code is a DIN 276 group — or that another id is the
Leistungsbereichkatalog and ``012`` is Mauerarbeiten.

The parser read the assignments and never the declarations, so every consumer had
an identifier with no way to resolve it, and the writer dropped them: a document
that went through pyGAEB came out with its codes permanently unreadable.

``<Ctlg>`` sits at the end of ``<BoQInfo>``, after ``<Totals>``, in every phase
schema that carries it.
"""

from __future__ import annotations

from pygaeb import GAEBParser, GAEBWriter

_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
  <GAEBInfo><Version>3.3</Version><Date>2026-09-24</Date>
    <ProgSystem>t</ProgSystem></GAEBInfo>
  <PrjInfo><NamePrj>T</NamePrj><Cur>EUR</Cur></PrjInfo>
  <Award><DP>83</DP><Cur>EUR</Cur><BoQ>
    <BoQInfo><Name>LV</Name>
      <BoQBkdn><Item Length="4"/></BoQBkdn>{catalogues}</BoQInfo>
    <BoQBody><Itemlist>
      <Item RNoPart="0010">
        <Qty>1.000</Qty><QU>m2</QU>
        <CtlgAssign><CtlgID>CANKDEDI</CtlgID><CtlgCode>331</CtlgCode></CtlgAssign>
        <Description><CompleteText><DetailTxt><Text><p><span>T</span></p></Text>
        </DetailTxt></CompleteText></Description>
      </Item>
    </Itemlist></BoQBody>
  </BoQ></Award></GAEB>"""

_CTLG = (
    "<Ctlg><CtlgID>CANKDEDI</CtlgID><CtlgType>cost group DIN 276-06</CtlgType>"
    "<CtlgName>DIN276_06</CtlgName></Ctlg>"
)


def _boq_info(catalogues: str = _CTLG):
    return GAEBParser().parse_string(_DOC.format(catalogues=catalogues)).award.boq.boq_info


def test_a_declaration_is_read() -> None:
    catalogues = _boq_info().catalogues

    assert len(catalogues) == 1
    assert catalogues[0].ctlg_id == "CANKDEDI"
    assert catalogues[0].ctlg_type == "cost group DIN 276-06"
    assert catalogues[0].ctlg_name == "DIN276_06"


def test_a_document_that_declares_nothing() -> None:
    assert _boq_info(catalogues="").catalogues == []


def test_several_declarations_keep_their_order() -> None:
    """A real file declares four at once — trades, cost groups, places, cost units."""
    second = (
        "<Ctlg><CtlgID>CBAOAGGM</CtlgID><CtlgType>work category</CtlgType>"
        "<CtlgName>Leistungsbereichkatalog</CtlgName></Ctlg>"
    )

    ids = [c.ctlg_id for c in _boq_info(_CTLG + second).catalogues]

    assert ids == ["CANKDEDI", "CBAOAGGM"]


def test_a_declaration_survives_a_write() -> None:
    """Dropped, the assignments on the positions become unreadable for good."""
    doc = GAEBParser().parse_string(_DOC.format(catalogues=_CTLG))

    xml, _ = GAEBWriter.to_bytes(doc)

    assert b"<CtlgName>DIN276_06</CtlgName>" in xml
    back = GAEBParser().parse_string(xml.decode("utf-8"))
    assert back.award.boq.boq_info.catalogues[0].ctlg_name == "DIN276_06"


def test_it_is_written_after_the_assignments() -> None:
    """The schema puts <Ctlg> at the end of BoQInfo; elsewhere the XSD refuses it."""
    doc = GAEBParser().parse_string(_DOC.format(catalogues=_CTLG))

    text = GAEBWriter.to_bytes(doc)[0].decode("utf-8")

    assert text.index("<BoQBkdn") < text.index("<Ctlg>")
    assert text.index("<Ctlg>") < text.index("</BoQInfo>")


def test_a_declaration_without_a_name_is_still_kept() -> None:
    # The id alone is what an assignment matches on; the name is for the reader.
    bare = "<Ctlg><CtlgID>CANKDEDI</CtlgID></Ctlg>"

    catalogues = _boq_info(bare).catalogues

    assert len(catalogues) == 1
    assert catalogues[0].ctlg_id == "CANKDEDI"
    assert catalogues[0].ctlg_name == ""
