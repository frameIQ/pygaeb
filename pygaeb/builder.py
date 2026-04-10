"""Programmatic BoQ construction API for building GAEB documents from scratch.

Usage::

    from pygaeb import BoQBuilder

    builder = BoQBuilder(phase="X83", version="3.3")
    builder.project(no="PRJ-001", name="School Renovation", currency="EUR")

    lot = builder.add_lot("1", "Structural Work")
    concrete = lot.add_category("01", "Concrete")
    concrete.add_item("01.0010", "Foundation", qty=120, unit="m3", unit_price=85)

    doc = builder.build()
"""

from __future__ import annotations

import difflib
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pygaeb.models.boq import BoQ, BoQBkdn, BoQBody, BoQCtgy, BoQInfo, Lot, Totals
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import (
    BkdnType,
    ExchangePhase,
    ItemType,
    SourceVersion,
)
from pygaeb.models.item import Attachment, Item, RichText
from pygaeb.writer.version_registry import VERSION_REGISTRY

_ITEM_FIELDS = set(Item.model_fields.keys())
_CTGY_FIELDS = set(BoQCtgy.model_fields.keys())
_LOT_FIELDS = set(Lot.model_fields.keys())
_AWARD_FIELDS = set(AwardInfo.model_fields.keys())

_PHASE_RULES: dict[str, dict[str, Any]] = {
    "X80": {"warn_if_present": {"unit_price", "total_price"}, "label": "blank BoQ"},
    "X83": {"warn_if_missing": {"unit_price"}, "label": "tender with prices"},
    "X84": {"warn_if_missing": {"unit_price"}, "label": "award"},
    "X88": {"warn_if_missing": {"unit_price", "change_order_number"}, "label": "addendum/Nachtrag"},
}

_VERSION_COMPAT: dict[str, dict[str, Any]] = {
    "bim_guid": {"min_version": "3.3"},
    "attachments": {"min_version": "3.3"},
    "change_order_number": {"min_version": "3.1"},
    "cost_approaches": {"phases": {"X50", "X51", "X52"}},
    "markup_type": {"phases": {"X52"}},
    "markup_sub_qtys": {"phases": {"X52"}},
    "up_components": {"min_version": "3.0"},
    "discount_pct": {"min_version": "3.0"},
    "ctlg_assigns": {"min_version": "3.1"},
}

_VERSION_ORDER = ["2.0", "2.1", "3.0", "3.1", "3.2", "3.3"]


def _to_decimal(value: int | float | Decimal | str | None) -> Decimal | None:
    """Convert a numeric value to Decimal, or return None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Cannot convert {value!r} to Decimal") from None


def _validate_kwargs(kwargs: dict[str, Any], valid_fields: set[str], model_name: str) -> None:
    """Check all kwargs are known fields; raise ValueError with suggestions for typos."""
    unknown = set(kwargs.keys()) - valid_fields
    if not unknown:
        return
    messages: list[str] = []
    for field_name in sorted(unknown):
        suggestions = difflib.get_close_matches(field_name, valid_fields, n=3, cutoff=0.5)
        if suggestions:
            messages.append(
                f"Unknown {model_name} field {field_name!r}. "
                f"Did you mean: {', '.join(repr(s) for s in suggestions)}?"
            )
        else:
            messages.append(f"Unknown {model_name} field {field_name!r}.")
    raise ValueError(" ".join(messages))


class ItemHandle:
    """Handle returned by ``CategoryBuilder.add_item()`` for fluent post-construction."""

    __slots__ = ("_item",)

    def __init__(self, item: Item) -> None:
        self._item = item

    @property
    def item(self) -> Item:
        return self._item

    def set_long_text(self, text: str) -> ItemHandle:
        """Set the item's long text from a plain string."""
        self._item.long_text = RichText.from_plain(text)
        return self

    def add_attachment(
        self, filename: str, data: bytes, mime_type: str = "application/octet-stream"
    ) -> ItemHandle:
        """Add a binary attachment to the item."""
        self._item.attachments.append(
            Attachment(filename=filename, data=data, mime_type=mime_type)
        )
        return self


