"""OZ-based item matching between two BoQ documents.

Matches items by OZ within each lot (lot-aware). Items that share the
same OZ and lot are considered the same position. Unmatched items are
returned separately for optional fuzzy resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pygaeb.api.boq_tree import BoQNode, BoQTree


@dataclass
class MatchResult:
    """Result of matching items between two trees."""

    matched: list[tuple[BoQNode, BoQNode]] = field(default_factory=list)
    unmatched_a: list[BoQNode] = field(default_factory=list)
    unmatched_b: list[BoQNode] = field(default_factory=list)
    #: ``{full oz: copies}`` for OZs a document repeats; only the first copy is matched.
    duplicates_a: dict[str, int] = field(default_factory=dict)
    duplicates_b: dict[str, int] = field(default_factory=dict)

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
    index_a, duplicates_a = _build_item_index(tree_a)
    index_b, duplicates_b = _build_item_index(tree_b)

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

    return MatchResult(
        matched=matched,
        unmatched_a=unmatched_a,
        unmatched_b=unmatched_b,
        duplicates_a=duplicates_a,
        duplicates_b=duplicates_b,
    )


def _build_item_index(
    tree: BoQTree,
) -> tuple[dict[tuple[str, str], BoQNode], dict[str, int]]:
    """Build (lot_rno, full oz) → BoQNode index, keeping the first copy of a repeated OZ.

    Also returns ``{oz: copies}`` for the OZs that repeated, so the caller can say
    which items never took part in the comparison.
    """
    index: dict[tuple[str, str], BoQNode] = {}
    seen: dict[str, int] = {}
    for lot_node in tree.lots:
        lot_rno = lot_node.rno
        for item_node in lot_node.iter_items():
            key = (lot_rno, item_node.oz)
            if key not in index:
                index[key] = item_node
            seen[item_node.oz] = seen.get(item_node.oz, 0) + 1
    return index, {oz: n for oz, n in seen.items() if n > 1}


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
        if node.oz not in oz_to_b:
            oz_to_b[node.oz] = node

    newly_matched_a: list[BoQNode] = []
    newly_matched_b_ozs: set[str] = set()

    for node_a in unmatched_a:
        if node_a.oz in oz_to_b and node_a.oz not in newly_matched_b_ozs:
            node_b = oz_to_b[node_a.oz]
            matched.append((node_a, node_b))
            newly_matched_a.append(node_a)
            newly_matched_b_ozs.add(node_a.oz)

    for node in newly_matched_a:
        unmatched_a.remove(node)
    unmatched_b[:] = [n for n in unmatched_b if n.oz not in newly_matched_b_ozs]
