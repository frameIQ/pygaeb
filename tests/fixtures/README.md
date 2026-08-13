# Test fixtures

Whole-file GAEB documents used by the test suite. Unlike the inline XML in the
test modules — which is hand-written to exercise one code path — these are
complete documents shaped the way real exporters emit them.

Record provenance and licence for every file added here.

| file | format | provenance |
|---|---|---|
| `gaebxml.x83` | DA XML 3.2, X83 | Written for pyGAEB. Element structure mirrors the output of a third-party AVA tool; all names, texts, identifiers and dates are invented. |

## Why `gaebxml.x83` looks the way it does

It reproduces the structural traits that a real exporter produces and that
hand-written test XML tends to miss:

- the DA XML **3.2** breakdown form — three sibling `<BoQBkdn>` elements with
  `<Type>`/`<Length>`/`<Num>` children, rather than the 3.3 single-element form
- `<Description><CompleteText>` wrapping `<ComplTSA>`/`<ComplTSB>` flags
  alongside `<DetailTxt>` and `<OutlineText>` — the shape behind issue #30
- items carrying `<QtyTBD>` in place of `<Qty>`
- a category with an empty `<LblTx>`
- a `<Remark>` block holding a full description tree at body level
- empty `<Street>`/`<PCode>`/`<City>` elements
- unit-price component labels (`NoUPComps`, `LblUPComp1`, `LblUPComp2`, `LblTime`)
- inline `<span>` markup inside labels and texts

Keep these traits when editing the file — several exist purely to hold a
regression in place.
