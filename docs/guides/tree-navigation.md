# Tree Navigation

*Since v1.8.0*

The `BoQTree` API provides a read-only tree view over a procurement BoQ with parent references, depth tracking, sibling navigation, and indexed lookups. It wraps the existing Pydantic models without modifying them.

## Why a Tree API?

The core `BoQ → Lot → BoQBody → BoQCtgy → Item` model is a downward-only nested structure — you can iterate items, but you cannot ask "what category does this item belong to?" or "what are the siblings of this section?". Every application building a UI tree, a copy/paste feature, or a structured report ends up reimplementing the same recursive walk.

`BoQTree` solves this by building a lightweight node graph on top of the existing models, with O(1) access to parent, children, depth, and siblings.

## Quick Start

```python
from pygaeb import GAEBParser, BoQTree

doc = GAEBParser.parse("tender.X83")
tree = BoQTree(doc.award.boq)

# Find an item and navigate up
node = tree.find_item("01.01.0010")
print(node.parent.label)       # "Mauerwerk" (category label)
print(node.parent.parent.label) # "Rohbau" (parent category)
print(node.depth)              # 4
print(node.label_path)         # ["BoQ", "Default", "Rohbau", "Mauerwerk", "Mauerwerk Innenwand"]
```

## Node Kinds

Every node in the tree has a `kind` that tells you what it wraps:

| Kind | Wraps | Typical depth |
|------|-------|---------------|
| `NodeKind.ROOT` | `BoQ` | 0 |
| `NodeKind.LOT` | `Lot` | 1 |
| `NodeKind.CATEGORY` | `BoQCtgy` | 2+ |
| `NodeKind.ITEM` | `Item` | leaf level |

## Navigating the Tree

### Parent, children, siblings

```python
from pygaeb.api.boq_tree import NodeKind

for lot_node in tree.lots:
    print(lot_node.label, lot_node.depth)

    for child in lot_node.children:
        if child.kind == NodeKind.CATEGORY:
            print(f"  {child.rno} {child.label}")

            # Siblings
            for sib in child.siblings:
                print(f"    sibling: {sib.label}")

            # Items in this category
            for item_node in child.iter_items():
                print(f"    {item_node.item.oz} {item_node.item.short_text}")
                print(f"      parent: {item_node.parent.label}")
```

### Ancestors and path

```python
node = tree.find_item("01.02.0030")

# All ancestors from root to parent (excludes self)
for ancestor in node.ancestors:
    print(f"  {ancestor.kind.value}: {ancestor.label}")

# Full path from root to self (includes self)
print(node.path)

# Human-readable breadcrumb
print(" > ".join(node.label_path))
```

### Sibling navigation

```python
node = tree.find_item("01.02.0010")
print(node.index)              # 0 (first among siblings)
print(node.next_sibling)       # BoQNode for the next item
print(node.prev_sibling)       # None (first item)
```

## Lookups

### Find item by OZ (O(1))

```python
node = tree.find_item("01.01.0010")
if node:
    print(node.item.short_text, node.item.total_price)
```

### Find category by rno

```python
node = tree.find_category("02")
if node:
    print(node.label, node.category.subtotal)
```

### Find all categories with same rno (multi-lot)

In multi-lot documents, the same rno can appear in different lots:

```python
nodes = tree.find_all_categories("01")
for n in nodes:
    lot_label = n.parent.label  # which lot this category belongs to
    print(f"  {lot_label}: {n.label}")
```

## Subtree Queries

Every `BoQNode` supports queries over its descendants:

```python
# All items under a specific category
rohbau = tree.find_category("01")
for item_node in rohbau.iter_items():
    print(item_node.item.oz)

# All categories (recursive)
for cat_node in tree.root.iter_categories():
    print(f"{'  ' * cat_node.depth}{cat_node.rno} {cat_node.label}")

# Find by predicate
expensive = tree.root.find_all(
    lambda n: n.kind == NodeKind.ITEM and n.item.total_price and n.item.total_price > 50000
)
for n in expensive:
    print(n.item.oz, n.item.total_price)
```

## Tree Traversal

### Depth-first (DFS)

```python
for node in tree.walk():
    indent = "  " * node.depth
    print(f"{indent}{node.kind.value}: {node.label}")
```

### Breadth-first (BFS)

```python
for node in tree.walk_bfs():
    print(f"[depth={node.depth}] {node.kind.value}: {node.label}")
```

## Type-Safe Model Access

Each node provides a type-safe accessor that raises `TypeError` if you use the wrong one:

```python
lot_node = tree.lots[0]
lot_node.lot           # Lot model — works
lot_node.item          # TypeError: Cannot access .item on a lot node

item_node = tree.find_item("01.01.0010")
item_node.item         # Item model — works
item_node.category     # TypeError: Cannot access .category on an item node
```

## Convenience Properties

These work on any node kind, giving you a unified interface:

| Property | ROOT | LOT | CATEGORY | ITEM |
|----------|------|-----|----------|------|
| `label` | `"BoQ"` | `lot.label` | `ctgy.label` | `item.short_text` |
| `rno` | `""` | `lot.rno` | `ctgy.rno` | `item.oz` |
| `label_path` | `["BoQ"]` | `["BoQ", "Default"]` | `["BoQ", ..., "Rohbau"]` | `["BoQ", ..., "Mauerwerk Innenwand"]` |

## Building a UI Tree

A common use case is rendering the BoQ as a hierarchical tree (React, Qt, etc.):

```python
def to_ui_tree(node):
    result = {
        "kind": node.kind.value,
        "label": node.label,
        "rno": node.rno,
        "depth": node.depth,
    }
    if node.kind == NodeKind.ITEM:
        result["oz"] = node.item.oz
        result["qty"] = str(node.item.qty)
        result["unit"] = node.item.unit
        result["total"] = str(node.item.total_price)
    if node.children:
        result["children"] = [to_ui_tree(child) for child in node.children]
    return result

tree_data = to_ui_tree(tree.root)
```

## Counts

```python
print(tree.node_count)   # Total nodes (root + lots + categories + items)
print(tree.item_count)   # Just items
print(tree.is_multi_lot) # True if > 1 lot
print(len(tree.lots))    # Number of lots
```

## Design Notes

- **Read-only** — `BoQNode.children` is a tuple (immutable). The tree API does not support mutation (move, detach, duplicate). This is planned for a future release.
- **Zero model impact** — The underlying `BoQ`, `Lot`, `BoQCtgy`, and `Item` models are not modified. `BoQNode.model` returns the exact same Pydantic object (same identity).
- **O(n) construction** — Building the tree is a single pass over all nodes. For a 10,000-item document, this takes < 5ms.
- **Opt-in** — If you never construct a `BoQTree`, the tree code never runs. There is no performance cost for users who don't need it.
- **Procurement BoQ only** — The current tree API works with `BoQ` from procurement documents. Cost (`ElementalCosting`) and quantity (`QtyDetermination`) tree adapters may be added in a future release.
