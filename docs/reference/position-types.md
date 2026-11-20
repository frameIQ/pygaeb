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
(a Normalposition has none). The Grund-/Alternativ linkage (Zuordnungszahl) is a pair of
child elements that opens the item. Confirmed members of `tgItem`:

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
| Grund-/Alternativposition | `<ALNGroupNo>` + `<ALNSerNo>`, then `<Accepted>` | The Zuordnungszahl, first in `tgItem` and `tgMarkupItem`: group 0–999, serial `0` = Grundposition, `1`–`9` = Alternativposition. Alternatives print "Nur Einh.-Preis" and are **excluded from the sum**. `Accepted` (X80–X82, X86, X87; not X83/X85) records the award: `AltAccept` on the alternative taken, `BasReject` on the base it replaces. X84 has none of the three. Categories have `ALNBGroupNo`/`ALNBSerNo` for whole base/alternative areas. |
| Teilmengen | `<QtySplit>` | `{ QtyPct, Qty, QU, CtlgAssign }`; Σ QtySplit must equal the position Qty (Fachdok Item constraint 6) |

## Mapping to pyGAEB `ItemType`

`pygaeb/models/enums.py::ItemType`. Whether a position's IT enters the sums follows the
GAEB "Nur Einh.-Preis" rule. `Item.affects_total` is the single source of truth: it reads
`NotAppl`, the Zuordnungszahl (`Item.alternative_group`) and `Provis`, and defers to
`ItemType.affects_total` otherwise.

| `ItemType` | Real serialization | `affects_total` | Status in current code |
|---|---|---|---|
| `NORMAL` | (no marker) | yes | ok |
| `LUMP_SUM` | `<LumpSumItem/>` | yes | name already correct |
| `EVENTUAL` | `<Provis>WithTotal</Provis>` / `<Provis>WithoutTotal</Provis>` | **mit GB yes**, ohne GB or unset no | `Item.provis` |
| `ALTERNATIVE` | `ALNGroupNo` + `ALNSerNo` 1–9 | **no**, unless `Accepted` = `AltAccept` | `Item.alternative_group`; read and written (DA XML 3.3) |
| `BASE_SURCHARGE` (the Grundposition) | `ALNGroupNo` + `ALNSerNo` 0 | **yes**, unless `Accepted` = `BasReject` | `Item.alternative_group`; read and written (DA XML 3.3) |
| `MARKUP` | `<MarkupItem>` sibling | **yes, with its own `IT`** | `markup_base` = `ITMarkup`, `unit_price` = `Markup` (%), `total_price` = `IT` |
| `TEXT_ONLY` | Item with no Qty/UP/IT (Hinweis) | no | approximate |
| `INDEX`, `SUPPLEMENT` | non-standard / vendor | no | keep lenient read only |

The BVBS Prüfdatei `ava/award.X86` bears this out: its declared category totals match
only when Bedarfspositionen mit GB and markup amounts are both counted. Two categories
differed because the Zuordnungszahl was not read, so their alternatives counted as normal
positions. It is read now; the check against that file is still to be repeated, as the
file is not in the repository.

## Decisions for the fix

1. **Writer emits real elements**: `EVENTUAL → <Provis>`, `LUMP_SUM → <LumpSumItem/>`, and
   `ALNGroupNo`/`ALNSerNo`/`Accepted` for any item or markup with an `alternative_group`.
   `MARKUP` keeps `<MarkupItem>`. The pyGAEB-internal `<AlternativeItem>`/`<SurchargeItem>`
   markers remain only for positions typed without a group, and for DA XML 3.0–3.2 and 2.x.
2. **Parser reads real elements** (`Provis`, `ProvisAccpt`, `LumpSumItem`, `MarkupIt`, `HourIt`,
   `KeyIt`, `QtyTBD`, `NotAppl`, `ALNGroupNo`, `ALNSerNo`, `Accepted`) **in addition to** the
   existing synthetic forms (kept for back-compat with current fixtures/consumers).
3. **One shared const**: encode this table once (`pygaeb/models/position_types.py`) and import it
   into both `_detect_item_type` and `_add_item` so read/write can never drift again.
4. **`Item.affects_total`** is the single source of truth for sum inclusion; `NotAppl`,
   alternatives not accepted, rejected base positions and Bedarfspositionen *ohne GB* are
   excluded, matching the "Nur Einh.-Preis" rule.

## Still to confirm against a real file / full XSD (not blocking)

- ~~Exact name carrying the Zuordnungszahl.~~ Confirmed against the 2021-05 XSDs: not an
  attribute but the elements `ALNGroupNo`, `ALNSerNo` and `Accepted`, the first children of
  `tgItem` and `tgMarkupItem`. pyGAEB's output validates for X81–X86.
- Whether DA XML 3.0–3.2 have the same elements. pyGAEB writes them only for 3.3 and reports
  the Zuordnungszahl as dropped for older versions until their schemas are checked.
- Whether X89 (invoice) carries them; its schema is not in the 2021-05 Leistungsverzeichnis
  package.
- Base/alternative **areas** (`ALNBGroupNo`/`ALNBSerNo` on `BoQCtgy`) are not modelled yet: the
  parser warns, and their positions are summed like any others.
- ~~`<Provis>` value domain for the *mit GB* vs *ohne GB* distinction.~~ Confirmed:
  `WithTotal` / `WithoutTotal`, as used in the BVBS `ava/award.X86`.
