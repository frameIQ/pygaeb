"""The long-text reader reads lxml's HTML tree the way it read BeautifulSoup's.

BeautifulSoup's "lxml" mode ran libxml2's HTML parser and copied the result into
Python objects; the reader now walks the parser's own tree. Each case below is a
place where the two could part ways, with the result BeautifulSoup gave.
"""

from __future__ import annotations

from pygaeb.parser.xml_v3.richtext_parser import parse_richtext


def test_the_text_after_an_image_stays() -> None:
    # Removing an lxml element drops the text after it; images are skipped instead.
    rich = parse_richtext('<p>Aushub<image Type="image/png">QUJD</image> abfahren</p>')
    assert rich is not None
    assert rich.paragraphs == ["Aushub abfahren"]
    assert rich.images == ["data:image/png;base64,QUJD"]


def test_an_image_in_a_table_cell_or_a_field_stays_out_of_its_text() -> None:
    table = parse_richtext("<table><tr><td>Typ<image>QUJD</image> A</td><td>2</td></tr></table>")
    assert table is not None
    assert table.tables == [[["Typ A", "2"]]]
    assert table.plain_text == "Typ A | 2"

    field = parse_richtext(
        '<p>Fabrikat <TextComplement Kind="Bidder"><ComplCaption>Typ<image>QUJD</image> A'
        "</ComplCaption><ComplBody>X</ComplBody></TextComplement></p>"
    )
    assert field is not None
    assert field.paragraphs == ["Fabrikat Typ A X"]


def test_script_and_style_are_not_image_data() -> None:
    rich = parse_richtext("<image><script>s</script><style>t</style>QUJD</image>")
    assert rich is not None
    assert rich.images == ["data:image/jpeg;base64,QUJD"]


def test_an_image_inside_ruby_text_has_no_data() -> None:
    rich = parse_richtext("<p>Text<rt>Lesung<image>QUJD</image></rt> weiter</p>")
    assert rich is not None
    assert rich.paragraphs == ["TextLesung weiter"]
    assert rich.images == []


def test_a_comment_or_a_byte_order_mark_alone_is_no_text() -> None:
    assert parse_richtext("<!-- nur ein Kommentar -->") is None
    # Closing a parser that was never fed raises; it is fed at least once.
    assert parse_richtext("\N{BYTE ORDER MARK}") is None


def test_text_after_a_stray_closing_html_tag_stays() -> None:
    # libxml2 puts it in a second top-level element.
    rich = parse_richtext("<p>Erster Absatz</p></html><p>nach dem Ende</p>")
    assert rich is not None
    assert rich.paragraphs == ["Erster Absatz", "nach dem Ende"]


def test_a_leading_byte_order_mark_is_dropped() -> None:
    rich = parse_richtext("\N{BYTE ORDER MARK}<p>Beton</p>")
    assert rich is not None
    assert rich.paragraphs == ["Beton"]


def test_deep_nesting_and_huge_images_are_read_to_the_end() -> None:
    # libxml2's tree builder stops at 256 levels and at 10 MB of text without huge_tree.
    deep = parse_richtext("<span>" * 300 + "tief" + "</span>" * 300)
    assert deep is not None
    assert deep.paragraphs == ["tief"]

    data = "A" * 10_500_000
    big = parse_richtext(f'<p>vorher</p><image Type="image/png">{data}</image><p>nachher</p>')
    assert big is not None
    assert big.paragraphs == ["vorher", "nachher"]
    assert big.images == [f"data:image/png;base64,{data}"]
