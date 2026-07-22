# Position types — canonical GAEB DA XML serialization

> **Task 0 reference.** Establishes the *real-schema* representation of each BoQ position type,
> so the parser and writer share one authoritative definition instead of the pyGAEB-internal
> synthetic tags (`<ItemTag>`, `<AlternativeItem/>`, `<ContingencyItem/>`) that no real GAEB
> exporter emits.

## Sources

- **GAEB DA XML `tgItem` complexType**, Altova-generated schema documentation of `GAEB_DA_XML.xsd`
  (Institut für Bauinformatik / TU Dresden print of the official schema) — authoritative element
  and attribute names.
- **GAEB DA XML Fachdokumentation 3.3 (Ausgabe 2023-01)**, §4.5 "Besondere Positions- und
  Ausführungsarten", §11.4/§11.5 — semantics and the `ZZ`/`ZZV` Zuordnungszahl linkage.

## The real `<Item>` (tgItem) position-type members

Position type in GAEB DA XML is marked by the **presence of a child element** inside `<Item>`
(a Normalposition has none), except the Grund-/Alternativ linkage which is an **attribute**
(Zuordnungszahl). Confirmed members of `tgItem`:

| Concept (DE) | Real element/attr | Notes |
|---|---|---|
| Bedarfsposition (Eventualposition) | `<Provis>` | contingency. Value distinguishes *mit GB* vs *ohne GB*; *ohne GB* prints "Nur Einh.-Preis" and is **excluded from the sum** |
| Bedarfsposition beauftragt | `<ProvisAccpt>` | contingency now ordered |
| Pauschalposition | `<LumpSumItem>` | lump sum; Qty may be omitted or = 1 |
| Zuschlagsposition | `<MarkupItem>` | a **sibling in `<Itemlist>`**, not an `<Item>` child; carries `MarkupType` ∈ {IdentAsMark, AllInCat, ListInSubQty}, `MarkupIt` refs, `MarkupSubQty`/`SubQty` |
| Position "zu bezuschlagen" | `<MarkupIt>` | child flag on a *normal* Item, marking it as a base for a following MarkupItem |
| Stundenlohnarbeiten | `<HourIt>` | time/day-work |
| Schwerpunktposition | `<KeyIt>` | key/emphasis position |
| Freie Menge (Menge vom Bieter) | `<QtyTBD>` | bidder enters the quantity; mutually exclusive with `Qty` in X83 |
| Position entfällt | `<NotAppl>` | not applicable; excluded from sum |
| Grund-/Alternativposition | **Item attribute** = Zuordnungszahl | ≤4-digit: group (1–3 digits) + last digit variant: `0`=Grundposition, `1`–`9`=Alternativposition. Alternatives print "Nur Einh.-Preis" and are **excluded from the sum**. Only valid within the same LV-Bereich. |
| Teilmengen | `<QtySplit>` | `{ QtyPct, Qty, QU, CtlgAssign }`; Σ QtySplit must equal the position Qty (Fachdok Item constraint 6) |

## Mapping to pyGAEB `ItemType`

`pygaeb/models/enums.py::ItemType`. `affects_total` (whether the position's IT enters
`computed_grand_total`) must follow the GAEB "Nur Einh.-Preis" rule.

| `ItemType` | Real serialization | `affects_total` | Status in current code |
|---|---|---|---|
| `NORMAL` | (no marker) | yes | ok |
| `LUMP_SUM` | `<LumpSumItem/>` | yes | name already correct |
| `EVENTUAL` | `<Provis>` (ohne GB) | **no** | **parser reads wrong name** (`ContingencyItem`); writer emits nothing |
| `ALTERNATIVE` | Item attr Zuordnungszahl (variant 1–9) | **no** | **parser reads wrong name** (`AlternativeItem`); writer emits nothing; **model lacks the Zuordnungszahl field** |
| `BASE_SURCHARGE` | Item attr Zuordnungszahl (variant 0) + `<MarkupIt>` when surcharged | context | parser reads wrong name (`SurchargeItem`) |
| `MARKUP` | `<MarkupItem>` sibling | computed | already handled by `_add_markup_item` |
| `TEXT_ONLY` | Item with no Qty/UP/IT (Hinweis) | no | approximate |
| `INDEX`, `SUPPLEMENT` | non-standard / vendor | no | keep lenient read only |

## Decisions for the fix

1. **Writer emits real elements**: `EVENTUAL → <Provis>`, `LUMP_SUM → <LumpSumItem/>`,
   and the Zuordnungszahl attribute for `ALTERNATIVE`/`BASE_SURCHARGE` once the model carries it
   (Task 3 adds an `alloc`/Zuordnungszahl field to `Item`). `MARKUP` keeps `<MarkupItem>`.
2. **Parser reads real elements** (`Provis`, `ProvisAccpt`, `LumpSumItem`, `MarkupIt`, `HourIt`,
   `KeyIt`, `QtyTBD`, `NotAppl`) **and** the Zuordnungszahl attribute, **in addition to** the
   existing synthetic forms (kept for back-compat with current fixtures/consumers).
2. **One shared const**: encode this table once (`pygaeb/models/position_types.py`) and import it
   into both `_detect_item_type` and `_add_item` so read/write can never drift again.
4. **`affects_total`** stays as the single source of truth for sum inclusion; `EVENTUAL`,
   `ALTERNATIVE`, `NotAppl` are excluded, matching the "Nur Einh.-Preis" rule.

## Still to confirm against a real file / full XSD (not blocking)

- Exact **attribute name** carrying the Zuordnungszahl (the printout labels it only "Nur bei
  Grund-/Alternativposition"; likely `Alloc`). Confirm from a real vendor export before relying on
  it for cross-software round-trip; `<Provis>`/`<LumpSumItem>` (the sum-affecting markers, i.e. the
  €50k→€121k bug) are already fully confirmed.
- `<Provis>` value domain for the *mit GB* vs *ohne GB* distinction.
