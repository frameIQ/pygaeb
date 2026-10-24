"""Word, HTML and Markdown exports: same LV, same rules, three formats."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import lxml.html
import pytest

from pygaeb import BoQBuilder, GAEBParser
from pygaeb.convert.to_docx import to_docx
from pygaeb.convert.to_html import to_html
from pygaeb.convert.to_markdown import to_markdown
from pygaeb.models.boq import BoQCtgy
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ItemType, Provis
from pygaeb.models.item import Item, RichText

FIXTURES = Path(__file__).parent / "fixtures"


def _lv() -> GAEBDocument:
    builder = BoQBuilder(phase="X84", version="3.3")
    builder.project(no="P-1", name="Schulsanierung", currency="EUR")
    works = builder.add_lot("1", "Rohbau").add_category("01", "Erdarbeiten")
    works.add_item("01.0010", "Baustelleneinrichtung", qty=1, unit="psch", unit_price=4800,
                   item_type=ItemType.LUMP_SUM,
                   long_text=RichText(plain_text="Einrichten und Räumen.\nBauzaun vorhalten."))
    works.add_item("01.0020", "Bodenaustausch", qty=40, unit="m3", unit_price=38,
                   item_type=ItemType.EVENTUAL, provis=Provis.WITHOUT_TOTAL)
    doc = builder.build()
    category = doc.award.boq.lots[0].body.categories[0]
    category.subcategories.append(BoQCtgy(rno="01", label="Verbau", items=[
        Item(oz="01.01.0010", short_text="Trägerbohlwand", qty=Decimal("85"), unit="m2",
             unit_price=Decimal("96"), total_price=Decimal("8160")),
    ]))
    return doc


# ── Markdown ────────────────────────────────────────────────────────────

class TestMarkdown:
    def test_headings_positions_and_sums_in_document_order(self) -> None:
        text = to_markdown(_lv())

        order = [line for line in text.splitlines()
                 if line.startswith(("#", "**"))]
        assert order == [
            "# Schulsanierung",
            "## Los 1 Rohbau",
            "### 01 Erdarbeiten",
            "**01.0010 Baustelleneinrichtung**",
            "**01.0020 Bodenaustausch**",
            "#### 01.01 Verbau",
            "**01.01.0010 Trägerbohlwand**",
            "**Summe 01.01 Verbau: 8.160,00**",
            "**Summe 01 Erdarbeiten: 12.960,00**",
            "**Gesamtsumme: 12.960,00**",
        ]

    def test_positions_carry_long_text_marker_and_amounts(self) -> None:
        text = to_markdown(_lv())

        assert "Einrichten und Räumen.\n\nBauzaun vorhalten." in text
        assert "*Pauschalposition* · Menge 1,000 psch · EP 4.800,00 · GB 4.800,00" in text
        assert "*Bedarfsposition ohne GB* · Menge 40,000 m3 · EP 38,00 · Nur Einh.-Preis" in text

    def test_document_text_cannot_turn_into_markdown(self) -> None:
        doc = _lv()
        item = next(doc.iter_items())
        item.short_text = "Fuge *dauerelastisch* [Typ_A]"
        item.long_text = RichText(plain_text="# keine Überschrift\n> kein Zitat")

        text = to_markdown(doc)

        assert r"**01.0010 Fuge \*dauerelastisch\* \[Typ\_A\]**" in text
        assert r"\# keine Überschrift" in text
        assert r"\> kein Zitat" in text

    def test_markups_show_their_rate_and_amount(self) -> None:
        text = to_markdown(GAEBParser.parse(FIXTURES / "synthetic_33.X86"))

        assert "*Zuschlagsposition* · Zuschlag 10,00 % · GB 100,00" in text
        assert "**Summe 01 Erdarbeiten: 1.755,00**" in text

    def test_english_locale_and_writing_a_file(self, tmp_path: Path) -> None:
        out = tmp_path / "lv.md"
        text = to_markdown(_lv(), out, locale="en", long_text=False)

        assert out.read_text(encoding="utf-8") == text
        assert "*Lump-sum item* · Qty 1.000 psch · Unit price 4,800.00 · Total 4,800.00" in text
        assert "Einrichten" not in text


# ── HTML ────────────────────────────────────────────────────────────────

class TestHtml:
    def test_standalone_page_and_fragment(self) -> None:
        page = to_html(_lv())
        fragment = to_html(_lv(), standalone=False)

        assert page.startswith("<!DOCTYPE html>")
        assert "<title>Schulsanierung</title>" in page and "<style>" in page
        assert fragment.startswith('<section class="lv" lang="de">')
        assert "<html" not in fragment and "<style>" not in fragment

    def test_rows_keep_document_order_and_classes(self) -> None:
        tree = lxml.html.fromstring(to_html(_lv(), standalone=False))
        rows = [(row.get("class").split()[0], row.xpath("string(td[1])"))
                for row in tree.xpath("//tbody/tr")]

        assert rows == [
            ("lv-heading", "Los 1"), ("lv-heading", "01"),
            ("lv-position", "01.0010"), ("lv-position", "01.0020"),
            ("lv-heading", "01.01"), ("lv-position", "01.01.0010"),
            ("lv-total", ""), ("lv-total", ""), ("lv-total", ""),
        ]

    def test_position_cells_and_link_back_attributes(self) -> None:
        tree = lxml.html.fromstring(to_html(_lv(), standalone=False))
        row = tree.xpath('//tr[@data-oz="01.0020"]')[0]

        cells = [cell.text_content() for cell in row.xpath("td")]
        assert cells[0] == "01.0020"
        assert cells[2:] == ["40,000", "m3", "38,00", "Nur Einh.-Preis"]
        assert "unit-price-only" in row.xpath("td")[5].get("class")
        assert row.xpath('string(.//p[@class="marker"])') == "Bedarfsposition ohne GB"

    def test_document_text_is_escaped(self) -> None:
        doc = _lv()
        next(doc.iter_items()).short_text = '<script>alert("x")</script> & Co'

        html = to_html(doc)

        assert "<script>" not in html
        assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; Co" in html


# ── Word ────────────────────────────────────────────────────────────────

@pytest.fixture
def word() -> Any:
    """python-docx, or skip: only the Word tests need it."""
    return pytest.importorskip("docx")


class TestDocx:
    @pytest.fixture(autouse=True)
    def _word(self, word: Any) -> None:
        self.word = word

    def _table(self, tmp_path: Path, doc: GAEBDocument | None = None) -> Any:
        out = tmp_path / "lv.docx"
        to_docx(doc or _lv(), out)
        return self.word.Document(str(out))

    def test_title_meta_and_repeating_header_row(self, tmp_path: Path) -> None:
        document = self._table(tmp_path)
        table = document.tables[0]

        assert document.paragraphs[0].text == "Schulsanierung"
        assert document.core_properties.title == "Schulsanierung"
        assert [cell.text for cell in table.rows[0].cells] == [
            "OZ", "Leistungsbeschreibung", "Menge", "ME", "EP", "GB",
        ]
        assert table.rows[0]._tr.xpath("./w:trPr/w:tblHeader")

    def test_rows_follow_the_lv(self, tmp_path: Path) -> None:
        table = self._table(tmp_path).tables[0]

        firsts = [(row.cells[0].text, row.cells[1].text.split("\n")[0]) for row in table.rows[1:]]
        assert firsts == [
            ("Los 1", "Rohbau"), ("01", "Erdarbeiten"),
            ("01.0010", "Baustelleneinrichtung"), ("01.0020", "Bodenaustausch"),
            ("01.01", "Verbau"), ("01.01.0010", "Trägerbohlwand"),
            ("", "Summe 01.01 Verbau"), ("", "Summe 01 Erdarbeiten"), ("", "Gesamtsumme"),
        ]

    def test_position_text_and_amount_cells(self, tmp_path: Path) -> None:
        table = self._table(tmp_path).tables[0]
        lump, eventual = table.rows[3], table.rows[4]

        assert lump.cells[1].text == (
            "Baustelleneinrichtung\nEinrichten und Räumen.\nBauzaun vorhalten.\nPauschalposition"
        )
        assert [cell.text for cell in lump.cells[2:]] == ["1,000", "psch", "4.800,00", "4.800,00"]
        assert eventual.cells[5].text == "Nur Einh.-Preis"
        assert table.rows[-1].cells[5].text == "12.960,00"

    def test_markups_show_their_rate_and_amount(self, tmp_path: Path) -> None:
        table = self._table(tmp_path, GAEBParser.parse(FIXTURES / "synthetic_33.X86")).tables[0]
        markup = next(row for row in table.rows if row.cells[0].text == "01.0040")

        assert [markup.cells[4].text, markup.cells[5].text] == ["10,00 %", "100,00"]


# ── All formats agree ───────────────────────────────────────────────────

def test_every_format_prints_the_same_sums(tmp_path: Path, word: Any) -> None:
    doc = GAEBParser.parse(FIXTURES / "synthetic_33.X86")
    sums = ["1.755,00", "1.755,00"]  # the category subtotal, then the grand total

    markdown = to_markdown(doc)
    html = lxml.html.fromstring(to_html(doc, standalone=False))
    to_docx(doc, tmp_path / "lv.docx")
    table = word.Document(str(tmp_path / "lv.docx")).tables[0]

    in_markdown = [line.rsplit(": ", 1)[1].rstrip("*") for line in markdown.splitlines()
                   if line.startswith(("**Summe", "**Gesamtsumme"))]
    in_html = [row.xpath("string(td[last()])")
               for row in html.xpath('//tr[contains(@class, "lv-total")]')]
    in_word = [row.cells[5].text for row in table.rows
               if row.cells[0].text == "" and row.cells[5].text]
    assert in_markdown == in_html == in_word == sums
