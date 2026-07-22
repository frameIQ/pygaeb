"""Canonical GAEB DA XML ``<Item>`` position-type serialization.

Single source of truth shared by the parser (``_detect_item_type``) and the writer
(``_add_item``), so read and write can never drift again. See
``docs/reference/position-types.md`` for the schema evidence behind these names.

Two tiers:

* **Real GAEB elements** (``REAL_CHILD_MARKER``) — confirmed against the official
  ``tgItem`` complexType. The writer emits these; real AVA software (California,
  ORCA, …) reads them correctly. These carry the sum-affecting markers, i.e. the
  ones behind the "priced but not summed" (Bedarfs-/Alternativ-) rule.
* **Legacy synthetic elements** (``LEGACY_CHILD_MARKER``) — pyGAEB-internal names for
  position types whose real serialization is attribute-based (Grund-/Alternativ
  Zuordnungszahl) or non-standard, and not yet implemented. Emitting them keeps
  pyGAEB round-tripping and its totals correct, but they are **not interoperable**;
  the writer emits a warning when it uses one.

``MARKUP`` is handled separately (``_add_markup_item`` → ``<MarkupItem>`` sibling in the
``<Itemlist>``) and ``NORMAL`` carries no marker, so neither appears here.
"""

from __future__ import annotations

from pygaeb.models.enums import ItemType

#: Confirmed real GAEB DA XML ``<Item>`` child elements. Writer emits; interoperable.
REAL_CHILD_MARKER: dict[ItemType, str] = {
    ItemType.LUMP_SUM: "LumpSumItem",   # Pauschalposition
    ItemType.EVENTUAL: "Provis",        # Bedarfsposition / Eventualposition
}

#: pyGAEB-internal fallback names for types whose real serialization is not yet
#: implemented (Alternativ = Zuordnungszahl attribute; others non-standard). NOT
#: interoperable — the writer warns when it emits one.
LEGACY_CHILD_MARKER: dict[ItemType, str] = {
    ItemType.ALTERNATIVE: "AlternativeItem",     # → real: Zuordnungszahl attr, variant 1-9
    ItemType.BASE_SURCHARGE: "SurchargeItem",    # → real: Zuordnungszahl attr, variant 0
    ItemType.SUPPLEMENT: "SupplementItem",
    ItemType.INDEX: "IndexItem",
    ItemType.TEXT_ONLY: "TextItem",
}

#: Full writer map: ItemType → element name to emit. MARKUP/NORMAL excluded (see above).
WRITER_MARKER: dict[ItemType, str] = {**REAL_CHILD_MARKER, **LEGACY_CHILD_MARKER}

#: Types that serialize only via a non-interoperable synthetic marker → writer warns.
NON_INTEROP_TYPES: frozenset[ItemType] = frozenset(LEGACY_CHILD_MARKER)

#: Parser map: ``<Item>`` child element localname → ItemType. Real names first, plus
#: the legacy synthetic names (kept so existing fixtures/consumers keep parsing).
MARKER_ELEMENT_TO_TYPE: dict[str, ItemType] = {
    # real GAEB
    "LumpSumItem": ItemType.LUMP_SUM,
    "GlobItem": ItemType.LUMP_SUM,
    "Provis": ItemType.EVENTUAL,
    # legacy synthetic (back-compat)
    "AlternativeItem": ItemType.ALTERNATIVE,
    "AltItem": ItemType.ALTERNATIVE,
    "ContingencyItem": ItemType.EVENTUAL,
    "EventualItem": ItemType.EVENTUAL,
    "TextItem": ItemType.TEXT_ONLY,
    "SurchargeItem": ItemType.BASE_SURCHARGE,
    "SupplementItem": ItemType.SUPPLEMENT,
    "IndexItem": ItemType.INDEX,
}

#: Parser map for the synthetic ``<ItemTag>Text</ItemTag>`` element (pyGAEB convention).
ITEMTAG_TEXT_TO_TYPE: dict[str, ItemType] = {
    "NormalItem": ItemType.NORMAL,
    "LumpSumItem": ItemType.LUMP_SUM,
    "AlternativeItem": ItemType.ALTERNATIVE,
    "ContingencyItem": ItemType.EVENTUAL,
    "EventualItem": ItemType.EVENTUAL,
    "Provis": ItemType.EVENTUAL,
    "TextItem": ItemType.TEXT_ONLY,
    "SurchargeItem": ItemType.BASE_SURCHARGE,
    "IndexItem": ItemType.INDEX,
    "SupplementItem": ItemType.SUPPLEMENT,
}

#: Real ``<Item>`` child flags that are NOT type markers but should not be dumped into
#: ``raw_data`` — recognised so ``_collect_raw_data`` skips them.
KNOWN_POSITION_FLAGS: frozenset[str] = frozenset({
    "Provis", "ProvisAccpt", "LumpSumItem", "GlobItem",
    "MarkupIt", "HourIt", "KeyIt", "QtyTBD", "NotAppl",
})
