"""OZ-based item matching between two BoQ documents.

Matches items by OZ within each lot (lot-aware). Items that share the
same OZ and lot are considered the same position. Unmatched items are
returned separately for optional fuzzy resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pygaeb.api.boq_tree import BoQNode, BoQTree


@dataclass
class MatchResult:
    """Result of matching items between two trees."""

    matched: list[tuple[BoQNode, BoQNode]] = field(default_factory=list)
    unmatched_a: list[BoQNode] = field(default_factory=list)
    unmatched_b: list[BoQNode] = field(default_factory=list)

    @property
    def match_ratio(self) -> float:
        total = max(
            len(self.matched) + len(self.unmatched_a),
            len(self.matched) + len(self.unmatched_b),
            1,
        )
        return len(self.matched) / total


def match_items(tree_a: BoQTree, tree_b: BoQTree) -> MatchResult:
    """Match items between two BoQ trees by OZ within each lot.

    For single-lot documents, matches globally by OZ.
    For multi-lot documents, matches within lots by (lot_rno, oz).
    Falls back to global OZ matching for items unmatched within their lot.
    """
    index_a = _build_item_index(tree_a)
    index_b = _build_item_index(tree_b)

    matched: list[tuple[BoQNode, BoQNode]] = []
    used_b_keys: set[tuple[str, str]] = set()

    for key, node_a in index_a.items():
        if key in index_b:
            matched.append((node_a, index_b[key]))
            used_b_keys.add(key)

    unmatched_a = [node for key, node in index_a.items() if key not in index_b]
    unmatched_b = [node for key, node in index_b.items() if key not in used_b_keys]

    if unmatched_a and unmatched_b:
        _try_global_oz_fallback(unmatched_a, unmatched_b, matched)

    return MatchResult(matched=matched, unmatched_a=unmatched_a, unmatched_b=unmatched_b)


def _build_item_index(tree: BoQTree) -> dict[tuple[str, str], BoQNode]:
    """Build (lot_rno, oz) → BoQNode index. Uses first occurrence for duplicates."""
    index: dict[tuple[str, str], BoQNode] = {}
    for lot_node in tree.lots:
        lot_rno = lot_node.rno
        for item_node in lot_node.iter_items():
            key = (lot_rno, item_node.rno)
            if key not in index:
                index[key] = item_node
    return index


def _try_global_oz_fallback(
    unmatched_a: list[BoQNode],
    unmatched_b: list[BoQNode],
    matched: list[tuple[BoQNode, BoQNode]],
) -> None:
    """For items unmatched within their lot, try matching by OZ alone.

    This handles cases where items moved between lots. Mutates the lists in place.
    """
    oz_to_b: dict[str, BoQNode] = {}
    for node in unmatched_b:
        if node.rno not in oz_to_b:
            oz_to_b[node.rno] = node

    newly_matched_a: list[BoQNode] = []
    newly_matched_b_rnos: set[str] = set()

    for node_a in unmatched_a:
        if node_a.rno in oz_to_b and node_a.rno not in newly_matched_b_rnos:
            node_b = oz_to_b[node_a.rno]
            matched.append((node_a, node_b))
            newly_matched_a.append(node_a)
            newly_matched_b_rnos.add(node_a.rno)

    for node in newly_matched_a:
        unmatched_a.remove(node)
    unmatched_b[:] = [n for n in unmatched_b if n.rno not in newly_matched_b_rnos]