class CategoryBuilder:
    """Builder for a single BoQ category (section), returned by ``LotBuilder.add_category()``."""

    __slots__ = ("_items", "_kwargs", "_label", "_rno", "_seq", "_subcategories")

    def __init__(self, rno: str, label: str, **kwargs: Any) -> None:
        _validate_kwargs(
            kwargs, _CTGY_FIELDS - {"rno", "label", "items", "subcategories"}, "BoQCtgy"
        )
        self._rno = rno
        self._label = label
        self._items: list[Item] = []
        self._subcategories: list[CategoryBuilder] = []
        self._seq = 0
        self._kwargs = kwargs

    def add_item(
        self,
        oz: str | None = None,
        short_text: str = "",
        *,
        qty: int | float | Decimal | None = None,
        unit: str | None = None,
        unit_price: int | float | Decimal | None = None,
        total_price: int | float | Decimal | None = None,
        item_type: ItemType = ItemType.NORMAL,
        **kwargs: Any,
    ) -> ItemHandle:
        """Add an item to this category.

        Args:
            oz: Ordinal number. If None, auto-generated from category rno + sequence.
            short_text: Short description text.
            qty: Quantity (int/float/Decimal accepted, converted to Decimal).
            unit: Unit of measurement.
            unit_price: Unit price (int/float/Decimal accepted).
            total_price: Total price. If None and qty+unit_price are set, auto-computed.
            item_type: Item type classification.
            **kwargs: Any additional Item model field.

        Returns:
            An ItemHandle for fluent post-construction (long text, attachments).
        """
        _validate_kwargs(kwargs, _ITEM_FIELDS - {
            "oz", "short_text", "qty", "unit", "unit_price", "total_price", "item_type",
        }, "Item")

        self._seq += 1
        if oz is None:
            oz = f"{self._rno}.{self._seq * 10:04d}"

        dec_qty = _to_decimal(qty)
        dec_up = _to_decimal(unit_price)
        dec_tp = _to_decimal(total_price)

        if dec_tp is None and dec_qty is not None and dec_up is not None:
            dec_tp = (dec_qty * dec_up).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        item = Item(
            oz=oz,
            short_text=short_text,
            qty=dec_qty,
            unit=unit,
            unit_price=dec_up,
            total_price=dec_tp,
            item_type=item_type,
            **kwargs,
        )
        self._items.append(item)
        return ItemHandle(item)

    def add_subcategory(self, rno: str, label: str, **kwargs: Any) -> CategoryBuilder:
        """Add a nested subcategory within this category."""
        sub = CategoryBuilder(rno, label, **kwargs)
        self._subcategories.append(sub)
        return sub

    def _build(self) -> BoQCtgy:
        """Assemble into a BoQCtgy model."""
        subcategories = [sub._build() for sub in self._subcategories]
        return BoQCtgy(
            rno=self._rno,
            label=self._label,
            items=list(self._items),
            subcategories=subcategories,
            **self._kwargs,
        )


class LotBuilder:
    """Builder for a single lot, returned by ``BoQBuilder.add_lot()``."""

    __slots__ = ("_categories", "_kwargs", "_label", "_rno")

    def __init__(self, rno: str, label: str, **kwargs: Any) -> None:
        _validate_kwargs(kwargs, _LOT_FIELDS - {"rno", "label", "body"}, "Lot")
        self._rno = rno
        self._label = label
        self._categories: list[CategoryBuilder] = []
        self._kwargs = kwargs

    def add_category(self, rno: str, label: str, **kwargs: Any) -> CategoryBuilder:
        """Add a top-level category to this lot."""
        cat = CategoryBuilder(rno, label, **kwargs)
        self._categories.append(cat)
        return cat

    def _build(self) -> Lot:
        """Assemble into a Lot model."""
        categories = [cat._build() for cat in self._categories]
        return Lot(
            rno=self._rno,
            label=self._label,
            body=BoQBody(categories=categories),
            **self._kwargs,
        )


