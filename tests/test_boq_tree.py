"""Tests for the read-only BoQ tree API (BoQTree, BoQNode, NodeKind)."""

from __future__ import annotations  # noqa: I001

from decimal import Decimal

import pytest

from pygaeb.api.boq_tree import BoQTree, NodeKind
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.enums import ItemType
from pygaeb.models.item import Item


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def nested_boq() -> BoQ:
    """BoQ with nested subcategories: Lot > Rohbau > Mauerwerk > 2 items, Ausbau > 1 item."""
    items_mauer = [
        Item(oz="01.01.0010", short_text="Mauerwerk Innenwand", qty=Decimal("1170"),
             unit="m2", unit_price=Decimal("45.50"), total_price=Decimal("53235.00"),
             item_type=ItemType.NORMAL, hierarchy_path=["Rohbau", "Mauerwerk"]),
        Item(oz="01.01.0020", short_text="Mauerwerk Aussenwand", qty=Decimal("850"),
             unit="m2", unit_price=Decimal("68.00"), total_price=Decimal("57800.00"),
             item_type=ItemType.NORMAL, hierarchy_path=["Rohbau", "Mauerwerk"]),
    ]
    items_ausbau = [
        Item(oz="02.0010", short_text="Innentuer Holz", qty=Decimal("25"),
             unit="Stk", unit_price=Decimal("450.00"), total_price=Decimal("11250.00"),
             item_type=ItemType.NORMAL, hierarchy_path=["Ausbau"]),
    ]
    mauerwerk = BoQCtgy(rno="01", label="Mauerwerk", items=items_mauer)
    rohbau = BoQCtgy(rno="01", label="Rohbau", subcategories=[mauerwerk])
    ausbau = BoQCtgy(rno="02", label="Ausbau", items=items_ausbau)
    lot = Lot(rno="1", label="Default", body=BoQBody(categories=[rohbau, ausbau]))
    return BoQ(lots=[lot])


@pytest.fixture
def multi_lot_boq() -> BoQ:
    """BoQ with 2 lots, each with 1 category. Lot 2 has an EVENTUAL item."""
    lot1 = Lot(
        rno="1", label="Los 1 - Erdarbeiten",
        body=BoQBody(categories=[BoQCtgy(rno="01", label="Erdarbeiten", items=[
            Item(oz="01.0010", short_text="Aushub", qty=Decimal("500"),
                 unit="m3", total_price=Decimal("6000"), item_type=ItemType.NORMAL),
        ])]),
    )
    lot2 = Lot(
        rno="2", label="Los 2 - Beton",
        body=BoQBody(categories=[BoQCtgy(rno="01", label="Beton", items=[
            Item(oz="01.0010", short_text="Stahlbeton", qty=Decimal("80"),
                 unit="m3", total_price=Decimal("14400"), item_type=ItemType.NORMAL),
            Item(oz="01.0020", short_text="Pfahlgründung", qty=Decimal("1"),
                 unit="psch", total_price=Decimal("25000"), item_type=ItemType.EVENTUAL),
        ])]),
    )
    return BoQ(lots=[lot1, lot2])


@pytest.fixture
def empty_boq() -> BoQ:
    """BoQ with one lot and one empty category."""
    lot = Lot(rno="1", label="Empty Lot", body=BoQBody(categories=[
        BoQCtgy(rno="01", label="Empty Section"),
    ]))
    return BoQ(lots=[lot])


@pytest.fixture
def tree(nested_boq: BoQ) -> BoQTree:
    return BoQTree(nested_boq)


@pytest.fixture
def multi_tree(multi_lot_boq: BoQ) -> BoQTree:
    return BoQTree(multi_lot_boq)


# ── Root node ─────────────────────────────────────────────────────────


