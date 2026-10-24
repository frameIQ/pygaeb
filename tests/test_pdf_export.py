"""PDF export: LV layout, number formats, and the text callback."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pygaeb import BoQBuilder, GAEBParser
from pygaeb.convert.to_pdf import PdfStyle, PdfTextRole, PdfTextRun, to_pdf
from pygaeb.models.boq import BoQCtgy
from pygaeb.models.document import GAEBDocument, GAEBInfo
from pygaeb.models.enums import ExchangePhase, ItemType, Provis, SourceVersion
from pygaeb.models.item import Item, RichText
from pygaeb.models.order import OrderInfo, OrderItem, TradeOrder

pytest.importorskip("reportlab")
pypdf = pytest.importorskip("pypdf")

LONG_TEXT = "Schalung und Bewehrung einkalkulieren. " * 6


def _lv(*, items: int = 1, priced: bool = True, long_text: str = "") -> GAEBDocument:
    builder = BoQBuilder(phase="X84" if priced else "X83", version="3.3")
    builder.project(no="P-1", name="Schulsanierung", currency="EUR")
    concrete = builder.add_lot("1", "Rohbau").add_category("01", "Betonarbeiten")
    for n in range(1, items + 1):
        concrete.add_item(
            f"01.{n * 10:04d}",
            f"Streifenfundament {n}",
            qty=Decimal("1170.5"),
            unit="m3",
            unit_price=Decimal("45.5") if priced else None,
            long_text=RichText(plain_text=long_text) if long_text else None,
        )
    return builder.build()


def _render(
    doc: GAEBDocument, tmp_path: Path, style: PdfStyle | None = None
) -> tuple[Path, list[PdfTextRun]]:
    runs: list[PdfTextRun] = []
    out = tmp_path / "lv.pdf"
    to_pdf(doc, out, style=style, on_text=runs.append)
    return out, runs


def _texts(runs: list[PdfTextRun], role: PdfTextRole) -> list[str]:
    return [run.text for run in runs if run.role is role]


def _de(value: Decimal) -> str:
    return f"{value:,.2f}".translate(str.maketrans({",": ".", ".": ","}))


def _drawn(path: Path) -> list[tuple[int, str, float, float]]:
    """Every string in the file with its page and origin, as an independent reader sees it."""
    found: list[tuple[int, str, float, float]] = []
    for number, page in enumerate(pypdf.PdfReader(path).pages, start=1):

        def visit(text: str, cm: Any, tm: Any, font: Any, size: Any, number: int = number) -> None:
            if text.strip():
                found.append((number, text.strip(), float(tm[4]), float(tm[5])))

        page.extract_text(visitor_text=visit)
    return found


def test_everything_drawn_is_reported_and_everything_reported_is_drawn(tmp_path: Path) -> None:
    _, runs = _render(_lv(items=30, long_text=LONG_TEXT), tmp_path)
    drawn = _drawn(tmp_path / "lv.pdf")

    assert max(run.page for run in runs) >= 3
    assert len(drawn) == len(runs)
    for run in runs:
        assert any(
            page == run.page and text == run.text
            and abs(x - run.x) < 0.01 and abs(y - run.y) < 0.01
            for page, text, x, y in drawn
        ), f"{run.text!r} is not on page {run.page} at ({run.x:.2f}, {run.y:.2f})"


def test_numbers_and_labels_are_german_by_default(tmp_path: Path) -> None:
    _, runs = _render(_lv(), tmp_path)

    assert _texts(runs, PdfTextRole.QTY) == ["1.170,500"]
    assert _texts(runs, PdfTextRole.UNIT_PRICE) == ["45,50"]
    assert _texts(runs, PdfTextRole.TOTAL_PRICE) == ["53.257,75"]
    assert _texts(runs, PdfTextRole.COLUMN_HEADER) == [
        "OZ", "Leistungsbeschreibung", "Menge", "ME", "EP", "GB",
    ]


def test_english_locale_switches_numbers_and_labels(tmp_path: Path) -> None:
    _, runs = _render(_lv(), tmp_path, PdfStyle(locale="en"))

    assert _texts(runs, PdfTextRole.QTY) == ["1,170.500"]
    assert _texts(runs, PdfTextRole.TOTAL_PRICE) == ["53,257.75"]
    assert _texts(runs, PdfTextRole.GRAND_TOTAL_LABEL) == ["Grand total"]


def test_numbers_keep_the_precision_the_document_carries(tmp_path: Path) -> None:
    doc = _lv()
    item = next(doc.award.boq.iter_items())
    item.unit_price = Decimal("12.345")

    _, runs = _render(doc, tmp_path)

    assert _texts(runs, PdfTextRole.UNIT_PRICE) == ["12,345"]


def test_items_print_full_oz_and_untruncated_texts(tmp_path: Path) -> None:
    doc = _lv(long_text="Erste Zeile des Langtexts.\nZweite Zeile.")
    item = next(doc.award.boq.iter_items())
    item.short_text = "Streifenfundament aus Stahlbeton C25/30, bewehrt, " * 4

    _, runs = _render(doc, tmp_path)

    assert _texts(runs, PdfTextRole.ITEM_NUMBER) == ["01.0010"]
    assert " ".join(_texts(runs, PdfTextRole.SHORT_TEXT)) == " ".join(item.short_text.split())
    assert _texts(runs, PdfTextRole.LONG_TEXT) == ["Erste Zeile des Langtexts.", "Zweite Zeile."]


def test_categories_print_in_document_order_with_subtotals(tmp_path: Path) -> None:
    doc = _lv()
    concrete = doc.award.boq.lots[0].body.categories[0]
    concrete.subcategories.append(BoQCtgy(rno="02", label="Fundamente", items=[
        Item(oz="01.02.0010", short_text="Einzelfundament", qty=Decimal("2"), unit="Stk",
             unit_price=Decimal("100"), total_price=Decimal("200")),
    ]))

    _, runs = _render(doc, tmp_path)

    shown = {PdfTextRole.CATEGORY_NUMBER, PdfTextRole.ITEM_NUMBER, PdfTextRole.SUBTOTAL}
    assert [(run.role, run.text) for run in runs if run.role in shown] == [
        (PdfTextRole.CATEGORY_NUMBER, "01"),
        (PdfTextRole.ITEM_NUMBER, "01.0010"),
        (PdfTextRole.CATEGORY_NUMBER, "01.02"),
        (PdfTextRole.ITEM_NUMBER, "01.02.0010"),
        (PdfTextRole.SUBTOTAL, "200,00"),
        (PdfTextRole.SUBTOTAL, "53.457,75"),
    ]
    assert _texts(runs, PdfTextRole.GRAND_TOTAL) == [_de(doc.grand_total)]


def test_item_types_print_markers_and_unsummed_items_show_unit_price_only(
    tmp_path: Path,
) -> None:
    builder = BoQBuilder(phase="X84", version="3.3")
    builder.project(no="P-1", name="Schulsanierung", currency="EUR")
    works = builder.add_lot("1", "Rohbau").add_category("01", "Erdarbeiten")
    works.add_item("01.0010", "Wasserhaltung", qty=1, unit="psch", unit_price=500,
                   item_type=ItemType.LUMP_SUM)
    works.add_item("01.0020", "Zusätzlicher Bodenaustausch", qty=10, unit="m3", unit_price=90,
                   item_type=ItemType.EVENTUAL, provis=Provis.WITHOUT_TOTAL)

    _, runs = _render(builder.build(), tmp_path)

    assert _texts(runs, PdfTextRole.ITEM_TYPE) == ["Pauschalposition", "Bedarfsposition ohne GB"]
    assert _texts(runs, PdfTextRole.TOTAL_PRICE) == ["500,00"]
    assert _texts(runs, PdfTextRole.UNIT_PRICE_ONLY) == ["Nur Einh.-Preis"]
    assert _texts(runs, PdfTextRole.SUBTOTAL) == ["500,00"]


def test_markup_items_print_their_rate_and_their_own_amount(tmp_path: Path) -> None:
    doc = GAEBParser.parse(Path(__file__).parent / "fixtures" / "synthetic_33.X86")

    _, runs = _render(doc, tmp_path)

    markup = [run for run in runs if run.item is not None and run.item.oz == "0040"]
    assert [(run.role, run.text) for run in markup if run.role is not PdfTextRole.SHORT_TEXT] == [
        (PdfTextRole.ITEM_NUMBER, "01.0040"),
        (PdfTextRole.ITEM_TYPE, "Zuschlagsposition"),
        (PdfTextRole.MARKUP_RATE, "10,00 %"),
        (PdfTextRole.TOTAL_PRICE, "100,00"),
    ]
    assert _texts(runs, PdfTextRole.SUBTOTAL) == ["1.755,00"]


def test_carry_forward_lines_repeat_the_running_total_across_each_page_break(
    tmp_path: Path,
) -> None:
    _, runs = _render(_lv(items=30, long_text=LONG_TEXT), tmp_path)
    pages = max(run.page for run in runs)
    carried = [run for run in runs if run.role is PdfTextRole.CARRY_FORWARD]

    assert len(carried) == 2 * (pages - 1)
    for page in range(1, pages):
        foot = min((run for run in carried if run.page == page), key=lambda run: run.y)
        head = max((run for run in carried if run.page == page + 1), key=lambda run: run.y)
        summed = sum(
            Decimal(run.text.replace(".", "").replace(",", "."))
            for run in runs
            if run.role is PdfTextRole.TOTAL_PRICE and run.page <= page
        )
        assert foot.text == head.text == _de(Decimal(summed))


def test_unpriced_documents_print_no_sums(tmp_path: Path) -> None:
    _, runs = _render(_lv(items=30, priced=False, long_text=LONG_TEXT), tmp_path)

    assert max(run.page for run in runs) >= 2
    assert not {run.role for run in runs} & {
        PdfTextRole.TOTAL_PRICE, PdfTextRole.SUBTOTAL,
        PdfTextRole.CARRY_FORWARD, PdfTextRole.GRAND_TOTAL,
    }


def test_style_can_leave_out_long_texts_and_carry_forward_lines(tmp_path: Path) -> None:
    style = PdfStyle(long_text=False, carry_forward=False)

    _, runs = _render(_lv(items=80, long_text=LONG_TEXT), tmp_path, style)

    assert max(run.page for run in runs) >= 2
    assert not {run.role for run in runs} & {PdfTextRole.LONG_TEXT, PdfTextRole.CARRY_FORWARD}


def test_runs_name_the_item_category_and_lot_they_came_from(tmp_path: Path) -> None:
    doc = _lv()
    item = next(doc.award.boq.iter_items())

    _, runs = _render(doc, tmp_path)

    qty = next(run for run in runs if run.role is PdfTextRole.QTY)
    assert qty.item is item
    assert qty.category is doc.award.boq.lots[0].body.categories[0]
    assert qty.lot is doc.award.boq.lots[0]


def test_other_document_kinds_print_a_flat_item_list(tmp_path: Path) -> None:
    order = TradeOrder(
        dp="X96",
        order_info=OrderInfo(order_no="ORD-1", currency="EUR"),
        items=[OrderItem(item_id="1", art_no="S-4", short_text="Schrauben",
                         qty=Decimal("250"), unit="Stk", net_price=Decimal("5"),
                         price_basis=Decimal("100"))],
    )
    doc = GAEBDocument(source_version=SourceVersion.DA_XML_33,
                       exchange_phase=ExchangePhase.X96, gaeb_info=GAEBInfo(), order=order)

    _, runs = _render(doc, tmp_path)

    assert _texts(runs, PdfTextRole.ITEM_NUMBER) == ["S-4"]
    assert _texts(runs, PdfTextRole.UNIT_PRICE) == ["5,00"]
    assert _texts(runs, PdfTextRole.TOTAL_PRICE) == ["12,50"]  # 5.00 per 100 pieces
    assert _texts(runs, PdfTextRole.GRAND_TOTAL) == ["12,50"]


def test_unknown_locale_is_rejected() -> None:
    with pytest.raises(ValueError, match="locale"):
        PdfStyle(locale="fr")  # type: ignore[arg-type]
