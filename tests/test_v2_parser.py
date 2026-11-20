"""DA XML 2.x: German element names are renamed before the 3.x parser runs."""

from __future__ import annotations

from pathlib import Path

from pygaeb import GAEBParser
from pygaeb.models.enums import ItemType
from pygaeb.parser.xml_v2.v2_parser import _translate_elements
from tests.conftest import SAMPLE_V20_XML


def test_self_closing_tag_without_attributes_is_renamed() -> None:
    # <Pauschalposition/> used to stay German: the pattern wanted whitespace
    # before anything that follows the name.
    assert _translate_elements("<Position><Pauschalposition/></Position>") == (
        "<Item><LumpSumItem/></Item>"
    )


def test_every_tag_shape_is_renamed() -> None:
    source = (
        '<Position RNoPart="0010"><Kurztext>x</Kurztext>'
        '<Pauschalposition /><Pauschalposition Wert="Ja"/></Position>'
    )
    assert _translate_elements(source) == (
        '<Item RNoPart="0010"><ShortText>x</ShortText>'
        '<LumpSumItem /><LumpSumItem Wert="Ja"/></Item>'
    )


def test_lump_sum_flag_in_a_2x_file_is_read(tmp_path: Path) -> None:
    xml = SAMPLE_V20_XML.replace(
        "<Kurztext>Abbruch Mauerwerk</Kurztext>",
        "<Kurztext>Abbruch Mauerwerk</Kurztext>\n              <Pauschalposition/>",
    )
    f = tmp_path / "old.D83"
    f.write_text(xml, encoding="utf-8")
    item = next(iter(GAEBParser.parse(f).iter_items()))
    assert item.item_type is ItemType.LUMP_SUM