class TestRoot:
    def test_root_kind(self, tree: BoQTree) -> None:
        assert tree.root.kind == NodeKind.ROOT

    def test_root_has_no_parent(self, tree: BoQTree) -> None:
        assert tree.root.parent is None
        assert tree.root.is_root is True

    def test_root_depth_is_zero(self, tree: BoQTree) -> None:
        assert tree.root.depth == 0

    def test_root_index_is_zero(self, tree: BoQTree) -> None:
        assert tree.root.index == 0

    def test_root_children_are_lots(self, tree: BoQTree) -> None:
        for child in tree.root.children:
            assert child.kind == NodeKind.LOT

    def test_root_label(self, tree: BoQTree) -> None:
        assert tree.root.label == "BoQ"

    def test_root_rno_is_empty(self, tree: BoQTree) -> None:
        assert tree.root.rno == ""

    def test_root_boq_accessor(self, tree: BoQTree, nested_boq: BoQ) -> None:
        assert tree.root.boq is nested_boq


# ── Lot nodes ─────────────────────────────────────────────────────────


class TestLotNode:
    def test_lot_kind(self, tree: BoQTree) -> None:
        assert tree.lots[0].kind == NodeKind.LOT

    def test_lot_depth(self, tree: BoQTree) -> None:
        assert tree.lots[0].depth == 1

    def test_lot_parent_is_root(self, tree: BoQTree) -> None:
        assert tree.lots[0].parent is tree.root

    def test_lot_label(self, tree: BoQTree) -> None:
        assert tree.lots[0].label == "Default"

    def test_lot_rno(self, tree: BoQTree) -> None:
        assert tree.lots[0].rno == "1"

    def test_lot_accessor(self, tree: BoQTree) -> None:
        lot_model = tree.lots[0].lot
        assert lot_model.rno == "1"

    def test_lot_children_are_categories(self, tree: BoQTree) -> None:
        for child in tree.lots[0].children:
            assert child.kind == NodeKind.CATEGORY


# ── Category nodes ────────────────────────────────────────────────────


