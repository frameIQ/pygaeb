"""Regression tests for GAEB XML 3.3 files containing XML comments.

iTWO (RIB Software) exports valid GAEB DA XML 3.3 with ``<!-- ... -->``
comments inserted inside elements. lxml reports these comment (and
processing-instruction) nodes during iteration with a *callable* ``.tag``,
which previously crashed the element-iterating loops in the v3 parser with a
``TypeError`` (notably ``_parse_item_attachments``) and could have produced a
spurious breakdown entry in ``_parse_bkdn_v33``.

See the first community-reported issue: comments inside each element of an
iTWO-exported X83 must be skipped, not parsed.
"""

from __future__ import annotations

from textwrap import dedent

from pygaeb import GAEBParser

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
