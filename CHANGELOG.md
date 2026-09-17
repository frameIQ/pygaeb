# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.18.1] - 2026-09-17

Follow-ups from driving the MCP server through multi-step questions in Claude Desktop. Every item is data the parser already held but the tools did not show, or two code paths that disagreed.

### Changed

- **Repeated OZs: diff and bid analysis both keep the first copy and say so.** `BoQDiff` matched the first copy of a full OZ a file repeats while `BidAnalysis` priced the last, so a bid's grand total in `analyze_bids` differed from `open_document`'s by an amount nobody could explain. Both keep the first copy now; `DiffSummary.duplicates_collapsed` (`{oz, count_a, count_b}`), `BidAnalysis.duplicates_collapsed(bidder)` and the two MCP results report which OZs were collapsed and how many copies each had.
- **Markup items no longer get a "Missing short text" note.** DA XML 3.x never carries one on a `MarkupItem`.

### Added

- **`BoQTree.find_items()` returns every copy of a repeated full OZ; `find_item_by_id()`.** MCP `get_item` and `get_item_long_text` refuse a repeated OZ with the copies listed and accept `item_id` — the XML `@ID` (now on every `list_items` row) or `#2` for the second copy in document order when a file carries no ids.
- **MCP: markup items show what they apply to.** Rows and details of a `Markup` item carry `markup: {type, rate_pct, amount, base_positions}` (`AllInCat` = a percentage on every position of the enclosing category; explicit `MarkupSubQty` references in `base_positions`), and their `unit_price`/`total_price` are null so a 48 % rate is never read as €48.
- **MCP: `content_sha256`.** `open_document` reports a short digest of the file bytes, and `list_documents(with_digest=true)` adds it per listed file, so "are these seventeen files the same?" is one call instead of sixteen opens and fifteen diffs. Handles stay path-and-mtime based.
- **MCP: `search_items(whole_word=true)`.** A one-letter query like "U" no longer matches every item through "und".

## [1.18.0] - 2026-09-17

Driving the MCP server from Claude Desktop against real bid files showed that every consumer of an item's identity used `Item.oz` — the leaf `RNoPart` alone, `"0010"` — although `Item.full_oz` (`"02.0010"`) had existed since 1.14. A leaf recurs in every category, so the diff paired a window position with a trench excavation, the bid analysis collapsed 28 positions into 7 keys, validation said "Item 0030" when five items carried that number, and `get_item("0010")` silently returned the first one. This release moves every reader, key and message to the full OZ. Written XML is untouched: `RNoPart` attributes stay the leaf.

### Changed

- **Diff matches positions by full OZ within a lot.** `BoQDiff.compare` no longer pairs `02.0020` with `001.002.0020`; `ItemAdded`/`ItemRemoved`/`ItemModified.oz` and `ItemMoved.oz` carry the full OZ, and the structure diff keys categories by their rno path so a sub-category "01" under "02" is distinct from the top-level "01". Section changes are reported in document order.
- **`BidAnalysis` keys prices by full OZ.** `from_x84_bids` and `from_x82` no longer overwrite positions that share a leaf. `price_spread` and `get_bidder_price` still accept a bare leaf when only one position has it and raise `ValueError("ambiguous OZ '0010': 01.0010, 02.0010")` otherwise (`resolve_oz` exposes the rule). Totals fall back to qty × unit price when a bid states no item totals, alternative and eventual positions are priced but no longer summed (`BidderPrice.affects_total`), and a bidder without a single priced item sorts last instead of winning with 0 € (`priced_item_count`, `lowest_bidder` is `None` when nobody priced). The constructor contract is unchanged: callers who build the `{bidder: {oz: BidderPrice}}` mapping themselves keep their own keys.
- **Validation messages name the full OZ and the node kind.** `Item 02.0010: …`, `MarkupItem 002.001.0030: …`. Markup items no longer get a "Missing short text" note — 3.x files never carry one. `CrossPhaseValidator` compares source and response by full OZ. `BoQ.get_item`, `BoQCtgy.remove_item` and `Item.__repr__` accept or show the full OZ; `BoQBuilder`'s duplicate check and warning texts use it too. `convert_document`'s database export keeps its `oz` column as the leaf.
- **`is_likely_same_project` no longer defaults to true.** Two documents without project numbers compared as "the same project" whatever they contained. Project numbers (`Prj`, falling back to `PrjID`) decide when both exist, then project names, then a match ratio of at least 50 %.
- **Quality score expects unit prices in priced phases.** In X82/X84/X86/X88/X89 an item that counts toward the total is incomplete without a unit price; markup items no longer count as incomplete for lacking a short text (3.x files never carry one).

### Added

- **`BoQNode.oz` and `BoQTree.find_items()`.** `node.rno` stays the leaf, as for categories; `node.oz` is the full OZ. `find_items("0010")` returns every item with that leaf so a caller can refuse to guess; `find_item` keeps its first-match behaviour. `node.label` falls back to the full OZ.
- **Duplicate OZ is a validation error.** `Duplicate OZ 001.001.0010 (3x) in lot '1'` — keyed on the full OZ and `RNoIndex`, so index positions sharing a number are fine and the same leaf in two categories is not a duplicate.
- **`Lot.synthetic`.** The placeholder lot the parser wraps a lot-less BoQ in is marked, so summaries, structure listings and `label_path` can hide it — the file has no "Default" lot.
- **MCP: `open_document` reports the tender's dates.** `award.open_date`, `open_time`, `eval_end`, `submit_location`, `construction_start`/`_end`, `contract_no`, `contract_date`, `award_no`, `procurement_type`, `description` — the submission date is the first thing an estimator asks.
- **MCP: `list_documents` tool.** Lists the GAEB files under the allowed roots (recursive, hidden directories and symlinks skipped, paginated, scan capped at 5 000 files) so an assistant can find a file without the user typing an absolute path. Ten read tools now.
- **MCP: `--xsd-dir`.** Same as `PYGAEB_XSD_DIR`; the "XSD validation skipped" note now names both. When schema errors appear in a file an older pyGAEB wrote, an info note says that re-exporting with the current version fixes them.
- **MCP: `compare_documents` returns `structure`** — the sections added, removed and renamed and the items moved (first 20 of each), not just their counts.
- **MCP: `search_items` also matches the OZ and category labels.** Each hit says which `field` matched (`oz`, `short_text`, `category`, `long_text`), so "Außentür" finds the positions under *Außentüren Aluminium*.