class BoQBuilder:
    """Programmatic builder for GAEB procurement documents.

    Constructs a ``GAEBDocument`` from scratch with field validation,
    Decimal convenience, auto OZ generation, phase-aware rules, and
    version compatibility checks.
    """

    def __init__(
        self,
        phase: str | ExchangePhase = "X83",
        version: str | SourceVersion = "3.3",
    ) -> None:
        self._phase = ExchangePhase(phase) if isinstance(phase, str) else phase
        self._version = SourceVersion(version) if isinstance(version, str) else version
        self._lots: list[LotBuilder] = []
        self._implicit_lot: LotBuilder | None = None
        self._award_kwargs: dict[str, Any] = {}

    def project(self, **kwargs: Any) -> BoQBuilder:
        """Set project-level metadata (AwardInfo fields).

        Common fields: ``no`` (project_no), ``name`` (project_name),
        ``currency``, ``client``. All AwardInfo fields accepted as kwargs.
        """
        mapped: dict[str, Any] = {}
        if "no" in kwargs:
            mapped["project_no"] = kwargs.pop("no")
        if "name" in kwargs:
            mapped["project_name"] = kwargs.pop("name")
        remaining = {**mapped, **kwargs}
        _validate_kwargs(remaining, _AWARD_FIELDS - {"boq", "source_element"}, "AwardInfo")
        self._award_kwargs.update(remaining)
        return self

    def add_lot(self, rno: str, label: str, **kwargs: Any) -> LotBuilder:
        """Add a lot to the document."""
        lot = LotBuilder(rno, label, **kwargs)
        self._lots.append(lot)
        return lot

    def add_category(self, rno: str, label: str, **kwargs: Any) -> CategoryBuilder:
        """Add a category to the implicit default lot (single-lot shortcut).

        If no lots have been added, creates an implicit lot with rno="1".
        """
        if self._lots:
            raise ValueError(
                "Cannot use add_category() after add_lot(). "
                "Add categories to a specific lot instead."
            )
        if self._implicit_lot is None:
            self._implicit_lot = LotBuilder("1", "")
        return self._implicit_lot.add_category(rno, label, **kwargs)

    def build(
        self,
        strict: bool = False,
        xsd_dir: str | None = None,
    ) -> GAEBDocument:
        """Assemble and return the GAEBDocument.

        Args:
            strict: If True, raise ValueError on phase/version incompatibilities
                    instead of adding warnings.
            xsd_dir: If provided, validate the built XML against XSD schemas.

        Returns:
            A fully constructed GAEBDocument.
        """
        lots = self._build_lots()
        boq = self._build_boq(lots)

        award = AwardInfo(boq=boq, **self._award_kwargs)

        doc = GAEBDocument(
            source_version=self._version,
            exchange_phase=self._phase,
            gaeb_info=GAEBInfo(prog_system="pyGAEB-Builder"),
            award=award,
        )

        warnings = self._run_validation(doc, strict)
        for w in warnings:
            doc.add_warning(w)

        if xsd_dir:
            self._run_xsd_validation(doc, xsd_dir)

        return doc

    def _build_lots(self) -> list[Lot]:
        if self._implicit_lot is not None:
            return [self._implicit_lot._build()]
        return [lot._build() for lot in self._lots]

    def _build_boq(self, lots: list[Lot]) -> BoQ:
        boq_info = self._infer_boq_info(lots)
        self._compute_totals(lots)
        return BoQ(boq_info=boq_info, lots=lots)

    def _infer_boq_info(self, lots: list[Lot]) -> BoQInfo:
        """Auto-detect BoQBkdn from the observed hierarchy."""
        bkdn: list[BoQBkdn] = []
        if len(lots) > 1:
            max_lot_rno = max((len(lot.rno) for lot in lots), default=2)
            bkdn.append(BoQBkdn(bkdn_type=BkdnType.LOT, length=max_lot_rno))

        max_ctgy_depth, max_ctgy_len, max_item_len = self._measure_hierarchy(lots)
        for _ in range(max(max_ctgy_depth, 1)):
            bkdn.append(BoQBkdn(bkdn_type=BkdnType.BOQ_LEVEL, length=max_ctgy_len or 2))

        if max_item_len:
            bkdn.append(BoQBkdn(bkdn_type=BkdnType.ITEM, length=max_item_len))

        return BoQInfo(bkdn=bkdn)

    @staticmethod
    def _measure_hierarchy(lots: list[Lot]) -> tuple[int, int, int]:
        """Measure max category depth, max rno length, max item OZ segment length."""
        max_depth = 0
        max_ctgy_len = 0
        max_item_len = 0

        def _walk_ctgy(ctgy: BoQCtgy, depth: int) -> None:
            nonlocal max_depth, max_ctgy_len, max_item_len
            max_depth = max(max_depth, depth)
            max_ctgy_len = max(max_ctgy_len, len(ctgy.rno))
            for item in ctgy.items:
                parts = item.oz.rsplit(".", 1)
                max_item_len = max(max_item_len, len(parts[-1]) if parts else 4)
            for sub in ctgy.subcategories:
                _walk_ctgy(sub, depth + 1)

        for lot in lots:
            for ctgy in lot.body.categories:
                _walk_ctgy(ctgy, 1)

        return max_depth, max_ctgy_len, max_item_len

    @staticmethod
    def _compute_totals(lots: list[Lot]) -> None:
        """Auto-compute subtotals for each lot."""
        for lot in lots:
            lot_total = Decimal("0")
            for ctgy in lot.body.categories:
                lot_total += ctgy.subtotal
            lot.totals = Totals(total=lot_total)

    def _run_validation(self, doc: GAEBDocument, strict: bool) -> list[str]:
        """Run phase-aware and version compatibility checks."""
        warnings: list[str] = []

        self._check_duplicate_oz(doc, warnings, strict)
        self._check_phase_rules(doc, warnings, strict)
        self._check_version_compat(doc, warnings, strict)

        return warnings

    @staticmethod
    def _check_duplicate_oz(doc: GAEBDocument, warnings: list[str], strict: bool) -> None:
        """Check for duplicate OZ within each lot."""
        for lot in doc.award.boq.lots:
            seen: dict[str, int] = {}
            for item in lot.iter_items():
                seen[item.oz] = seen.get(item.oz, 0) + 1
            duplicates = {oz: count for oz, count in seen.items() if count > 1}
            if duplicates:
                msg = (
                    f"Lot {lot.rno!r}: duplicate OZ numbers: "
                    + ", ".join(f"{oz!r} ({n}x)" for oz, n in duplicates.items())
                )
                if strict:
                    raise ValueError(msg)
                warnings.append(msg)

    def _check_phase_rules(
        self, doc: GAEBDocument, warnings: list[str], strict: bool
    ) -> None:
        """Apply phase-specific business rules."""
        phase_key = self._phase.value
        rules = _PHASE_RULES.get(phase_key)
        if not rules:
            return

        warn_present = rules.get("warn_if_present", set())
        warn_missing = rules.get("warn_if_missing", set())
        label = rules.get("label", phase_key)

        for item in doc.award.boq.iter_items():
            if item.item_type != ItemType.NORMAL:
                continue
            for field_name in warn_present:
                if getattr(item, field_name, None) is not None:
                    msg = (
                        f"Item {item.oz}: {field_name!r} is set but phase "
                        f"{phase_key} ({label}) typically should not have it."
                    )
                    if strict:
                        raise ValueError(msg)
                    warnings.append(msg)
                    break
            for field_name in warn_missing:
                if getattr(item, field_name, None) is None:
                    msg = (
                        f"Item {item.oz}: {field_name!r} is missing for phase "
                        f"{phase_key} ({label})."
                    )
                    if strict:
                        raise ValueError(msg)
                    warnings.append(msg)
                    break

    def _check_version_compat(
        self, doc: GAEBDocument, warnings: list[str], strict: bool
    ) -> None:
        """Check fields against version/phase compatibility map."""
        target_ver = self._version.value
        target_ver_idx = (
            _VERSION_ORDER.index(target_ver)
            if target_ver in _VERSION_ORDER
            else len(_VERSION_ORDER)
        )
        phase_key = self._phase.value

        meta = VERSION_REGISTRY.get(self._version)
        unsupported = set(meta.unsupported_fields) if meta else set()

        for item in doc.award.boq.iter_items():
            for field_name, compat in _VERSION_COMPAT.items():
                val = getattr(item, field_name, None)
                if val is None or (isinstance(val, (list, dict)) and not val):
                    continue

                if "min_version" in compat:
                    min_ver = compat["min_version"]
                    min_idx = (
                        _VERSION_ORDER.index(min_ver)
                        if min_ver in _VERSION_ORDER
                        else 0
                    )
                    if target_ver_idx < min_idx or field_name in unsupported:
                        msg = (
                            f"Item {item.oz}: {field_name!r} requires DA XML "
                            f"{min_ver}+, but target is {target_ver}. "
                            f"This field will be dropped during export."
                        )
                        if strict:
                            raise ValueError(msg)
                        warnings.append(msg)

                if "phases" in compat and phase_key not in compat["phases"]:
                    allowed = ", ".join(sorted(compat["phases"]))
                    msg = (
                        f"Item {item.oz}: {field_name!r} is only valid for "
                        f"phases {allowed}, but target is {phase_key}."
                    )
                    if strict:
                        raise ValueError(msg)
                    warnings.append(msg)

    @staticmethod
    def _run_xsd_validation(doc: GAEBDocument, xsd_dir: str) -> None:
        """Serialize to XML in memory and validate against XSD."""
        from pathlib import Path

        from lxml import etree

        from pygaeb.writer.gaeb_writer import GAEBWriter

        xml_bytes, _ = GAEBWriter.to_bytes(doc)
        xsd_path = Path(xsd_dir)
        version_dir = xsd_path / f"v{doc.source_version.value.replace('.', '')}"

        if not version_dir.exists():
            doc.add_info(
                f"XSD validation skipped: schema directory not found "
                f"for version {doc.source_version.value}"
            )
            return

        xsd_files = list(version_dir.glob("*.xsd"))
        if not xsd_files:
            doc.add_info(f"XSD validation skipped: no .xsd files in {version_dir}")
            return

        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            with xsd_files[0].open("rb") as xsd_fh:
                schema_doc = etree.parse(xsd_fh, parser=parser)
            schema = etree.XMLSchema(schema_doc)
            xml_doc = etree.fromstring(xml_bytes, parser=parser)
            if not schema.validate(xml_doc):
                for error in schema.error_log:  # type: ignore[attr-defined]
                    doc.add_warning(
                        f"XSD validation: {error.message}",
                        xpath=f"line {error.line}",
                    )
        except Exception as e:
            doc.add_warning(f"XSD validation failed: {e}")
