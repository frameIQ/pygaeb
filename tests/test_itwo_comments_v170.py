"""Regression tests for GAEB XML 3.3 files containing XML comments.

iTWO (RIB Software) exports valid GAEB DA XML 3.3 with ``<!-- ... -->``
comments inserted inside elements. lxml reports these comment (and
processing-instruction) nodes during iteration with a *callable* ``.tag``,
which previously crashed the element-iterating loops in the v3 parser with a
``TypeError`` (notably ``_parse_item_attachments``) and could have produced a
spurious breakdown entry in ``_parse_bkdn_v33``.

See the first community-reported issue: comments inside each element of an
iTWO-exported X83 must be skipped, not parsed.

Comments stay in the XML tree for ``keep_xml`` users; the parsers read past them.
The tests at the end put comments everywhere, in every document kind, so a new
loop that forgets to skip them fails here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from textwrap import dedent

import pytest
from lxml import etree

from pygaeb import GAEBParser, GAEBWriter
from tests.document_kinds import DOCUMENT_KINDS

# A 3.3 file with comments injected the way iTWO does — inside the breakdown
# (BoQBkdn), inside an Item (where item type is classified), and inside the
# Description subtree (where attachments are parsed).
ITWO_WITH_COMMENTS = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3">
      <!-- exported by iTWO -->
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo><Cur>EUR</Cur></AwardInfo>
        <BoQ>
          <BoQInfo>
            <Name>Main BoQ</Name>
            <BoQBkdn>
              <!-- breakdown level comment -->
              <BoQLevel Length="2"/>
              <!-- another comment between levels -->
              <BoQLevel Length="2"/>
              <Item Length="4"/>
            </BoQBkdn>
          </BoQInfo>
          <BoQBody>
            <BoQCtgy RNoPart="01">
              <Itemlist>
                <Item RNoPart="0001">
                  <!-- iTWO item comment -->
                  <ShortText>Item with attachments</ShortText>
                  <Description>
                    <!-- iTWO description comment -->
                    <CompleteText>
                      <DetailTxt>
                        <!-- attachment follows -->
                        <attachment>https://example.com/plan.pdf</attachment>
                        <Text><p>
                          <!-- embedded image follows -->
                          <image Type="image/png" Name="photo.png">iVBORw0KGgo=</image>
                        </p></Text>
                      </DetailTxt>
                    </CompleteText>
                  </Description>
                  <Qty>1</Qty>
                  <QU>pcs</QU>
                </Item>
              </Itemlist>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>
""")


class TestITwoComments:
    def test_parses_without_crash(self) -> None:
        # Previously raised TypeError in _parse_item_attachments.
        doc = GAEBParser.parse_string(ITWO_WITH_COMMENTS)
        assert doc is not None

    def test_uri_attachment_still_parsed(self) -> None:
        doc = GAEBParser.parse_string(ITWO_WITH_COMMENTS)
        item = next(iter(doc.award.boq.iter_items()))
        uri_attachments = [a for a in item.attachments if a.data == b""]
        assert len(uri_attachments) == 1
        assert uri_attachments[0].filename == "https://example.com/plan.pdf"

    def test_embedded_image_still_parsed(self) -> None:
        doc = GAEBParser.parse_string(ITWO_WITH_COMMENTS)
        item = next(iter(doc.award.boq.iter_items()))
        img_attachments = [a for a in item.attachments if a.data != b""]
        assert len(img_attachments) == 1
        assert img_attachments[0].filename == "photo.png"
        assert img_attachments[0].mime_type == "image/png"

    def test_comments_do_not_inflate_breakdown(self) -> None:
        # Comment nodes in the BoQBkdn loop must not become breakdown entries.
        doc = GAEBParser.parse_string(ITWO_WITH_COMMENTS)
        assert doc.award.boq.boq_info is not None
        assert len(doc.award.boq.boq_info.bkdn) == 3

    def test_collect_raw_data_skips_the_comments(self) -> None:
        # Raised TypeError: the raw-data loop was the one the first fix missed.
        doc = GAEBParser.parse_string(ITWO_WITH_COMMENTS, collect_raw_data=True)
        assert next(iter(doc.award.boq.iter_items())).raw_data is None

    def test_comments_stay_in_the_kept_xml_tree(self) -> None:
        doc = GAEBParser.parse_string(ITWO_WITH_COMMENTS, keep_xml=True)
        assert doc.xml_root is not None
        comments = [n.text for n in doc.xml_root.iter(etree.Comment)]
        assert " iTWO item comment " in comments
        assert len(comments) == ITWO_WITH_COMMENTS.count("<!--")


NOISE = ("<!--c-->", "<?pi x?>")
_CDATA = re.compile(r"(<!\[CDATA\[.*?\]\]>)", re.S)


def _in_markup(xml: str, pattern: str, repl: Callable[[re.Match[str]], str]) -> str:
    """``re.sub`` outside CDATA sections: their content is text, so a comment there is not one."""
    return "".join(
        part if part.startswith("<![CDATA[") else re.sub(pattern, repl, part)
        for part in _CDATA.split(xml)
    )


def _comments_between_tags(xml: str) -> str:
    return _in_markup(xml, r">(\s*)<", lambda m: ">" + "".join(NOISE) + m.group(1) + "<")


def _comment_inside_text(xml: str) -> str:
    # "<T>foo bar</T>" -> "<T>foo<!--c--> bar</T>": a comment splitting a value.
    return _in_markup(
        xml, r">([^<>\s]+)( [^<>]*)<", lambda m: f">{m.group(1)}{NOISE[0]}{m.group(2)}<",
    )


def _without_noise(value: object) -> object:
    """Comments stay in raw markup (``raw_html``, nested ``raw_data``): compare without."""
    if isinstance(value, str):
        for marker in NOISE:
            value = value.replace(marker, "")
        return value
    if isinstance(value, dict):
        return {k: _without_noise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_noise(v) for v in value]
    return value


def _snapshot(xml: str, filename: str) -> object:
    doc = GAEBParser.parse_string(xml, filename=filename, collect_raw_data=True)
    return _without_noise({
        "doc": doc.model_dump(mode="json"),
        "raw_data": [item.raw_data for item in doc.iter_items()],
    })


@pytest.mark.parametrize("inject", [_comments_between_tags, _comment_inside_text])
@pytest.mark.parametrize("kind", list(DOCUMENT_KINDS))
def test_comments_anywhere_change_nothing(kind: str, inject: Callable[[str], str]) -> None:
    xml, filename = DOCUMENT_KINDS[kind]
    noisy = inject(xml)

    assert noisy != xml
    assert _snapshot(noisy, filename) == _snapshot(xml, filename)


def test_writing_keeps_the_text_after_a_comment() -> None:
    xml, filename = DOCUMENT_KINDS["X86 award with markups"]
    clean = GAEBParser.parse_string(xml, filename=filename)
    noisy = GAEBParser.parse_string(_comment_inside_text(xml), filename=filename)

    written, _ = GAEBWriter.to_bytes(noisy)
    back = GAEBParser.parse_string(written.decode("utf-8"), filename=filename)
    texts = [item.long_text_plain for item in back.iter_items()]
    assert texts == [item.long_text_plain for item in clean.iter_items()]
    assert "Boden lösen und laden." in texts