class TestCategoryNode:
    def test_category_kind(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        assert rohbau.kind == NodeKind.CATEGORY

    def test_category_depth(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        assert rohbau.depth == 2
        mauerwerk = rohbau.children[0]
        assert mauerwerk.depth == 3

    def test_category_label_and_rno(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        assert rohbau.label == "Rohbau"
        assert rohbau.rno == "01"

    def test_category_accessor(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        assert rohbau.category.label == "Rohbau"

    def test_category_parent_is_lot(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        assert rohbau.parent is tree.lots[0]

    def test_subcategory_parent_is_category(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        mauerwerk = rohbau.children[0]
        assert mauerwerk.parent is rohbau


# ── Item nodes ────────────────────────────────────────────────────────


class TestItemNode:
    def test_item_kind(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.kind == NodeKind.ITEM

    def test_item_is_leaf(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.is_leaf is True
        assert len(item_node.children) == 0

    def test_item_depth(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.depth == 4

    def test_item_accessor(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.item.oz == "01.01.0010"

    def test_item_label_is_short_text(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.label == "Mauerwerk Innenwand"

    def test_item_rno_is_oz(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.rno == "01.01.0010"

    def test_item_parent_is_category(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.parent is mauerwerk
        assert item_node.parent.label == "Mauerwerk"


# ── Children ordering ─────────────────────────────────────────────────


class TestChildrenOrder:
    def test_subcategories_before_items(self, tree: BoQTree) -> None:
        """Rohbau has 1 subcategory (Mauerwerk) and 0 items — children are just the subcategory."""
        rohbau = tree.lots[0].children[0]
        assert len(rohbau.children) == 1
        assert rohbau.children[0].kind == NodeKind.CATEGORY

    def test_items_in_leaf_category(self, tree: BoQTree) -> None:
        """Mauerwerk has 0 subcategories and 2 items."""
        mauerwerk = tree.lots[0].children[0].children[0]
        assert len(mauerwerk.children) == 2
        assert all(c.kind == NodeKind.ITEM for c in mauerwerk.children)

    def test_children_immutable(self, tree: BoQTree) -> None:
        assert isinstance(tree.root.children, tuple)
        assert isinstance(tree.lots[0].children, tuple)


# ── Parent / ancestor / path ──────────────────────────────────────────


class TestParentChain:
    def test_full_parent_chain(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert item_node.parent.label == "Mauerwerk"
        assert item_node.parent.parent.label == "Rohbau"
        assert item_node.parent.parent.parent.label == "Default"
        assert item_node.parent.parent.parent.parent is tree.root

    def test_ancestors(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        ancestors = item_node.ancestors
        assert len(ancestors) == 4
        assert ancestors[0] is tree.root
        assert ancestors[-1] is mauerwerk

    def test_path_includes_self(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        path = item_node.path
        assert path[-1] is item_node
        assert path[0] is tree.root

    def test_label_path(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        expected = ["BoQ", "Default", "Rohbau", "Mauerwerk", "Mauerwerk Innenwand"]
        assert item_node.label_path == expected

    def test_root_ancestors_empty(self, tree: BoQTree) -> None:
        assert tree.root.ancestors == ()

    def test_root_path_is_just_self(self, tree: BoQTree) -> None:
        assert tree.root.path == (tree.root,)


# ── Siblings ──────────────────────────────────────────────────────────


class TestSiblings:
    def test_item_siblings(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        first_item = mauerwerk.children[0]
        second_item = mauerwerk.children[1]
        assert first_item.siblings == (second_item,)
        assert second_item.siblings == (first_item,)

    def test_category_siblings(self, tree: BoQTree) -> None:
        lot = tree.lots[0]
        rohbau = lot.children[0]
        ausbau = lot.children[1]
        assert rohbau.siblings == (ausbau,)
        assert ausbau.siblings == (rohbau,)

    def test_root_siblings_empty(self, tree: BoQTree) -> None:
        assert tree.root.siblings == ()

    def test_next_sibling(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        first_item = mauerwerk.children[0]
        second_item = mauerwerk.children[1]
        assert first_item.next_sibling is second_item
        assert second_item.next_sibling is None

    def test_prev_sibling(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        first_item = mauerwerk.children[0]
        second_item = mauerwerk.children[1]
        assert first_item.prev_sibling is None
        assert second_item.prev_sibling is first_item

    def test_index_values(self, tree: BoQTree) -> None:
        lot = tree.lots[0]
        assert lot.children[0].index == 0
        assert lot.children[1].index == 1


# ── find_item / find_category ─────────────────────────────────────────


class TestLookups:
    def test_find_item_by_oz(self, tree: BoQTree) -> None:
        node = tree.find_item("01.01.0010")
        assert node is not None
        assert node.kind == NodeKind.ITEM
        assert node.item.short_text == "Mauerwerk Innenwand"

    def test_find_item_missing(self, tree: BoQTree) -> None:
        assert tree.find_item("nonexistent") is None

    def test_find_category_by_rno(self, tree: BoQTree) -> None:
        node = tree.find_category("02")
        assert node is not None
        assert node.label == "Ausbau"

    def test_find_category_missing(self, tree: BoQTree) -> None:
        assert tree.find_category("99") is None

    def test_find_all_categories_same_rno(self, multi_tree: BoQTree) -> None:
        nodes = multi_tree.find_all_categories("01")
        assert len(nodes) == 2
        labels = {n.label for n in nodes}
        assert labels == {"Erdarbeiten", "Beton"}

    def test_find_item_duplicate_oz_returns_first(self, multi_tree: BoQTree) -> None:
        """When the same OZ exists in multiple lots, find_item returns the first."""
        node = multi_tree.find_item("01.0010")
        assert node is not None
        assert node.item.short_text == "Aushub"


# ── iter_items / iter_categories / iter_descendants ───────────────────


class TestIteration:
    def test_iter_items_from_root(self, tree: BoQTree) -> None:
        items = list(tree.root.iter_items())
        assert len(items) == 3
        assert all(n.kind == NodeKind.ITEM for n in items)

    def test_iter_items_from_category(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        items = list(rohbau.iter_items())
        assert len(items) == 2

    def test_iter_categories_from_root(self, tree: BoQTree) -> None:
        cats = list(tree.root.iter_categories())
        labels = [c.label for c in cats]
        assert "Rohbau" in labels
        assert "Mauerwerk" in labels
        assert "Ausbau" in labels

    def test_iter_descendants_dfs_order(self, tree: BoQTree) -> None:
        descendants = list(tree.root.iter_descendants())
        kinds = [n.kind for n in descendants]
        assert kinds[0] == NodeKind.LOT
        assert NodeKind.CATEGORY in kinds
        assert NodeKind.ITEM in kinds

    def test_iter_descendants_excludes_self(self, tree: BoQTree) -> None:
        descendants = list(tree.root.iter_descendants())
        assert tree.root not in descendants

    def test_leaf_has_no_descendants(self, tree: BoQTree) -> None:
        mauerwerk = tree.lots[0].children[0].children[0]
        item_node = mauerwerk.children[0]
        assert list(item_node.iter_descendants()) == []
        assert list(item_node.iter_items()) == []


# ── find / find_all (predicate) ──────────────────────────────────────


class TestFindPredicate:
    def test_find_by_unit(self, tree: BoQTree) -> None:
        node = tree.root.find(
            lambda n: n.kind == NodeKind.ITEM and n.item.unit == "Stk"
        )
        assert node is not None
        assert node.item.short_text == "Innentuer Holz"

    def test_find_returns_none_when_no_match(self, tree: BoQTree) -> None:
        result = tree.root.find(lambda n: False)
        assert result is None

    def test_find_all(self, tree: BoQTree) -> None:
        nodes = tree.root.find_all(
            lambda n: n.kind == NodeKind.ITEM and n.item.unit == "m2"
        )
        assert len(nodes) == 2


# ── walk / walk_bfs ──────────────────────────────────────────────────


class TestWalk:
    def test_walk_visits_all_nodes(self, tree: BoQTree) -> None:
        all_nodes = list(tree.walk())
        assert len(all_nodes) == tree.node_count

    def test_walk_starts_with_root(self, tree: BoQTree) -> None:
        all_nodes = list(tree.walk())
        assert all_nodes[0] is tree.root

    def test_walk_dfs_order(self, tree: BoQTree) -> None:
        """DFS: root → lot → rohbau → mauerwerk → items → ausbau → item."""
        all_nodes = list(tree.walk())
        labels = [n.label for n in all_nodes]
        rohbau_idx = labels.index("Rohbau")
        mauerwerk_idx = labels.index("Mauerwerk")
        ausbau_idx = labels.index("Ausbau")
        assert rohbau_idx < mauerwerk_idx < ausbau_idx

    def test_walk_bfs_visits_all_nodes(self, tree: BoQTree) -> None:
        all_nodes = list(tree.walk_bfs())
        assert len(all_nodes) == tree.node_count

    def test_walk_bfs_order(self, tree: BoQTree) -> None:
        """BFS: root first, then lots, then top-level categories, then deeper."""
        all_nodes = list(tree.walk_bfs())
        depths = [n.depth for n in all_nodes]
        assert depths == sorted(depths)


# ── Counts ────────────────────────────────────────────────────────────


class TestCounts:
    def test_item_count(self, tree: BoQTree) -> None:
        assert tree.item_count == 3

    def test_node_count(self, tree: BoQTree) -> None:
        # root(1) + lot(1) + rohbau(1) + mauerwerk(1) + ausbau(1) + items(3) = 8
        assert tree.node_count == 8

    def test_multi_lot_item_count(self, multi_tree: BoQTree) -> None:
        assert multi_tree.item_count == 3

    def test_multi_lot_node_count(self, multi_tree: BoQTree) -> None:
        # root(1) + lot1(1) + erdarbeiten(1) + item(1)
        # + lot2(1) + beton(1) + items(2) = 8
        assert multi_tree.node_count == 8


# ── Multi-lot ─────────────────────────────────────────────────────────


class TestMultiLot:
    def test_is_multi_lot(self, multi_tree: BoQTree) -> None:
        assert multi_tree.is_multi_lot is True

    def test_single_lot_not_multi(self, tree: BoQTree) -> None:
        assert tree.is_multi_lot is False

    def test_lot_count(self, multi_tree: BoQTree) -> None:
        assert len(multi_tree.lots) == 2

    def test_lots_property_matches_root_children(self, multi_tree: BoQTree) -> None:
        assert multi_tree.lots is multi_tree.root.children

    def test_items_per_lot(self, multi_tree: BoQTree) -> None:
        lot1_items = list(multi_tree.lots[0].iter_items())
        lot2_items = list(multi_tree.lots[1].iter_items())
        assert len(lot1_items) == 1
        assert len(lot2_items) == 2


# ── Type-safe accessor errors ─────────────────────────────────────────


class TestTypeSafeAccessors:
    def test_lot_accessor_on_root_raises(self, tree: BoQTree) -> None:
        with pytest.raises(TypeError, match="lot"):
            _ = tree.root.lot

    def test_item_accessor_on_lot_raises(self, tree: BoQTree) -> None:
        with pytest.raises(TypeError, match="item"):
            _ = tree.lots[0].item

    def test_category_accessor_on_item_raises(self, tree: BoQTree) -> None:
        node = tree.find_item("01.01.0010")
        assert node is not None
        with pytest.raises(TypeError, match="category"):
            _ = node.category

    def test_boq_accessor_on_category_raises(self, tree: BoQTree) -> None:
        rohbau = tree.lots[0].children[0]
        with pytest.raises(TypeError, match="boq"):
            _ = rohbau.boq


# ── Empty category ────────────────────────────────────────────────────


class TestEmptyCategory:
    def test_empty_category_is_leaf(self, empty_boq: BoQ) -> None:
        tree = BoQTree(empty_boq)
        ctgy_node = tree.lots[0].children[0]
        assert ctgy_node.is_leaf is True
        assert len(ctgy_node.children) == 0

    def test_empty_category_iter_items_empty(self, empty_boq: BoQ) -> None:
        tree = BoQTree(empty_boq)
        ctgy_node = tree.lots[0].children[0]
        assert list(ctgy_node.iter_items()) == []


# ── Model identity ────────────────────────────────────────────────────


class TestModelIdentity:
    def test_node_wraps_same_object(self, tree: BoQTree, nested_boq: BoQ) -> None:
        """BoQNode.model returns the original Pydantic object, not a copy."""
        assert tree.root.model is nested_boq
        lot_model = nested_boq.lots[0]
        assert tree.lots[0].model is lot_model

    def test_item_model_identity(self, tree: BoQTree, nested_boq: BoQ) -> None:
        original_item = nested_boq.lots[0].body.categories[0].subcategories[0].items[0]
        node = tree.find_item("01.01.0010")
        assert node is not None
        assert node.model is original_item


# ── Repr ──────────────────────────────────────────────────────────────


class TestRepr:
    def test_node_repr(self, tree: BoQTree) -> None:
        r = repr(tree.lots[0])
        assert "lot" in r
        assert "Default" in r

    def test_tree_repr(self, tree: BoQTree) -> None:
        r = repr(tree)
        assert "BoQTree" in r
        assert "items=3" in r

    def test_item_node_repr(self, tree: BoQTree) -> None:
        node = tree.find_item("01.01.0010")
        assert node is not None
        r = repr(node)
        assert "item" in r
        assert "01.01.0010" in r


# ── Construction from existing conftest fixtures ──────────────────────


class TestWithConftestFixtures:
    """Verify BoQTree works with the standard conftest sample_document and multi_lot_document."""

    def test_from_sample_document(self, sample_document) -> None:
        tree = BoQTree(sample_document.award.boq)
        assert tree.item_count == sample_document.item_count
        assert tree.is_multi_lot is False

    def test_from_multi_lot_document(self, multi_lot_document) -> None:
        tree = BoQTree(multi_lot_document.award.boq)
        assert tree.item_count == multi_lot_document.item_count
        assert tree.is_multi_lot is True
        assert len(tree.lots) == 2

    def test_navigate_sample_document(self, sample_document) -> None:
        tree = BoQTree(sample_document.award.boq)
        node = tree.find_item("01.01.0010")
        assert node is not None
        assert node.parent is not None
        assert node.parent.kind == NodeKind.CATEGORY

    def test_walk_sample_document(self, sample_document) -> None:
        tree = BoQTree(sample_document.award.boq)
        all_nodes = list(tree.walk())
        assert len(all_nodes) == tree.node_count
        item_nodes = [n for n in all_nodes if n.kind == NodeKind.ITEM]
        assert len(item_nodes) == 3
