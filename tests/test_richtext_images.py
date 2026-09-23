"""Graphics embedded in a long text.

GAEB DA XML carries a drawing as ``<image Type="image/jpeg">`` with the base64 as
the element's own content, not as ``<img src="...">``. The extractor only looked
for the latter, so a graphic was never found — and because the ``<p>`` wrapping it
yields the element's text, the whole base64 blob was swept into ``paragraphs`` and
``plain_text`` instead.

The visible effect is tens of kilobytes of unreadable base64 sitting in the middle
of a specification, in the one field an estimator has to read to price the work.
"""

from __future__ import annotations

from pygaeb.parser.xml_v3.richtext_parser import parse_richtext

# A one-pixel JPEG is still a JPEG; the point is the element, not the picture.
PIXEL = "/9j/4AAQSkZJRgABAQEBLAEsAAD//gAfTEVBRA=="

GAEB_IMAGE = f"""
<Text>
  <p><span>Boden für Baugruben profilgerecht lösen.</span></p>
  <p><span>Langtext mit Grafik</span></p>
  <p><image align="left" width="217" Type="image/jpeg" Name="bagger.jpg">{PIXEL}</image></p>
</Text>
"""


def test_a_gaeb_image_element_is_found() -> None:
    rich = parse_richtext(GAEB_IMAGE)

    assert rich is not None
    assert rich.images == [f"data:image/jpeg;base64,{PIXEL}"]


def test_the_base64_stays_out_of_the_prose() -> None:
    """The regression that matters: a specification you can actually read."""
    rich = parse_richtext(GAEB_IMAGE)

    assert rich is not None
    assert rich.paragraphs == [
        "Boden für Baugruben profilgerecht lösen.",
        "Langtext mit Grafik",
    ]
    assert PIXEL not in rich.plain_text


def test_the_declared_mime_type_is_kept() -> None:
    rich = parse_richtext(
        f'<Text><p><image Type="image/png" Name="d.png">{PIXEL}</image></p></Text>'
    )

    assert rich is not None
    assert rich.images[0].startswith("data:image/png;base64,")


def test_an_image_without_a_type_falls_back_to_jpeg() -> None:
    # GAEB files in the wild omit the attribute; JPEG is what they carry in practice.
    rich = parse_richtext(f"<Text><p><image>{PIXEL}</image></p></Text>")

    assert rich is not None
    assert rich.images[0].startswith("data:image/jpeg;base64,")


def test_html_style_images_still_work() -> None:
    """The other shape, which was the only one handled before."""
    rich = parse_richtext('<Text><p><img src="https://example.org/d.png"/>Hinweis</p></Text>')

    assert rich is not None
    assert rich.images == ["https://example.org/d.png"]
    assert rich.paragraphs == ["Hinweis"]


def test_a_text_that_is_only_a_graphic_is_not_discarded() -> None:
    # No prose at all, but the position still has something to show.
    rich = parse_richtext(f'<Text><p><image Type="image/jpeg">{PIXEL}</image></p></Text>')

    assert rich is not None
    assert rich.paragraphs == []
    assert len(rich.images) == 1