### Fixed

- **MCP: `get_item` and `get_item_long_text` refuse an ambiguous leaf.** `get_item("0010")` on a file with `02.0010` and `03.0010` raises and lists both instead of returning the first.
- **MCP: `list_items` filters and sorts on the computed total.** `min_total`, `max_total`, `sort='total_desc'`, `sum_of_matched_totals` and `pct_of_grand_total` use the stated total, else qty × unit price; rows carry `computed_total`. A bid with unit prices only used to return nothing for "items above 5 000 €".
- **MCP: `open_document` reports `grand_total: null` when no item states a total**, keeping `computed_grand_total`, instead of `"0"` next to a six-figure computed total. `analyze_bids` ranks on computed totals, returns `grand_total`/`rank` null with `priced_items: 0` for a bidder who priced nothing, and reports `spread_unmatched`/`spread_ambiguous` instead of silently dropping OZs.
- **MCP: bare file names now open.** `open_document` and `convert_document` resolved relative paths against the server's working directory, which desktop clients set to `/`, so `tender.X83` with a correct `--root` failed with "outside the allowed roots". Relative paths are now looked up under each root in order; write destinations resolve against `--output-dir`.
- **MCP: unpriced tenders no longer report a total of `"0"`.** `open_document` returns `is_priced` and null totals for an X83 without prices, and `list_items` returns a null `sum_of_matched_totals`, so an assistant cannot read a blank tender as costing 0 €.

## [1.17.0] - 2026-09-15

DA XML 3.3 procurement output now validates against the official GAEB 2021-05
schemas. Verified on the BVBS certification test files (Prüfdateien): every
export step of the AVA, Bauausführung and Texterstellung criteria — X81, X82,
X83, X84 and X86 — passes the per-phase XSD, where 1.16.3 failed every one of
them (161 schema errors on the AVA X81 alone). The parser keeps reading every
shape it read before; only what the writer *emits* changed.

### Changed

- **`<ProgSystem>` names pyGAEB as the generating software.** BVBS criterion 2.3 checks that the exported file names the software that produced it; the writer used to copy the source's value (so a pyGAEB export claimed to come from the source tool). Every 3.x write now stamps `pyGAEB <version>`; pass `prog_system=` (and `prog_name=`) to `GAEBWriter.write()`/`to_bytes()` to name your own application instead. `<ProgName>` keeps the source's value, as issue #34 required. The invented `<ProgSystemVersion>` element is no longer written for 3.x — no schema defines it.
- **Every 3.x version writes the breakdown in the sibling form.** 1.16.3 introduced `bkdn_sibling_form` for "3.2 and earlier" and kept the nested `<BoQBkdn><BoQLevel Length=…/>` shape for 3.3. The official 3.3 XSD has no such shape: `tgBoQBkdn` is `Type, LblBoQBkdn?, Length, Num, Alignment?`, one element per level, for 3.0 through 3.3. The nested shape is DA XML 2.x (`LVGliederung`/`OZEbene`) and is still written for 2.0/2.1. `Num` is required and is written as `Yes` unless the model says `False`; level labels and alignment are now carried.
- **The writer follows each phase's schema profile.** X83 (tender) has no prices, no totals and no contractor; X84 (bid) has no category labels, no catalog assignments, no position-type markers, and its item texts hold only the bidder's `TextComplement` blocks; X86 (contract) requires owner, contractor and category totals. Elements the target phase cannot carry are left out and reported once per element kind as `… not written … not part of X84 in DA XML 3.x`, which is distinct from the `dropped` wording that signals real data loss. A missing but required party block (X84 CTR, X86 OWN/CTR) is written as an empty-address placeholder with a warning; a missing required `Totals` is computed from the items.
- **X84 exports no longer carry Bedarfs-/Pauschal-/Alternativposition markers.** The X84 schema has none — a bid inherits the position types from its tender (X83). A pyGAEB X84 round trip therefore reads those items back as Normal; the writer says so per document. Round-trip tests that need markers and prices now go through X86.
- **pyGAEB-only elements are no longer written into 3.x output.** `<Attachment>` (embedded images still travel inside the long text markup), `<GUID>`, `QtySplit/Label` and `QtySplit/QU` (`tgQtySplit` is `(QtyPcnt|Qty) CtlgAssign*`), `<ShortText>` on markup items and `<RefRNoPart>` do not exist in the GAEB schema. `<BidderUP>` (Preisspiegel data) is the one exception: it is still written, with a warning, because GAEB has no home for it and dropping it would lose the data.
- **`<CONo>` is only written together with `<COStatus>`**, as the schema demands; set `item.co_status` (e.g. `Recog`) for change-order items or the number is dropped with a warning.

### Added

