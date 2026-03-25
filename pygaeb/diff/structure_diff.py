"""Structural comparison of BoQ hierarchies (sections/categories).

Detects added, removed, and renamed sections, as well as items that
moved between categories or lots.
"""

from __future__ import annotations

from pygaeb.api.boq_tree import BoQNode, BoQTree, NodeKind
from pygaeb.diff.models import (
    ItemMoved,
    SectionChange,
    SectionRenamed,
    StructureDiffSummary,
)


def compare_structure(tree_a: BoQTree, tree_b: BoQTree) -> StructureDiffSummary:
    """Compare the category hierarchy between two BoQ trees."""
    result = StructureDiffSummary()

    cats_a = _build_category_index(tree_a)
    cats_b = _build_category_index(tree_b)

    keys_a = set(cats_a.keys())
    keys_b = set(cats_b.keys())

    for key in keys_b - keys_a:
        node = cats_b[key]
        lot_rno = _get_lot_rno(node)
        result.sections_added.append(SectionChange(
            rno=node.rno,
            label=node.label,
            lot_rno=lot_rno,
            item_count=sum(1 for _ in node.iter_items()),
        ))

    for key in keys_a - keys_b:
        node = cats_a[key]
        lot_rno = _get_lot_rno(node)
        result.sections_removed.append(SectionChange(
            rno=node.rno,
            label=node.label,
            lot_rno=lot_rno,
            item_count=sum(1 for _ in node.iter_items()),
        ))

    for key in keys_a & keys_b:
        node_a = cats_a[key]
        node_b = cats_b[key]
        if node_a.label != node_b.label:
            result.sections_renamed.append(SectionRenamed(
                rno=node_a.rno,
                old_label=node_a.label,
                new_label=node_b.label,
                lot_rno=_get_lot_rno(node_a),
            ))

    return result


def detect_moved_items(
    matched_pairs: list[tuple[BoQNode, BoQNode]],
) -> list[ItemMoved]:
    """Detect items whose parent category changed between the two documents."""
    moved: list[ItemMoved] = []
    for node_a, node_b in matched_pairs:
        cat_rno_a = _get_parent_category_rno(node_a)
        cat_rno_b = _get_parent_category_rno(node_b)
        lot_rno_a = _get_lot_rno(node_a)
        lot_rno_b = _get_lot_rno(node_b)

        if cat_rno_a != cat_rno_b or lot_rno_a != lot_rno_b:
            moved.append(ItemMoved(
                oz=node_a.rno,
                short_text=node_a.label,
                old_category_rno=cat_rno_a,
                new_category_rno=cat_rno_b,
                old_lot_rno=lot_rno_a,
                new_lot_rno=lot_rno_b,
            ))

    return moved


def _build_category_index(tree: BoQTree) -> dict[tuple[str, str], BoQNode]:
    """Build (lot_rno, category_rno) → BoQNode index."""
    index: dict[tuple[str, str], BoQNode] = {}
    for node in tree.walk():
        if node.kind == NodeKind.CATEGORY:
            lot_rno = _get_lot_rno(node)
            key = (lot_rno, node.rno)
            if key not in index:
                index[key] = node
    return index


def _get_lot_rno(node: BoQNode) -> str:
    """Walk up the tree to find the enclosing lot's rno."""
    current = node.parent
    while current is not None:
        if current.kind == NodeKind.LOT:
            return current.rno
        current = current.parent
    return ""


def _get_parent_category_rno(node: BoQNode) -> str:
    """Get the rno of the immediate parent category."""
    if node.parent is not None and node.parent.kind == NodeKind.CATEGORY:
        return node.parent.rno
    return ""
