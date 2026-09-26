"""Reading a long text as the issuer wrote it: line breaks and fields.

Standard texts break every line with ``<br/>`` and leave gaps — ``TextComplement``
fields — that the issuer fills (``Material 'Beton C25/30'``) and the bidder
answers (``Material '....'``). Both were lost: stripping every string glued words
together at each line break, and a block-by-block reader never looked at the
fields, which sit between ``<Text>`` blocks.

The texts here are written for these tests; they copy the shapes of real
standard-text files, not their wording.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pygaeb import ComplementKind, TextComplement
from pygaeb.parser.xml_v3.richtext_parser import parse_richtext

OWNER = (
    '<TextComplement Kind="Owner" MarkLbl="31"><ComplCaption>Material </ComplCaption>'
    "<ComplBody><span>'Beton C25/30'</span></ComplBody><ComplTail/></TextComplement>"
)
BIDDER = (
    '<TextComplement Kind="Bidder" MarkLbl="32" Empty="Yes"><ComplCaption>Material </ComplCaption>'
    "<ComplBody><span>'</span><br/><span>..........'</span></ComplBody>"
    "<ComplTail>,</ComplTail></TextComplement>"
)
PAIRED = (
    "<Text><p><span>Rinne liefern,</span></p></Text>"
    + OWNER
    + "<Text><p><span>oder gleichwertiger Art,</span></p></Text>"
    + BIDDER
    + "<Text><p><span>einbauen.</span></p></Text>"
)


def paragraphs(html: str) -> list[str]:
    rich = parse_richtext(html)
    assert rich is not None
    return rich.paragraphs


# --- line breaks ----------------------------------------------------------------


def test_a_line_break_is_a_line_break() -> None:
    """Fails if ``<br/>`` becomes nothing — the glued ``vorhandenenDrahtankern``."""
    assert paragraphs(
        "<Text><p><span>an vorhandenen </span><br/><span>Drahtankern</span></p></Text>"
    ) == ["an vorhandenen\nDrahtankern"]


def test_a_word_split_across_style_runs_stays_one_word() -> None:
    """Fails if adjacent spans are joined with a space."""
    assert paragraphs("<Text><p><span>Ver</span><span>dichten</span></p></Text>") == [
        "Verdichten"
    ]


def test_indentation_in_the_markup_is_not_a_line_break() -> None:
    assert paragraphs("<Text><p>\n  <span>Beton\n  liefern</span>\n</p></Text>") == [
        "Beton liefern"
    ]


def test_text_outside_a_paragraph_is_kept() -> None:
    """Fails if only innermost ``<p>`` blocks are read."""
    assert paragraphs("<Text><p><span>Erster Absatz.</span></p><span>Lose Zeile</span></Text>") == [
        "Erster Absatz.",
        "Lose Zeile",
    ]


# --- fields -----------------------------------------------------------------------


def test_fields_read_inline_where_they_stand() -> None:
    """Fails if fields are skipped, or if each opens a paragraph of its own."""
    assert paragraphs(PAIRED) == [
        "Rinne liefern, Material 'Beton C25/30' oder gleichwertiger Art, Material '…', einbauen."
    ]


def test_quote_marks_are_not_doubled() -> None:
    """The quotes are part of the body; fails if the renderer adds its own."""
    assert "''" not in paragraphs(PAIRED)[0]


def test_a_field_that_opens_a_sentence_keeps_its_paragraph() -> None:
    html = (
        "<Text><p><span>Kosten sind einzurechnen.</span></p></Text>"
        '<TextComplement Kind="Owner" MarkLbl="21"><ComplCaption>Dicke = </ComplCaption>'
        "<ComplBody><span>'24 cm'</span></ComplBody></TextComplement>"
        "<Text><p><span>Verformungsmodul min. 150 MN/m2</span></p></Text>"
    )
    assert paragraphs(html) == [
        "Kosten sind einzurechnen.",
        "Dicke = '24 cm'",
        "Verformungsmodul min. 150 MN/m2",
    ]


def test_a_field_inside_a_paragraph_reads_inline() -> None:
    html = (
        "<Text><p><span>Farbe </span>"
        '<TextComplement Kind="Bidder" MarkLbl="5"><ComplBody><span>\'...\'</span></ComplBody>'
        "</TextComplement><span>, matt</span></p></Text>"
    )
    assert paragraphs(html) == ["Farbe '…', matt"]


def test_the_fields_come_back_as_structure() -> None:
    rich = parse_richtext(PAIRED)
    assert rich is not None

    owner, bidder = rich.complements
    assert (owner.kind, owner.mark, owner.caption, owner.value) == (
        ComplementKind.OWNER, "31", "Material", "Beton C25/30",
    )
    assert (bidder.kind, bidder.mark, bidder.tail, bidder.empty) == (
        ComplementKind.BIDDER, "32", ",", True,
    )


def test_a_dotted_body_is_blank_without_being_marked_so() -> None:
    """Several programs mark a blank only with dots. Fails if only ``Empty`` counts."""
    rich = parse_richtext(
        '<TextComplement Kind="Bidder" MarkLbl="7"><ComplBody><span>...........</span>'
        "</ComplBody></TextComplement>"
    )
    assert rich is not None
    assert rich.complements[0].empty
    assert rich.complements[0].value == ""


def test_a_numeric_field_keeps_its_number() -> None:
    rich = parse_richtext(
        '<TextComplement Kind="Owner" MarkLbl="3"><ComplCaption>Falzbreite </ComplCaption>'
        "<ComplBodyDec Value=\"799\"/><ComplBody><span>'799'</span></ComplBody></TextComplement>"
    )
    assert rich is not None
    field = rich.complements[0]
    assert (field.number, field.number_kind, field.value) == (Decimal("799"), "dec", "799")


def test_a_field_in_a_table_cell_is_found_and_read_inline() -> None:
    rich = parse_richtext(
        "<Text><table><tr><td><span>Farbe </span>"
        '<TextComplement Kind="Bidder" MarkLbl="9"><ComplBody/></TextComplement></td>'
        "<td><span>a</span><br/><span>b</span></td></tr></table></Text>"
    )
    assert rich is not None
    assert rich.tables == [[["Farbe '…'", "a b"]]]
    assert [c.mark for c in rich.complements] == ["9"]
    assert "Farbe '…' | a b" in rich.plain_text


def test_plain_text_reads_like_the_paragraphs() -> None:
    rich = parse_richtext(PAIRED)
    assert rich is not None
    assert rich.plain_text == rich.paragraphs[0]


# --- answering a field --------------------------------------------------------------


def test_the_bidder_answers_its_own_field() -> None:
    rich = parse_richtext(PAIRED)
    assert rich is not None

    assert rich.fill_bidder("32", "Beton C30/37") == 1
    assert rich.complements[1].value == "Beton C30/37"
    assert not rich.complements[1].empty


def test_the_issuer_field_is_not_the_bidders_to_fill() -> None:
    rich = parse_richtext(PAIRED)
    assert rich is not None

    assert rich.fill_bidder("31", "anders") == 0
    with pytest.raises(ValueError, match="issuer"):
        rich.complements[0].fill("anders")


def test_an_answer_to_a_numeric_field_sets_its_number_only_when_it_is_one() -> None:
    field = TextComplement(kind=ComplementKind.BIDDER, mark="1", number_kind="dec")
    field.fill("0,5")
    assert field.number == Decimal("0.5")

    field.fill("etwa fünf")
    assert field.number is None
    assert field.value == "etwa fünf"


def test_clearing_an_answer_leaves_the_field_open() -> None:
    field = TextComplement(kind=ComplementKind.BIDDER, mark="1")
    field.fill("Fabrikat A")
    field.fill("  ")
    assert field.empty


# --- a field without a caption ----------------------------------------------------

UNCAPTIONED = (
    "<Text><p><span>Fenster aus Aluminium, weiß.</span></p>"
    "<p><span>Angebotenes Fabrikat:</span></p></Text>"
    '<TextComplement Kind="Bidder" MarkLbl="12" Empty="Yes"><ComplBody><span>\'....\'</span>'
    "</ComplBody></TextComplement>"
)


def test_a_colon_introduces_the_field_after_it() -> None:
    """Fails if a colon counts as the end of a sentence."""
    assert paragraphs(UNCAPTIONED) == ["Fenster aus Aluminium, weiß.", "Angebotenes Fabrikat: '…'"]


def test_a_field_without_a_caption_is_labelled_by_the_words_before_it() -> None:
    """Fails if the context is not recorded, or runs back past the sentence."""
    rich = parse_richtext(UNCAPTIONED)
    assert rich is not None
    assert rich.complements[0].label == "Angebotenes Fabrikat"


def test_a_caption_labels_a_field_that_has_one() -> None:
    rich = parse_richtext(PAIRED)
    assert rich is not None
    assert rich.complements[1].label == "Material"


def test_the_label_is_only_the_clause_before_the_field() -> None:
    """Fails if the context runs back past the end of the previous sentence."""
    rich = parse_richtext(
        "<Text><p><span>Fenster aus Aluminium, weiß. Angebotenes Fabrikat:</span></p></Text>"
        '<TextComplement Kind="Bidder" MarkLbl="12" Empty="Yes"><ComplBody/></TextComplement>'
    )
    assert rich is not None
    assert rich.complements[0].label == "Angebotenes Fabrikat"
