"""Read-only tree API for navigating the BoQ hierarchy with parent references.

Usage::

    from pygaeb import GAEBParser, BoQTree

    doc = GAEBParser.parse("tender.X83")
    tree = BoQTree(doc.award.boq)

    node = tree.find_item("01.01.0010")
    print(node.parent.label)    # category label
    print(node.depth)           # level in tree
    print(node.label_path)      # breadcrumb from root

The tree adapter wraps existing Pydantic models without modifying them.
All navigation properties are precomputed at construction time (O(1) access).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from enum import Enum
from typing import Any, Callable, Union

from pygaeb.models.boq import BoQ, BoQCtgy, Lot
from pygaeb.models.item import Item


class NodeKind(str, Enum):
    """Discriminator for the type of model a BoQNode wraps."""

    ROOT = "root"
    LOT = "lot"
    CATEGORY = "category"
    ITEM = "item"


_ModelType = Union[BoQ, Lot, BoQCtgy, Item]


class BoQNode:
    """Read-only tree node wrapping a single BoQ model object.

    Provides O(1) parent/children/depth access and subtree query helpers.
    Children are stored as an immutable tuple to signal read-only intent.
    """

    __slots__ = ("_kind", "_model", "_parent", "_children", "_depth", "_index")

    def __init__(
        self,
        kind: NodeKind,
        model: _ModelType,
        parent: BoQNode | None,
        children: tuple[BoQNode, ...],
        depth: int,
        index: int,
    ) -> None:
        self._kind = kind
        self._model = model
        self._parent = parent
        self._children = children
        self._depth = depth
        self._index = index

    def __repr__(self) -> str:
        return f"BoQNode(kind={self._kind.value}, rno={self.rno!r}, label={self.label!r}, depth={self._depth})"

    # ------------------------------------------------------------------
    # Core properties (precomputed, O(1))
    # ------------------------------------------------------------------

    @property
    def kind(self) -> NodeKind:
        return self._kind

    @property
    def model(self) -> _ModelType:
        """The underlying Pydantic model object (same identity, not a copy)."""
        return self._model

    @property
    def parent(self) -> BoQNode | None:
        return self._parent

    @property
    def children(self) -> tuple[BoQNode, ...]:
        return self._children

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def index(self) -> int:
        """Position among siblings (0-based)."""
        return self._index

    # ------------------------------------------------------------------
    # Derived navigation (computed from core, still cheap)
    # ------------------------------------------------------------------

    @property
    def is_leaf(self) -> bool:
        return len(self._children) == 0

    @property
    def is_root(self) -> bool:
        return self._parent is None

    @property
    def siblings(self) -> tuple[BoQNode, ...]:
        """All siblings excluding self. Empty tuple for root."""
        if self._parent is None:
            return ()
        return tuple(c for c in self._parent._children if c is not self)

    @property
    def next_sibling(self) -> BoQNode | None:
        if self._parent is None:
            return None
        sibs = self._parent._children
        next_idx = self._index + 1
        if next_idx < len(sibs):
            return sibs[next_idx]
        return None

    @property
    def prev_sibling(self) -> BoQNode | None:
        if self._parent is None:
            return None
        prev_idx = self._index - 1
        if prev_idx >= 0:
            return self._parent._children[prev_idx]
        return None

    @property
    def ancestors(self) -> tuple[BoQNode, ...]:
        """From root to parent (excludes self). Empty for root."""
        result: list[BoQNode] = []
        node = self._parent
        while node is not None:
            result.append(node)
            node = node._parent
        result.reverse()
        return tuple(result)

    @property
    def path(self) -> tuple[BoQNode, ...]:
        """From root to self (includes self)."""
        return (*self.ancestors, self)

    # ------------------------------------------------------------------
    # Type-safe model accessors
    # ------------------------------------------------------------------

    @property
    def boq(self) -> BoQ:
        if self._kind != NodeKind.ROOT:
            raise TypeError(f"Cannot access .boq on a {self._kind.value} node")
        return self._model  # type: ignore[return-value]

    @property
    def lot(self) -> Lot:
        if self._kind != NodeKind.LOT:
            raise TypeError(f"Cannot access .lot on a {self._kind.value} node")
        return self._model  # type: ignore[return-value]

    @property
    def category(self) -> BoQCtgy:
        if self._kind != NodeKind.CATEGORY:
            raise TypeError(f"Cannot access .category on a {self._kind.value} node")
        return self._model  # type: ignore[return-value]

    @property
    def item(self) -> Item:
        if self._kind != NodeKind.ITEM:
            raise TypeError(f"Cannot access .item on a {self._kind.value} node")
        return self._model  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Convenience (unified across node kinds)
    # ------------------------------------------------------------------

    @property
    def label(self) -> str:
        if self._kind == NodeKind.ROOT:
            return "BoQ"
        if self._kind == NodeKind.LOT:
            return self._model.label or self._model.rno or "Lot"  # type: ignore[union-attr]
        if self._kind == NodeKind.CATEGORY:
            return self._model.label or self._model.rno or ""  # type: ignore[union-attr]
        return self._model.short_text or self._model.oz or ""  # type: ignore[union-attr]

    @property
    def rno(self) -> str:
        if self._kind == NodeKind.ROOT:
            return ""
        if self._kind == NodeKind.ITEM:
            return self._model.oz  # type: ignore[union-attr]
        return self._model.rno  # type: ignore[union-attr]

    @property
    def label_path(self) -> list[str]:
        """Labels from root to self (human-readable breadcrumb)."""
        return [n.label for n in self.path]

    # ------------------------------------------------------------------
    # Subtree queries
    # ------------------------------------------------------------------

    def iter_descendants(self) -> Iterator[BoQNode]:
        """Depth-first iteration over all descendants (excludes self)."""
        stack = list(reversed(self._children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node._children))

    def iter_items(self) -> Iterator[BoQNode]:
        """All ITEM-kind descendants (depth-first)."""
        for node in self.iter_descendants():
            if node._kind == NodeKind.ITEM:
                yield node

    def iter_categories(self) -> Iterator[BoQNode]:
        """All CATEGORY-kind descendants (depth-first)."""
        for node in self.iter_descendants():
            if node._kind == NodeKind.CATEGORY:
                yield node

    def find(self, predicate: Callable[[BoQNode], bool]) -> BoQNode | None:
        """First descendant matching predicate, or None."""
        for node in self.iter_descendants():
            if predicate(node):
                return node
        return None

    def find_all(self, predicate: Callable[[BoQNode], bool]) -> list[BoQNode]:
        """All descendants matching predicate."""
        return [node for node in self.iter_descendants() if predicate(node)]


_MAX_TREE_DEPTH = 50


class BoQTree:
    """Read-only tree adapter for a procurement BoQ.

    Wraps an existing ``BoQ`` instance and builds a navigable node graph
    with parent references, depth tracking, and indexed lookups. The
    underlying Pydantic models are not modified.

    Construction is O(n) where n is the total number of nodes.
    """

    __slots__ = ("_root", "_items_by_oz", "_node_count", "_item_count")

    def __init__(self, boq: BoQ) -> None:
        self._items_by_oz: dict[str, BoQNode] = {}
        self._node_count = 0
        self._item_count = 0
        self._root = self._build_root(boq)

    def __repr__(self) -> str:
        return f"BoQTree(lots={len(self._root._children)}, nodes={self._node_count}, items={self._item_count})"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def root(self) -> BoQNode:
        return self._root

    @property
    def lots(self) -> tuple[BoQNode, ...]:
        return self._root._children

    @property
    def is_multi_lot(self) -> bool:
        return len(self._root._children) > 1

    @property
    def node_count(self) -> int:
        """Total nodes in the tree (all kinds including root)."""
        return self._node_count

    @property
    def item_count(self) -> int:
        """Total ITEM-kind nodes."""
        return self._item_count

    def find_item(self, oz: str) -> BoQNode | None:
        """O(1) item lookup by OZ. Returns None if not found."""
        return self._items_by_oz.get(oz)

    def find_category(self, rno: str) -> BoQNode | None:
        """First category node with this rno (depth-first). None if not found."""
        return self._root.find(
            lambda n: n._kind == NodeKind.CATEGORY and n.rno == rno
        )

    def find_all_categories(self, rno: str) -> list[BoQNode]:
        """All category nodes with this rno (e.g. same rno in different lots)."""
        return self._root.find_all(
            lambda n: n._kind == NodeKind.CATEGORY and n.rno == rno
        )

    def walk(self) -> Iterator[BoQNode]:
        """Depth-first iteration over all nodes (including root)."""
        yield self._root
        yield from self._root.iter_descendants()

    def walk_bfs(self) -> Iterator[BoQNode]:
        """Breadth-first iteration over all nodes (including root)."""
        queue: deque[BoQNode] = deque([self._root])
        while queue:
            node = queue.popleft()
            yield node
            queue.extend(node._children)

    # ------------------------------------------------------------------
    # Tree construction (private)
    # ------------------------------------------------------------------

    def _build_root(self, boq: BoQ) -> BoQNode:
        root = BoQNode(
            kind=NodeKind.ROOT,
            model=boq,
            parent=None,
            children=(),
            depth=0,
            index=0,
        )
        self._node_count += 1

        lot_nodes: list[BoQNode] = []
        for i, lot_model in enumerate(boq.lots):
            lot_node = self._build_lot(lot_model, parent=root, index=i)
            lot_nodes.append(lot_node)

        root._children = tuple(lot_nodes)
        return root

    def _build_lot(self, lot_model: Lot, parent: BoQNode, index: int) -> BoQNode:
        lot_node = BoQNode(
            kind=NodeKind.LOT,
            model=lot_model,
            parent=parent,
            children=(),
            depth=1,
            index=index,
        )
        self._node_count += 1

        child_nodes: list[BoQNode] = []
        for i, ctgy in enumerate(lot_model.body.categories):
            ctgy_node = self._build_category(ctgy, parent=lot_node, depth=2, index=i)
            child_nodes.append(ctgy_node)

        lot_node._children = tuple(child_nodes)
        return lot_node

    def _build_category(
        self, ctgy: BoQCtgy, parent: BoQNode, depth: int, index: int
    ) -> BoQNode:
        if depth > _MAX_TREE_DEPTH:
            return BoQNode(
                kind=NodeKind.CATEGORY,
                model=ctgy,
                parent=parent,
                children=(),
                depth=depth,
                index=index,
            )

        ctgy_node = BoQNode(
            kind=NodeKind.CATEGORY,
            model=ctgy,
            parent=parent,
            children=(),
            depth=depth,
            index=index,
        )
        self._node_count += 1

        child_nodes: list[BoQNode] = []

        for i, sub in enumerate(ctgy.subcategories):
            sub_node = self._build_category(sub, parent=ctgy_node, depth=depth + 1, index=i)
            child_nodes.append(sub_node)

        offset = len(child_nodes)
        for i, item_model in enumerate(ctgy.items):
            item_node = self._build_item(item_model, parent=ctgy_node, depth=depth + 1, index=offset + i)
            child_nodes.append(item_node)

        ctgy_node._children = tuple(child_nodes)
        return ctgy_node

    def _build_item(self, item_model: Item, parent: BoQNode, depth: int, index: int) -> BoQNode:
        item_node = BoQNode(
            kind=NodeKind.ITEM,
            model=item_model,
            parent=parent,
            children=(),
            depth=depth,
            index=index,
        )
        self._node_count += 1
        self._item_count += 1

        if item_model.oz:
            self._items_by_oz.setdefault(item_model.oz, item_node)

        return item_node
