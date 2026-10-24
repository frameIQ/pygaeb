"""An LV as a list of blocks, shared by the document exports (PDF, Word, HTML, Markdown).

The walk applies the print rules once: which headings and sums appear, the
"Nur Einh.-Preis" rule, markup rates, and number formats per locale.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from pygaeb.models.boq import BoQCtgy, Lot
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ItemType, Provis
from pygaeb.models.item import Item

logger = logging.getLogger("pygaeb.convert")

_MAX_DEPTH = 50
_TOTAL_FIELDS = ("total_price", "line_total", "item_total")  # procurement, trade, cost
_DE_SEPARATORS = str.maketrans({",": ".", ".": ","})

LABELS: dict[str, dict[str, str]] = {
    "de": {
        "oz": "OZ",
        "text": "Leistungsbeschreibung",
        "qty": "Menge",
        "unit": "ME",
        "unit_price": "EP",
        "total": "GB",
        "rate": "Zuschlag",
        "lot": "Los",
        "subtotal": "Summe",
        "grand_total": "Gesamtsumme",
        "carry_forward": "Übertrag",
        "unit_price_only": "Nur Einh.-Preis",
        "page": "Seite",
        "project": "Projekt",
        "phase": "Phase",
        "items": "Positionen",
    },
    "en": {
        "oz": "OZ",
        "text": "Description",
        "qty": "Qty",
        "unit": "Unit",
        "unit_price": "Unit price",
        "total": "Total",
        "rate": "Markup",
        "lot": "Lot",
        "subtotal": "Total",
        "grand_total": "Grand total",
        "carry_forward": "Carried forward",
        "unit_price_only": "Unit price only",
        "page": "Page",
        "project": "Project",
        "phase": "Phase",
        "items": "Items",
    },
}

_TYPE_LABELS: dict[str, dict[ItemType, str]] = {
    "de": {
        ItemType.LUMP_SUM: "Pauschalposition",
        ItemType.ALTERNATIVE: "Alternativposition",
        ItemType.EVENTUAL: "Bedarfsposition",
        ItemType.TEXT_ONLY: "Textposition",
        ItemType.BASE_SURCHARGE: "Grundposition",
        ItemType.INDEX: "Indexposition",
        ItemType.SUPPLEMENT: "Zulageposition",
        ItemType.MARKUP: "Zuschlagsposition",
    },
    "en": {
        ItemType.LUMP_SUM: "Lump-sum item",
        ItemType.ALTERNATIVE: "Alternative item",
        ItemType.EVENTUAL: "Optional item",
        ItemType.TEXT_ONLY: "Text item",
        ItemType.BASE_SURCHARGE: "Base item",
        ItemType.INDEX: "Index item",
        ItemType.SUPPLEMENT: "Supplement item",
        ItemType.MARKUP: "Markup item",
    },
}

_PROVIS_LABELS: dict[str, dict[Provis, str]] = {
    "de": {Provis.WITH_TOTAL: "mit GB", Provis.WITHOUT_TOTAL: "ohne GB"},
    "en": {Provis.WITH_TOTAL: "total included", Provis.WITHOUT_TOTAL: "total not included"},
}


def check_locale(locale: str) -> None:
    if locale not in LABELS:
        raise ValueError(f"Unsupported locale {locale!r}; use 'de' or 'en'.")


def number(value: Decimal, min_places: int, locale: str) -> str:
    """Format without rounding away digits the document carries."""
    exponent = value.as_tuple().exponent
    places = max(min_places, -exponent) if isinstance(exponent, int) else min_places
    text = f"{value:,.{places}f}"
    return text.translate(_DE_SEPARATORS) if locale == "de" else text


@dataclass(frozen=True)
class Heading:
    """A lot or category heading. ``depth`` counts the visible nesting, from 0."""

    kind: Literal["lot", "category"]
    number: str
    label: str
    depth: int
    lot: Lot | None = None
    category: BoQCtgy | None = None


@dataclass(frozen=True)
class Position:
    """An item with its printed values, already formatted for the locale."""

    number: str
    short_text: str
    long_text: str
    marker: str | None
    qty: str | None
    unit: str | None
    unit_price: str | None
    total: str | None
    #: ``unit_price`` holds a markup's rate (``10,00 %``), not money.
    rate: bool = False
    #: ``total`` holds the "Nur Einh.-Preis" label instead of an amount.
    unit_price_only: bool = False
    #: What this position adds to the running total, when it is summed.
    amount: Decimal | None = None
    depth: int = 0
    item: BaseModel | None = None
    category: BoQCtgy | None = None
    lot: Lot | None = None


@dataclass(frozen=True)
class Total:
    """A category or lot subtotal, or the grand total."""

    kind: Literal["subtotal", "lot_subtotal", "grand_total"]
    label: str
    amount: str
    depth: int = 0
    lot: Lot | None = None
    category: BoQCtgy | None = None


Block = Heading | Position | Total


@dataclass(frozen=True)
class Lv:
    """Everything a document export prints, in order."""

    title: str
    meta: list[str]
    version: str
    priced: bool
    labels: dict[str, str]
    blocks: list[Block] = field(default_factory=list)


def _first(obj: Any, *names: str) -> Any:
    """The first attribute that is set; document kinds name the same field differently."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None and value != "":
            return value
    return None


def _marker(item: Item, locale: str) -> str | None:
    label = _TYPE_LABELS[locale].get(item.item_type)
    if label is not None and item.item_type is ItemType.EVENTUAL and item.provis is not None:
        return f"{label} {_PROVIS_LABELS[locale][item.provis]}"
    return label


