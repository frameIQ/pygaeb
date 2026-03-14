"""DA XML 2.x parser — translates German element names, then delegates to Track B base."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pygaeb.models.document import GAEBDocument
from pygaeb.parser.xml_v2.german_element_map import GERMAN_TO_ENGLISH
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser

logger = logging.getLogger("pygaeb.parser")


class V2Parser(BaseV3Parser):
    """DA XML 2.x parser — thin wrapper that translates German element names
    before delegating to the base v3 parser.
    """

    def parse(self, path: Path, text: str) -> GAEBDocument:
        translated = _translate_elements(text)
        doc = super().parse(path, translated)
        return doc


def _translate_elements(xml_text: str) -> str:
    """Replace German element names with their English equivalents.

    Handles both opening and closing tags, preserving attributes.
    """
    def _replace_tag(match: re.Match[str]) -> str:
        slash = match.group(1) or ""
        tag_name = match.group(2)
        rest = match.group(3) or ""
        english = GERMAN_TO_ENGLISH.get(tag_name, tag_name)
        return f"<{slash}{english}{rest}>"

    result = re.sub(
        r"<(/?)(\w+)((?:\s[^>]*)?)>",
        _replace_tag,
        xml_text,
    )
    return result
