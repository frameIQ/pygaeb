"""DA XML 3.3 compatibility — BIM GUIDs, Base64 attachments in X31."""

from __future__ import annotations

import base64
import logging

from lxml import etree

from pygaeb.models.item import Attachment
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser

logger = logging.getLogger("pygaeb.parser")


class V33Compat(BaseV3Parser):
    """DA XML 3.3 — latest version with BIM support.

    New features:
    - BIM GUIDs on LV objects
    - Base64-embedded images/PDFs in X31 room book files
    - 2023-01 addenda
    """

    @staticmethod
    def supports_bim_guids() -> bool:
        return True

    @staticmethod
    def supports_attachments() -> bool:
        return True


def extract_attachments(item_el: etree._Element, ns_prefix: str = "") -> list[Attachment]:
    """Extract Base64-encoded binary attachments from an item element (DA XML 3.3 / X31)."""
    attachments: list[Attachment] = []

    for attach_el in item_el.iter(f"{ns_prefix}Attachment" if ns_prefix else "Attachment"):
        filename = _get_child_text(attach_el, "Filename", ns_prefix) or "unknown"
        mime_type = _get_child_text(attach_el, "MimeType", ns_prefix) or "application/octet-stream"
        b64_data = _get_child_text(attach_el, "Data", ns_prefix) or ""

        if not b64_data:
            continue

        try:
            data = base64.b64decode(b64_data)
            attachments.append(Attachment(
                filename=filename,
                mime_type=mime_type,
                data=data,
            ))
        except Exception as e:
            logger.warning("Failed to decode attachment %s: %s", filename, e)

    return attachments


def _get_child_text(
    parent: etree._Element, tag: str, ns_prefix: str = ""
) -> str | None:
    full_tag = f"{ns_prefix}{tag}" if ns_prefix else tag
    el = parent.find(full_tag)
    if el is None:
        el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return None