- **`validate_xml(xml, version, phase, xsd_dir=None)`, `resolve_schema()`, `XsdResult`/`XsdError`** (in `pygaeb.parser.gaeb_parser`, exported from `pygaeb`) and **`GAEBWriter.validate_against_xsd(doc, phase=…, xsd_dir=…)`**. The lookup understands the official distribution's file names (`GAEB_DA_XML_83_3.3_2021-05.xsd` + the `Lib` include), in a flat folder or under `v33/`, and picks the schema by exchange phase. `GAEBParser.parse(xsd_dir=…)` and `BoQBuilder.build(xsd_dir=…)` use the same lookup; both used to load whichever `.xsd` globbed first and validated against the wrong phase. Schemas remain unbundled (GAEB licensing).
- **`pygaeb.writer.phase_profiles`** — the per-phase allow/require tables (`LIB`, `X83`, `X84`, `X86`, `GENERIC`) the writer consults; `profile_for(phase)`.
- **Model fields the schema needs:** `Item.id`, `Item.rno_index`, `Item.provis` (`Provis.WITH_TOTAL`/`WITHOUT_TOTAL` — Bedarfsposition mit/ohne GB), `Item.co_status`; `BoQ.id`, `Lot.id`, `BoQCtgy.id`; `BoQBkdn.label`/`alignment` and a tri-state `num`; `BoQInfo.outl_compl`, `BoQInfo.lbl_up_comp_types` (`LblUPCompN/@Type`); `AwardInfo.contractor` (`Party`: CTR address, DPNo, AwardNo, AcctsPayNo, BidderNo) and `AwardInfo.construction_site` (`ConstructionSite`); `MarkupSubQty.ref_id` (`RefItem/@IDRef`, resolved to `ref_rno` after parsing). All parsed from 3.x sources and written back.
- **`tests/fixtures/synthetic_33.X86`**, a self-authored, schema-valid 3.3 award covering the structures the BVBS criteria check (Bedarf mit GB, Pauschal, Index position, Zuschlag with `RefItem`, labelled breakdown levels, UP component types, owner and contractor). **`tests/test_writer_conformance_shape.py`** pins the writer's structure without XSDs; **`tests/test_xsd_resolver.py`** covers the lookup; **`tests/test_bvbs_conformance.py`** runs the certification export matrix against the real files and schemas when `PYGAEB_BVBS_FIXTURES` and `PYGAEB_XSD_DIR` are set, and is skipped otherwise.

### Fixed

- **Required `@ID` attributes were never written** on `BoQ`, `BoQCtgy`, `Item` and `MarkupItem` (`xs:ID`, required) — every 3.x export failed the schema on this alone. Source IDs are kept; missing ones are generated as document-unique NCNames (`I1`, `C1`, …), deterministically, and a duplicated or invalid source ID is replaced. The X31 writer shares the allocator, so items repeating an `RNoPart` across categories no longer collide on `I_<rno>`.
- **Element order inside `GAEBInfo`, `PrjInfo`, `AwardInfo`, `BoQInfo`, `BoQCtgy`, `Item`, `MarkupItem` and `Address` now follows the schema sequences** (`VersDate, Date, Time, ProgSystem, ProgName`; `CtlgAssign` before `UP`; `QtySplit` right after `Qty`; `UPComp`/`DiscountPcnt` only inside the `UP` group; `ITMarkup` before `Markup`; `Totals` after `BoQBody`; `ILN` before `Contact`). `Prj`/`PrjName`/`PrcTyp` were written into `AwardInfo`, which has no such elements — the project number now goes to `PrjInfo/PrjID`.
- **`<VersDate>` is taken from the target version** (`2021-05` for 3.3, `2013-10` for 3.2) when a document is converted, instead of carrying the source's value into a version whose schema enumerates a different one.
- **`<LblTx>` and `<Descrip>` were written as plain text**; both are formatted text (`p`/`span`), and `LblTx` is required — an empty element is written for label-less categories.
- **`<Provis>` was written empty**; it now carries `WithTotal`/`WithoutTotal`, so the Bedarfsposition-mit/ohne-GB distinction survives. `<LumpSumItem>` is written as `Yes` (`tgYesNo`), and a `<LumpSumItem>No</LumpSumItem>` no longer reads as a Pauschalposition.
- **Owner and contractor blocks:** `Address/Email` (was `EMail`), the four required address children are always present in X84/X86 party blocks, and the legacy `<OWN>text</OWN>` inside `AwardInfo` is written back as `OWN/Address/Name1`.
- **`MarkupSubQty` referenced items by an invented `<RefRNoPart>`**; the schema's `<RefItem IDRef="…"/>` is written, resolved from the item's ID or its RNoPart, and read back.
- **`Totals` wrote `DiscountPcnt` and `DiscountAmt` side by side and without `TotAfterDisc`**; the schema allows one discount form, only together with the discounted total.
- **Long-text markup was serialised as HTML** (`<br>`), so texts containing a line break could not be re-embedded and fell back to plain paragraphs, losing inline formatting and embedded images on the way out. XML serialisation keeps them intact.
- **`BoQBuilder`'s XSD check used a bare `etree.XMLParser`** instead of the hardened parser factory.

## [1.16.3] - 2026-08-13

### Fixed

