"""Main entry point for comparing two GAEB documents.

Usage::

    from pygaeb import GAEBParser, BoQDiff

    doc_a = GAEBParser.parse("tender_v1.X83")
    doc_b = GAEBParser.parse("tender_v2.X83")
    result = BoQDiff.compare(doc_a, doc_b)
"""

from __future__ import annotations

from decimal import Decimal

from pygaeb.api.boq_tree import BoQTree
from pygaeb.diff.field_comparator import compare_items
from pygaeb.diff.item_matcher import match_items
from pygaeb.diff.models import (
    DiffDocInfo,
    DiffMode,
    DiffResult,
    DiffSummary,
    ItemAdded,
    ItemDiffSummary,
    ItemModified,
    ItemRemoved,
    MetadataChange,
    Significance,
)
from pygaeb.diff.structure_diff import compare_structure, detect_moved_items
from pygaeb.models.document import GAEBDocument


class BoQDiff:
    """Deterministic document comparison engine for GAEB BoQ files.

    Compares items by OZ (lot-aware), detects structural changes,
    and classifies each field change by significance level.
    """

    @staticmethod
    def compare(
        doc_a: GAEBDocument,
        doc_b: GAEBDocument,
        mode: DiffMode = DiffMode.DEFAULT,
    ) -> DiffResult:
        """Compare two GAEB documents and return a structured diff result.

        Args:
            doc_a: The "before" document (base/original).
            doc_b: The "after" document (revised/updated).
            mode: Controls strictness of compatibility validation.
                  ``DEFAULT`` adds warnings for mismatched projects.
                  ``STRICT`` raises ValueError for different projects.
                  ``FORCE`` suppresses all compatibility warnings.

        Returns:
            A ``DiffResult`` with item-level, structural, and metadata changes.

        Raises:
            ValueError: If mode is STRICT and documents appear to be from
                different projects.
            TypeError: If either document is not a procurement-type document.
        """
        _validate_documents(doc_a, doc_b, mode)

        info_a = _extract_doc_info(doc_a)
        info_b = _extract_doc_info(doc_b)

        tree_a = BoQTree(doc_a.award.boq)
        tree_b = BoQTree(doc_b.award.boq)

        match_result = match_items(tree_a, tree_b)

        item_summary = _build_item_summary(match_result)

        structure = compare_structure(tree_a, tree_b)
        moved = detect_moved_items(match_result.matched)
        structure.items_moved = moved

        metadata = _compare_metadata(doc_a, doc_b)
        warnings = _generate_warnings(doc_a, doc_b, match_result.match_ratio, mode)

        summary = _build_summary(info_a, info_b, item_summary, match_result.match_ratio)

        return DiffResult(
            doc_a=info_a,
            doc_b=info_b,
            summary=summary,
            items=item_summary,
            structure=structure,
            metadata=metadata,
            warnings=warnings,
        )


def _validate_documents(
    doc_a: GAEBDocument, doc_b: GAEBDocument, mode: DiffMode
) -> None:
    """Validate that both documents are comparable."""
    if not doc_a.is_procurement:
        raise TypeError(
            f"Document A is a {doc_a.document_kind.value} document. "
            "BoQDiff only supports procurement documents (X80-X89)."
        )
    if not doc_b.is_procurement:
        raise TypeError(
            f"Document B is a {doc_b.document_kind.value} document. "
            "BoQDiff only supports procurement documents (X80-X89)."
        )

    if mode == DiffMode.STRICT:
        prj_a = doc_a.award.project_no or doc_a.award.prj_id
        prj_b = doc_b.award.project_no or doc_b.award.prj_id
        if prj_a and prj_b and prj_a != prj_b:
            raise ValueError(
                f"Documents appear to be from different projects "
                f"({prj_a!r} vs {prj_b!r}). Use DiffMode.DEFAULT "
                f"or DiffMode.FORCE to compare anyway."
            )


def _extract_doc_info(doc: GAEBDocument) -> DiffDocInfo:
    """Extract identifying metadata snapshot from a document."""
    return DiffDocInfo(
        source_version=doc.source_version.value,
        exchange_phase=doc.exchange_phase.value,
        project_no=doc.award.project_no,
        project_name=doc.award.project_name or doc.award.lbl_prj,
        currency=doc.award.currency,
        item_count=doc.item_count,
        grand_total=doc.grand_total,
    )


def _build_item_summary(match_result: object) -> ItemDiffSummary:
    """Build the item-level diff summary from match results."""
    added: list[ItemAdded] = []
    removed: list[ItemRemoved] = []
    modified: list[ItemModified] = []
    unchanged_count = 0

    for node_b in match_result.unmatched_b:  # type: ignore[attr-defined]
        item = node_b.item
        lot_rno = _node_lot_rno(node_b)
        cat_rno = _node_category_rno(node_b)
        added.append(ItemAdded(
            oz=item.oz,
            short_text=item.short_text,
            lot_rno=lot_rno,
            category_rno=cat_rno,
            total_price=item.total_price,
        ))

    for node_a in match_result.unmatched_a:  # type: ignore[attr-defined]
        item = node_a.item
        lot_rno = _node_lot_rno(node_a)
        cat_rno = _node_category_rno(node_a)
        removed.append(ItemRemoved(
            oz=item.oz,
            short_text=item.short_text,
            lot_rno=lot_rno,
            category_rno=cat_rno,
            total_price=item.total_price,
        ))

    for node_a, node_b in match_result.matched:  # type: ignore[attr-defined]
        changes = compare_items(node_a.item, node_b.item)
        if changes:
            lot_rno = _node_lot_rno(node_a)
            modified.append(ItemModified(
                oz=node_a.item.oz,
                short_text_a=node_a.item.short_text,
                short_text_b=node_b.item.short_text,
                lot_rno=lot_rno,
                changes=changes,
            ))
        else:
            unchanged_count += 1

    return ItemDiffSummary(
        added=added,
        removed=removed,
        modified=modified,
        unchanged_count=unchanged_count,
    )


