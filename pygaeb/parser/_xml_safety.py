"""Hardened lxml parser constants — single source of truth for XXE prevention."""

from __future__ import annotations

from typing import Any

from lxml import etree

SAFE_PARSER: etree.XMLParser = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=False,
    dtd_validation=False,
    remove_comments=False,
)

SAFE_RECOVER_PARSER: etree.XMLParser = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=False,
    recover=True,
    encoding="utf-8",
)


def safe_iterparse(
    source: Any,
    events: tuple[str, ...] = ("start",),
) -> Any:
    """Wrapper around ``etree.iterparse`` with XXE protections.

    ``lxml.etree.iterparse`` does not accept a ``parser`` argument;
    instead, security-relevant settings are passed as keyword args.
    """
    return etree.iterparse(
        source,
        events=events,
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
    )