- **Every item's `long_text` was prefixed with the text-supplement flags and suffixed with its own short text** ([#30](https://github.com/frameIQ/pygaeb/issues/30)). `Description/CompleteText` holds `<ComplTSA>`/`<ComplTSB>` flags and the `<OutlineText>` alongside the actual `<DetailTxt>`, but `_find(desc_el, "CompleteText", "DetailTxt")` matched the wrapper and the whole subtree was serialized, so `plain_text` came back as `'No\nNo\nExcavation for the building pit.\nNo\nExcavation'`. The parser now descends to `DetailTxt`, and still reads it when a writer places it directly under `Description`. `TradeParser` shared the defect and shares the fix. Long text feeds LLM classification and structured extraction, so every prompt carried the junk.
- **`RichText.paragraphs` repeated each paragraph.** `_extract_paragraphs` matched `p`, `div` and `span` alike, so `<p><span>x</span></p>` — the ordinary GAEB shape — yielded `x` twice. Only the innermost block elements are collected now, with `span` used as a fallback when there are none.
- **`<QtyTBD>` was neither parsed nor written** ([#31](https://github.com/frameIQ/pygaeb/issues/31)). The flag marks a quantity that is still to be determined, so a missing `<Qty>` is deliberate rather than absent data — but it was dropped on read and never emitted, leaving those items indistinguishable from items that simply carry no quantity, and silently downgrading them on write. Adds `Item.qty_tbd`, parsed from `<QtyTBD>` and written back before `<Qty>`.
- **`target_version=3.2` wrote a 3.3 breakdown** ([#32](https://github.com/frameIQ/pygaeb/issues/32)). `_add_boq_info` always emitted the 3.3 spelling — level elements nested in one `<BoQBkdn>` — so a document written as 3.2, 3.1 or 3.0 carried no `<Type>` element at all and was not conforming for consumers that require it. `VersionMeta` gains `bkdn_sibling_form`, set for 3.2 and earlier, and the two shapes are now emitted from one helper. Round-trips through pyGAEB were unaffected either way, since 1.16.1 reads both.
- **Item text was written as flat `<ShortText>`/`<LongText>` for every version** ([#33](https://github.com/frameIQ/pygaeb/issues/33)). Those are the 2.x spelling; DA XML 3.x carries short and long text inside `<Description><CompleteText>`, so 3.x output was not what conforming consumers read, and all inline `<span>` markup was dropped on the way out. 3.x now emits the full `Description` → `CompleteText` → `DetailTxt`/`OutlineText` tree with the source's inline markup carried across, while 2.x keeps the flat elements that `_translate_to_german` renames. Source markup is re-embedded with namespaces stripped, so writing a 3.2 document as 3.3 no longer leaves the old namespace on the text nodes, and a plaintext long text (from a 2.x source) is rebuilt as `<Text><p>` rather than sitting loose in `<DetailTxt>`. The parser now stores the description's inner markup only, matching the contract the `<LongText>` path already followed.
- **Document metadata was dropped on write** ([#34](https://github.com/frameIQ/pygaeb/issues/34)), from three separate causes. `<VersDate>` was parsed and never written. `<Date>` was written but always stamped with `datetime.now()`, overwriting the document's own date. `<DP>` — the exchange-phase marker the trade, cost and QD writers all emit — was missing from the award writer. `<ProgName>` was folded into `prog_system_version`, so it came back out under the wrong element name. And `<Time>`, `<BoQID>`, the BoQ's own `<Date>`, the breakdown's `<Num>` flag and the unit-price component labels (`NoUPComps`, `LblUPComp1`/`2`, `LblTime`) were never modelled at all — they now have fields and round-trip in both breakdown shapes. `<Street>`/`<PCode>`/`<City>` were never lost: those source elements are empty, so parsing them to `None` and omitting them is correct.
- First whole-file test fixture (`tests/fixtures/`), shaped the way real exporters emit: the DA XML 3.2 three-element breakdown, `CompleteText` wrapping flags and outline text, `QtyTBD` in place of `Qty`, an empty category label, a body-level `Remark`, and inline `span` markup. Both defects above were invisible to 1188 passing tests built from hand-written XML and surfaced immediately against it.

## [1.16.2] - 2026-08-13

Follow-up to 1.16.1: the same silent-data-loss shape, audited across the other
document kinds. Content held without its expected wrapper element, or split
across sibling wrappers, was being dropped.

### Fixed

- **Quantity determination (X31) dropped items split across sibling `Itemlist` elements.** `_parse_qty_body` and `_parse_qty_ctgy` located the item list with `_find`, which returns only the first match, so a body or category holding several `<Itemlist>` siblings kept the first and silently lost the rest — on the path that feeds billing. Both now use `_findall`. `CtlgAttachment` was reading only its first container for the same reason and is now read repeatably too.
- **Elemental costing (X50/X51) dropped cost elements held directly by a category.** `_parse_ec_ctgy` read its contents only through an `<ECBody>` wrapper, so a `<CostElement>` sitting directly under an `<ECCtgy>` was lost entirely — the exact shape of the BoQ defect in [#27](https://github.com/frameIQ/pygaeb/issues/27), one document kind over. The category now falls back to reading its own children, mirroring what the BoQ parser already did.
- **Only the first body element was read under a category, in both the BoQ and cost hierarchies.** 1.14.1 fixed the *writer*, which until then emitted one `BoQBody` per subcategory, but the reader was never fixed — so files written by pyGAEB ≤1.14.0 still loaded with everything after the first body missing. `BoQCtgy` and `ECCtgy` now read every sibling body and merge them in document order. A category with no content still parses to `body=None`, so the writer does not start emitting empty wrappers.
- Trade (X93–X97) was audited for the same pattern and has none — it reads a flat `<OrderItem>` list with no wrapper nesting. `BillElement` in the cost parser looks like the pattern but is a boolean flag, and is correctly read with `_find`.
- New tests in `tests/test_qty_sibling_itemlists.py` and `tests/test_body_wrapper_tolerance.py` cover both hierarchies across wrapper-less, single-wrapper, and multi-wrapper shapes.

## [1.16.1] - 2026-08-13

### Fixed

- **A BoQ whose items sit directly under `BoQBody` parsed to zero items** ([#27](https://github.com/frameIQ/pygaeb/issues/27)). The GAEB schema allows an `Itemlist` as a direct child of `BoQBody`, without a `BoQCtgy` wrapper, but `_parse_boq_body` only iterated `BoQCtgy` children — so those files parsed "successfully" into an empty BoQ and every item was silently dropped, taking totals, tree, Excel export, and the writer with them. Reported against a real tender corpus (1 of 3 sampled DA XML 3.2 files). The body now also reads loose `Itemlist`/`Item`/`MarkupItem` children, using the same logic `_parse_ctgy` already applied one level down. Loose items are wrapped in an anonymous `BoQCtgy` so consumers keep a single `body.categories` traversal, and the writer unwraps it again rather than inventing a category level the source never had — matching what `_add_qty_boq_body` already did on the quantity side.
- **A DA XML 3.2 breakdown declaring a single level was read as the 3.3 format.** `BoQInfo` chose the breakdown parser by *counting* `BoQBkdn` elements, so a lone 3.2 `<BoQBkdn><Type>Item</Type><Length>4</Length></BoQBkdn>` fell through to the 3.3 branch, which read its `<Type>`/`<Length>` children as level definitions. The result was junk levels of length 0, no Item level, a spurious `expected exactly 1 Item level, found 0` warning, and — because `BoQBkdn` lengths drive OZ segmentation — wrong OZ resolution. Detection is now by shape: 3.2 spells a level as `Type`/`Length` children, 3.3 as `<Item Length="4"/>`. Breakdown shapes that already parsed correctly are unchanged.
- **Only the first `BoQBkdn` element was read in the 3.3 branch.** DA XML 2.x translates each `<LVGliederung>` into its own `<BoQBkdn>`, so a 2.x file that split its levels across sibling elements lost all but the first. All elements are now read. `V2Parser` inherits this path, so 2.0/2.1 files are affected alongside 3.x.
- New regression tests (`tests/test_bare_itemlist_issue27.py`) cover both defects, the reporter's verbatim file, the DA XML 2.x German equivalent, and writer round-trip shape — asserting that a bare `Itemlist` does not gain a category on write and that a real category still keeps one.

## [1.16.0] - 2026-07-22

### Fixed

- **Position type lost on write — a €50,000 bid could export as €121,000.** `_add_item` never serialized `Item.item_type`, so every Bedarfs-/Alternativ-/Zuschlags-/Textposition was written as a Normalposition and its price silently joined the sum on re-read. The writer now emits the position-type marker (real `<Provis>` for Bedarfsposition/Eventual, real `<LumpSumItem>` for Pauschalposition; other non-standard types via a pyGAEB-internal marker **with a warning** that it is not yet interoperable). Blast radius was every written phase — X84 bid export, X86 contract, X83 tender issue.
- **Parser read no real GAEB position-type markers.** `_detect_item_type` recognised only pyGAEB-internal names (`<AlternativeItem/>`, `<ContingencyItem/>`, `<ItemTag>…`) that no real exporter emits, so a genuine tender's `<Provis>` Bedarfspositionen were mis-read as Normal on import. It now reads the real `tgItem` markers (`<Provis>`, `<LumpSumItem>`, …) **in addition to** the legacy synthetic forms. Parser and writer now share one mapping table (`pygaeb/models/position_types.py`, documented in `docs/reference/position-types.md`) so they cannot drift again.
- **`qty_splits` never serialized** — the partial-quantity breakdown (`QtySplit`) parsed into `Item.qty_splits` was dropped on write. Now round-trips symmetrically.
- **Long text corrupted and compounded on round trip.** The parser stored the wrapping `<LongText>` tag inside `raw_html` and the writer re-wrapped it, nesting one layer deeper each round trip; plaintext long texts (no `raw_html`) were dropped entirely. The parser now stores inner content only, the writer wraps exactly once and falls back to `plain_text`/`paragraphs`, so long text is stable across repeated round trips.
- New field-level round-trip tests (`tests/test_position_type_roundtrip.py`) assert per-item `item_type`, sum inclusion, `qty_splits`, and long-text stability — the pre-existing round-trip test asserted only item *count* and passed while all four defects fired.

## [1.15.0] - 2026-07-17

### Added

- **MCP server** — `pip install pyGAEB[mcp]` and `pygaeb-mcp --root ~/tenders` exposes GAEB documents to any [Model Context Protocol](https://modelcontextprotocol.io) client (ChatGPT, Gemini, Claude, Copilot, Cursor, …). MCP is a vendor-neutral standard stewarded by the Agentic AI Foundation; the server calls no model itself and adds no provider dependency or API key. It runs as a local subprocess over stdio — there is nothing to host.
- **Nine read tools** — `open_document`, `list_structure`, `list_items`, `get_item`, `get_item_long_text`, `search_items`, `list_validation_issues`, `compare_documents`, `analyze_bids`. Two more (`export_document`, `convert_document`) are registered only under `--allow-write`, which also requires `--output-dir`.
- **Context-safety contract** — a GAEB tender serialized whole is megabytes, so the tool surface is query-oriented rather than dump-oriented. Attachment bytes, `raw_data`, and whole-document JSON are structurally unreachable; `short_text` (120 chars), `long_text_preview` (500), and validation messages (200) are clipped with their true lengths reported; every list is paginated with `total_matched` and `has_more`; and responses are capped at `PYGAEB_MCP_MAX_RESPONSE_CHARS` (default 20 000). `list_items(sort="total_desc", limit=20)` answers "where is the money?" on a 5 000-item tender in ~2 KB.
- **VOB/A-conform sums** — `list_items.sum_of_matched_totals` follows the library's `ItemType.affects_total` convention: alternative and eventual positions are excluded, matching `grand_total`, and each item row carries an `affects_total` field so a model can see which prices count toward the contract value.
- **Event-loop safety** — the heavy tools (`open_document`, `search_items`, `compare_documents`, `analyze_bids`, and both write tools) are async and run their expensive work in a worker thread via `asyncio.to_thread`, so parsing a 50 MB file cannot stall protocol heartbeats or, over HTTP, other sessions. Diff results are cached per document pair, so paging through `compare_documents` never re-runs the diff engine.
- **MCP tool annotations** — every tool declares `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`, so clients can skip confirmation prompts for the nine read-only tools and confirm only the write tools.
- **Document handles** — `open_document` parses once and returns a handle derived from path, mtime, size, and validation mode. Re-opening an unchanged file is free and returns the same handle; a changed file yields a new one, so stale reads are impossible. The LRU cache is bounded by both document count and total megabytes.
- **Filesystem safety** — `open_document` is the only path-taking read tool. Paths are resolved before the roots-containment check (so symlink escapes are caught), checked against a GAEB extension allowlist, and size-checked before any bytes are read. Writes are off by default.
- **Three MCP prompts** — `tender_review`, `compare_tenders`, `bid_evaluation`.
- New settings: `mcp_roots`, `mcp_allow_write`, `mcp_output_dir`, `mcp_max_open_documents`, `mcp_max_cache_mb`, `mcp_max_page_size`, `mcp_max_response_chars` (all `PYGAEB_MCP_*`).
- New export: `create_server` (top-level lazy import). Only `pygaeb.mcp.server` imports the MCP SDK, and that import is function-local — so `import pygaeb` never pulls it in, and the tool surface is unit-testable without it.
- 79 new tests covering path safety, handle derivation and eviction, every tool, cross-kind tolerance, VOB-conform summation, event-loop safety, tool annotations, write gating, the import guard, and the context-budget contract. Total test count: 1152.

### Changed

- **Dropped Python 3.9 support**; `requires-python` is now `>=3.10`. Python 3.9 reached end of life in October 2025, and the MCP SDK requires 3.10+. The `eval_type_backport` dependency (3.9-only) has been removed, and the CI matrix, ruff target, and mypy target now start at 3.10.
- **Modernised dependency floors** (`lxml>=5.0`, `pydantic-settings>=2.5`, `litellm>=1.61`, `click>=8.1`). These were stale enough that a fresh install pulled transitive dependencies flagged by security scanners. pyGAEB itself is not affected by the advisories against those older versions — see the new [SECURITY.md](SECURITY.md) for the per-CVE non-exposure rationale (lxml's XXE is in the default parser pyGAEB never uses; litellm's CVEs are all in its proxy server, which pyGAEB doesn't run).

### Security

- **Added [SECURITY.md](SECURITY.md)** — disclosure process, threat model, hardening summary, and a dependency non-exposure table for the notable litellm / lxml / pydantic-settings advisories.
- **MCP server input hardening** — `list_items` price filters now reject non-finite values (`NaN`/`±inf`) with a clear error instead of letting `NaN` poison downstream `Decimal` comparisons.
- **MCP HTTP transport warning** — the guide now states explicitly that `sse`/`streamable-http` carry no authentication and must not be exposed to untrusted networks.

### Fixed

- **`AwardInfo.description` type error under Python 3.10+** — `lxml`'s `itertext()` is typed `Iterator[str | bytes]`, so joining it directly failed strict type checking. Now uses the same `str(t)` coercion idiom as `_text` elsewhere in the parser.
- **Stale README badges** — the version badge still read 1.14.0 after the 1.14.1 release; both READMEs now track the current version and the 3.10+ floor.

## [1.14.1] - 2026-07-08

### Fixed

- **Writer emitted the default namespace twice** — the `<GAEB>` root element carried `xmlns` both via lxml `nsmap` and as a literal attribute, producing malformed XML (`Attribute xmlns redefined`). Strict parsers rejected written files outright; recover-mode parsers silently truncated them. The declaration is now written exactly once. Applies to all document kinds (procurement, trade, cost).
- **Writer nested one `BoQBody` per subcategory** — per the GAEB DA XML schema a `BoQCtgy` contains a single `BoQBody` holding all sub-`BoQCtgy` elements and the `Itemlist`. The writer previously created a separate `BoQBody` per subcategory (with `Itemlist` as a direct `BoQCtgy` child), so conforming parsers — including pyGAEB's own — read back only the first subcategory of every category. Deeply structured BoQs now round-trip completely (verified against the BVBS GAEB Muster file: 28/28 items, cross-phase validation clean).

## [1.14.0] - 2026-05-26

### Added

- **`Item.full_oz`** — New property returning the complete ordinal number (e.g. `"01.02.0004"`) by joining the ancestor category/lot chain with the item's leaf `RNoPart`. Use `Item.full_oz_with(separator)` for a custom separator. Backed by the new `Item.oz_path` field (the ancestor `RNoPart` chain, populated during parsing). For multi-lot documents the lot number prefixes the OZ; programmatically built items fall back to the bare `oz`.
- **`BoQTree.find_item()` accepts full OZ** — Lookups now resolve by either the leaf `RNoPart` (`"0004"`) or the full OZ (`"01.02.0004"`).
- **CSV export `full_oz` column** — `to_csv()` now includes a `full_oz` column alongside `oz`.

### Fixed

- **Crash parsing files with XML comments (iTWO / RIB Software)** — GAEB DA XML 3.3 exports that embed `<!-- ... -->` comments inside elements no longer raise `TypeError`. lxml reports comment and processing-instruction nodes during iteration with a callable `.tag`; the v3 parser now skips these non-element nodes in `_parse_item_attachments`, `_classify_item_type`, and `_parse_bkdn_v33` (the last of which also previously produced a spurious breakdown entry per comment). Covers DA XML 2.x as well, since the 2.x parser delegates to the same base.

## [1.12.0] - 2026-04-11

### Added

- **X88 (Nachtrag/Addendum) exchange phase** — Full support for claims and variations: enum values (`X88`, `D88`), file extension detection, parser recognition, phase-specific validation (quantity, price, description required; change order number recommended), and round-trip serialization.
- **Cross-phase validation: X86→X89 (contract→invoice)** — `CrossPhaseValidator.check()` now validates that invoice unit prices match the contract exactly, flags invented invoice items, and warns on missing executed quantities.
- **Cross-phase validation: X86→X88 (contract→addendum)** — Validates that new Nachtrag items have change order numbers (CONo) for traceability, and flags contract items modified without CONo.
- **Totals validation** — New `validate_totals()` checks XML-declared totals against computed subtotals at BoQ, lot, and category levels. Also detects when alternative/eventual items are incorrectly included in totals (VOB/A compliance).
- **GAEB precision limit validation** — `validate_numerics()` now enforces GAEB Fachdokumentation limits: unit price max 10 pre-decimal digits, total price max 11, quantity max 8 pre-decimal / 3 decimal places, and max 6 unit price components per item.
- **Writer `up_frac_dig` support** — `GAEBWriter` now formats unit prices to the correct number of decimal places when `UPFracDig` is set in the document's `PrjInfo` (e.g., 3 decimals when `UPFracDig=3`).
- **Explicit cross-phase methods** — `CrossPhaseValidator.check_tender_bid()`, `.check_contract_invoice()`, and `.check_contract_addendum()` for direct invocation without auto-dispatch.
- 92 new tests covering all gap fixes and coverage improvements across classifier, extractor, version compat, detector, and validation modules. Total test count: 927.

### Fixed

- **X80 phase validation false positives** — X80 (BoQ Catalogue) no longer incorrectly warns about missing quantities. X80 is a reusable item library without quantities or prices per the GAEB standard.
- **README version badge** — Updated from 1.7.0 to 1.11.0 (both English and German).

### Security

- **SQLiteCache file permissions** — Database files are now created with `0o600` permissions and cache directories with `0o700`, restricting access to the owning user. Classification results may contain business-sensitive construction data.

## [1.11.0] - 2026-03-24

### Added

- **Excel Export** — `to_excel()` exports any GAEB document to a structured Excel workbook (.xlsx) with hierarchy-aware layout and phase-specific columns.
- **Two export modes** — `mode="structured"` for a single hierarchy-aware sheet; `mode="full"` for a multi-sheet workbook (BoQ + Items + Summary + Info).
- **All document kinds** — Procurement (X80-X89), Trade (X93-X97), Cost (X50-X52), and Quantity Determination (X31) each get phase-appropriate columns.
- **Optional columns** — `include_long_text`, `include_classification`, and `include_bim_guid` flags add extra columns on demand.
- **Minimal formatting** — Bold headers, frozen panes, auto column widths, currency/quantity number formatting, bold subtotals.
- Optional dependency: `openpyxl` via `pip install pyGAEB[excel]`.
- New export: `to_excel` (top-level lazy import and via `pygaeb.convert`).
- 34 new tests covering all 4 phases, both modes, column flags, formatting, and edge cases.

## [1.10.0] - 2026-03-24

### Added

- **BoQ Builder API** — `BoQBuilder` provides programmatic construction of GAEB documents from scratch with a fluent, explicit-object API.
- **Auto OZ generation** — Ordinal numbers auto-generated from category `rno` + sequence (10, 20, 30...) when `oz` is omitted. Explicit OZ overrides supported.
- **Decimal convenience** — `int`, `float`, and `str` values auto-converted to `Decimal` for `qty`, `unit_price`, and `total_price`. Auto-computes `total_price` when missing.
- **Field name validation** — Unknown kwargs raise `ValueError` with `difflib` suggestions for likely typos (e.g., `'unit_prce'` → `Did you mean: 'unit_price'?`).
- **Phase-aware rules** — Warns or errors (strict mode) when items violate exchange phase semantics (e.g., prices in X80 blank BoQ, missing prices in X83 tender).
- **Version compatibility checks** — Detects fields incompatible with the target DA XML version (e.g., `bim_guid` in DA XML < 3.3) with warnings or strict errors.
- **Duplicate OZ detection** — Catches duplicate ordinal numbers within a lot at build time.
- **Auto totals & BoQBkdn** — Lot subtotals computed from item prices; breakdown structure inferred from hierarchy depth.
- **Implicit lot shortcut** — `builder.add_category()` creates a single implicit lot for simple documents.
- **ItemHandle** — Fluent post-construction for long text (`.set_long_text()`) and attachments (`.add_attachment()`).
- **Optional XSD validation** — `build(xsd_dir=...)` serializes to XML in memory and validates against official GAEB XSD schemas.
- **Full writer compatibility** — Built documents work directly with `GAEBWriter.write()` and `GAEBWriter.to_bytes()`.
- New export: `BoQBuilder` (top-level lazy import).
- 46 new tests covering basic construction, multi-lot, nested categories, auto OZ, Decimal conversion, field validation, typo detection, phase rules, version compatibility, strict mode, duplicate OZ, auto totals, round-trip serialization, and edge cases.

## [1.9.0] - 2026-03-24

### Added

- **Document Diff Engine** — `BoQDiff.compare(doc_a, doc_b)` performs a deterministic, field-by-field comparison of two GAEB procurement documents with structured results.
- **OZ-based item matching** — Lot-aware matching by OZ (ordinal number) with global fallback for items that moved between lots.
- **Field-level change detection** — Each changed field carries a `Significance` level (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`) based on construction context impact.
- **Structural diff** — Detects added, removed, and renamed sections (categories), as well as items that moved between categories or lots.
- **`DiffMode`** enum — `DEFAULT` (warnings for mismatched projects), `STRICT` (raises `ValueError`), `FORCE` (suppresses warnings).
- **`DiffResult`** Pydantic model — Complete comparison output with `summary`, `items`, `structure`, `metadata`, and `warnings` sections. Fully serializable to JSON.
- **Financial impact** — Automatic computation of net financial impact (`grand_total_b - grand_total_a`).
- **Match ratio & compatibility warnings** — Low match ratio detection, different project warnings, currency mismatch alerts, version difference notices.
- **Result filtering** — `ItemModified.filter_changes(min_significance)` and `ItemDiffSummary.filter_modified(min_significance)` for targeted reporting.
- New exports: `BoQDiff`, `DiffMode`, `DiffResult`, `DiffSummary`, `DiffDocInfo`, `Significance`, `FieldChange`, `ItemAdded`, `ItemRemoved`, `ItemModified`, `ItemMoved`, `ItemDiffSummary`, `MetadataChange`, `SectionChange`, `SectionRenamed`, `StructureDiffSummary`.
- 53 new tests covering item matching, field comparison, structural diff, integration, models, lazy imports, and edge cases.

## [1.8.0] - 2026-03-24

### Added

- **Read-only BoQ Tree API** — `BoQTree` adapter wraps an existing `BoQ` and builds a navigable node graph with parent references, depth tracking, and indexed lookups. The underlying Pydantic models are not modified.
- **`BoQNode`** — Lightweight tree node with O(1) `parent`, `children`, `depth`, `index`, `siblings`, `ancestors`, `path`, `next_sibling`, `prev_sibling`, `is_leaf`, `is_root` properties.
- **Type-safe model accessors** — `node.boq`, `node.lot`, `node.category`, `node.item` raise `TypeError` if accessed on the wrong node kind.
- **Unified convenience properties** — `node.label`, `node.rno`, `node.label_path` work across all node kinds (root, lot, category, item).
- **Subtree queries** — `node.iter_descendants()`, `node.iter_items()`, `node.iter_categories()`, `node.find(predicate)`, `node.find_all(predicate)`.
- **`BoQTree` lookups** — `tree.find_item(oz)` (O(1) via index), `tree.find_category(rno)`, `tree.find_all_categories(rno)`.
- **Tree traversal** — `tree.walk()` (depth-first) and `tree.walk_bfs()` (breadth-first) over all nodes.
- **`NodeKind`** enum — `ROOT`, `LOT`, `CATEGORY`, `ITEM` discriminator for node types.
- New exports: `BoQTree`, `BoQNode`, `NodeKind`.
- 87 new tests covering tree navigation, lookups, iteration, and multi-lot documents.

## [1.7.1] - 2026-03-15

### Fixed

- **Procurement long text parsing** — Items in DA XML 3.x procurement files (X80–X89) now correctly extract long text from the `<Description>/<CompleteText>/<DetailTxt>` structure.
- **OWN (owner/client) parsed from wrong element** — `<OWN>` is now correctly located as a child of `<Award>` instead of `<AwardInfo>`, producing a full `Address` with all `tgAddress` fields.

### Added

- **AwardInfo metadata** — 13 new fields on `AwardInfo`: `category`, `open_date`, `open_time`, `eval_end`, `submit_location`, `construction_start`, `construction_end`, `contract_no`, `contract_date`, `accept_type`, `warranty_duration`, `warranty_unit`, and `award_no`.
- **`AwardInfo.owner_address`** — Full `Address` model for the `<OWN>/<Address>` structure.
- **`Address` model extended to match `tgAddress` XSD** — Added `name3`, `name4`, `contact`, `iln`, and `vat_id` fields.
- **`_parse_address` consolidated** — Moved into `BaseV3Parser` so all phases share XSD-complete address parsing.
- Writer, German element map, and 48 new tests updated accordingly.

## [1.0.0] - 2026-03-14

### Added

- Unified domain model (GAEBDocument, Item, BoQ, AwardInfo) with Pydantic v2
- Format & version detection for DA XML 2.0–3.3
- Pre-parse encoding repair via ftfy + charset-normalizer
- Malformed XML recovery with two-pass strategy
- DA XML 3.x parser (3.0, 3.1, 3.2, 3.3)
- DA XML 2.x parser (2.0, 2.1) via German element mapping
- OZ resolver with BoQBkdn hierarchy breakdown
- Rich text parser for tgBoQText long texts (BeautifulSoup4 + lxml)
- Structural, item, numeric, and phase validation
- Cross-phase validation (source ↔ response compatibility)
- LLM classification via LiteLLM (100+ providers) + instructor (structured output)
- Async batch classifier with SQLite cache, deduplication, cost preview
- Sync convenience wrapper for classification
- Model fallback chains
- Progress reporting callbacks
- Manual override support with cache persistence
- Prompt versioning (v1)
- GAEB XML writer with round-trip support
- JSON and CSV export
- Multi-lot document navigation
- Configuration via pydantic-settings (env vars / .env)
- Comprehensive validation with lenient (default) and strict modes