def _compare_metadata(doc_a: GAEBDocument, doc_b: GAEBDocument) -> list[MetadataChange]:
    """Compare document-level metadata fields."""
    changes: list[MetadataChange] = []

    meta_fields = [
        ("exchange_phase", doc_a.exchange_phase.value, doc_b.exchange_phase.value),
        ("source_version", doc_a.source_version.value, doc_b.source_version.value),
        ("currency", doc_a.award.currency, doc_b.award.currency),
        ("project_no", doc_a.award.project_no, doc_b.award.project_no),
        ("project_name", doc_a.award.project_name, doc_b.award.project_name),
        ("client", doc_a.award.client, doc_b.award.client),
    ]

    for name, val_a, val_b in meta_fields:
        if val_a != val_b:
            changes.append(MetadataChange(field=name, old_value=val_a, new_value=val_b))

    return changes


def _generate_warnings(
    doc_a: GAEBDocument,
    doc_b: GAEBDocument,
    match_ratio: float,
    mode: DiffMode,
) -> list[str]:
    """Generate human-readable warnings about the comparison."""
    warnings: list[str] = []

    if mode == DiffMode.FORCE:
        return warnings

    prj_a = doc_a.award.project_no or doc_a.award.prj_id
    prj_b = doc_b.award.project_no or doc_b.award.prj_id
    if prj_a and prj_b and prj_a != prj_b:
        warnings.append(
            f"Documents may be from different projects ({prj_a!r} vs {prj_b!r})."
        )

    if doc_a.award.currency != doc_b.award.currency:
        warnings.append(
            f"Currency changed from {doc_a.award.currency!r} to "
            f"{doc_b.award.currency!r}. Financial comparisons may be misleading."
        )

    if match_ratio < 0.3:
        warnings.append(
            f"Low match ratio ({match_ratio:.0%}). Documents may be unrelated."
        )

    if doc_a.source_version != doc_b.source_version:
        warnings.append(
            f"GAEB versions differ ({doc_a.source_version.value} vs "
            f"{doc_b.source_version.value})."
        )

    return warnings


def _build_summary(
    info_a: DiffDocInfo,
    info_b: DiffDocInfo,
    items: ItemDiffSummary,
    match_ratio: float,
) -> DiffSummary:
    """Build the top-level summary."""
    total_changes = len(items.added) + len(items.removed) + len(items.modified)
    has_changes = total_changes > 0

    financial_impact = _compute_financial_impact(info_a, info_b, items)

    all_sigs: list[Significance] = []
    if items.added:
        all_sigs.append(Significance.HIGH)
    if items.removed:
        all_sigs.append(Significance.HIGH)
    for m in items.modified:
        all_sigs.append(m.max_significance)

    max_sig = Significance.LOW
    sig_order = [Significance.CRITICAL, Significance.HIGH, Significance.MEDIUM, Significance.LOW]
    for sig in sig_order:
        if sig in all_sigs:
            max_sig = sig
            break

    prj_a = info_a.project_no
    prj_b = info_b.project_no
    is_likely_same = not (prj_a and prj_b and prj_a != prj_b)

    return DiffSummary(
        has_changes=has_changes,
        total_changes=total_changes,
        items_added=len(items.added),
        items_removed=len(items.removed),
        items_modified=len(items.modified),
        items_unchanged=items.unchanged_count,
        match_ratio=match_ratio,
        is_likely_same_project=is_likely_same,
        financial_impact=financial_impact,
        max_significance=max_sig,
    )


def _compute_financial_impact(
    info_a: DiffDocInfo,
    info_b: DiffDocInfo,
    items: ItemDiffSummary,
) -> Decimal | None:
    """Compute net financial impact (grand_total_b - grand_total_a)."""
    if info_a.grand_total is not None and info_b.grand_total is not None:
        return info_b.grand_total - info_a.grand_total
    return None


def _node_lot_rno(node: object) -> str:
    """Walk up the tree to find the enclosing lot's rno."""
    current = getattr(node, "parent", None)
    while current is not None:
        if hasattr(current, "kind") and current.kind.value == "lot":
            return current.rno
        current = getattr(current, "parent", None)
    return ""


def _node_category_rno(node: object) -> str:
    """Get the rno of the immediate parent category."""
    parent = getattr(node, "parent", None)
    if parent is not None and hasattr(parent, "kind") and parent.kind.value == "category":
        return parent.rno
    return ""