class _Walk:
    def __init__(self, locale: str, priced: bool) -> None:
        self.locale = locale
        self.labels = LABELS[locale]
        self.priced = priced
        self.blocks: list[Block] = []

    def money(self, value: Decimal) -> str:
        return number(value, 2, self.locale)

    def position(self, item: Item, depth: int, category: BoQCtgy | None, lot: Lot) -> None:
        unit_price: str | None = None
        total: str | None = None
        amount: Decimal | None = None
        rate = only = False
        if item.item_type is ItemType.MARKUP:
            # A markup's unit_price is its percentage, not money; total_price is its amount.
            if item.unit_price is not None:
                unit_price, rate = f"{self.money(item.unit_price)} %", True
            if item.total_price is not None:
                total, amount = self.money(item.total_price), item.total_price
        else:
            if item.unit_price is not None:
                unit_price = self.money(item.unit_price)
            if not item.affects_total:
                # Priced but not summed (Bedarfs- ohne GB, Alternativpositionen).
                if item.unit_price is not None:
                    total, only = self.labels["unit_price_only"], True
            elif item.total_price is not None:
                total, amount = self.money(item.total_price), item.total_price
        self.blocks.append(Position(
            number=item.full_oz,
            short_text=item.short_text,
            long_text=item.long_text_plain.strip(),
            marker=_marker(item, self.locale),
            qty=number(item.qty, 3, self.locale) if item.qty is not None else None,
            unit=item.unit or None,
            unit_price=unit_price,
            total=total,
            rate=rate,
            unit_price_only=only,
            amount=amount,
            depth=depth,
            item=item,
            category=category,
            lot=lot,
        ))

    def category(self, ctgy: BoQCtgy, path: list[str], lot: Lot, depth: int, level: int) -> None:
        if level > _MAX_DEPTH:
            logger.warning("Categories nested deeper than %d levels are not printed", _MAX_DEPTH)
            return
        number_ = ".".join(part for part in path if part)
        # Loose items arrive wrapped in a nameless category; it prints no heading or subtotal.
        named = bool(ctgy.rno or ctgy.label)
        if named:
            self.blocks.append(Heading("category", number_, ctgy.label, depth, lot, ctgy))
        inner = depth + 1 if named else depth
        for item in ctgy.items:
            self.position(item, inner, ctgy, lot)
        for sub in ctgy.subcategories:
            self.category(sub, [*path, sub.rno], lot, inner, level + 1)
        if named and self.priced:
            label = " ".join(p for p in (self.labels["subtotal"], number_, ctgy.label) if p)
            amount = self.money(ctgy.subtotal)
            self.blocks.append(Total("subtotal", label, amount, depth, lot, ctgy))

    def boq(self, doc: GAEBDocument) -> None:
        boq = doc.award.boq
        lot_word = self.labels["lot"]
        for lot in boq.lots:
            shown = not lot.synthetic
            if shown:
                lot_number = f"{lot_word} {lot.rno}".strip()
                self.blocks.append(Heading("lot", lot_number, lot.label, 0, lot))
            for ctgy in lot.body.categories:
                self.category(ctgy, [ctgy.rno], lot, 1 if shown else 0, 1)
            if self.priced and boq.is_multi_lot and shown:
                parts = (self.labels["subtotal"], lot_word, lot.rno, lot.label)
                label = " ".join(p for p in parts if p)
                self.blocks.append(Total("lot_subtotal", label, self.money(lot.subtotal), 0, lot))
        if self.priced:
            self.grand_total(doc)

    def flat(self, doc: GAEBDocument) -> None:
        for item in doc.iter_items():
            qty = getattr(item, "qty", None)
            unit = getattr(item, "unit", None)
            unit_price = _first(item, "unit_price", "net_price", "offer_price")
            total = _first(item, *_TOTAL_FIELDS)
            self.blocks.append(Position(
                number=str(_first(item, "full_oz", "oz", "art_no", "ele_no", "item_id") or ""),
                short_text=str(getattr(item, "short_text", "") or ""),
                long_text=str(getattr(item, "long_text_plain", "") or "").strip(),
                marker=None,
                qty=number(qty, 3, self.locale) if qty is not None else None,
                unit=str(unit) if unit else None,
                unit_price=self.money(unit_price) if unit_price is not None else None,
                total=self.money(total) if total is not None else None,
                amount=total,
                item=item,
            ))
        if self.priced:
            self.grand_total(doc)

    def grand_total(self, doc: GAEBDocument) -> None:
        label = self.labels["grand_total"]
        self.blocks.append(Total("grand_total", label, self.money(doc.grand_total)))


def build_lv(doc: GAEBDocument, locale: str, title: str | None = None) -> Lv:
    """Walk ``doc`` into the blocks every document export prints."""
    check_locale(locale)
    labels = LABELS[locale]
    procurement = doc.is_procurement
    items = list(doc.award.boq.iter_items()) if procurement else list(doc.iter_items())
    priced = any(_first(item, *_TOTAL_FIELDS) is not None for item in items)

    doc_title = title or (doc.award.project_name if procurement else None) or "GAEB"
    version = f"{doc.exchange_phase.value} · DA XML {doc.source_version.value}"
    meta: list[str] = []
    if procurement and doc.award.project_no:
        meta.append(f"{labels['project']}: {doc.award.project_no}")
    meta.append(f"{labels['phase']}: {version}")
    meta.append(f"{labels['items']}: {len(items)}")
    if priced:
        total = number(doc.grand_total, 2, locale)
        currency = f" {doc.award.currency}" if procurement and doc.award.currency else ""
        meta.append(f"{labels['subtotal']}: {total}{currency}")

    walk = _Walk(locale, priced)
    if procurement:
        walk.boq(doc)
    else:
        walk.flat(doc)
    return Lv(doc_title, meta, version, priced, labels, walk.blocks)
