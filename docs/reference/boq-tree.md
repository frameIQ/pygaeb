# BoQ Tree API

Read-only tree adapter for navigating the BoQ hierarchy with parent references, depth tracking, and indexed lookups.

```python
from pygaeb import BoQTree, BoQNode, NodeKind

tree = BoQTree(doc.award.boq)
```

::: pygaeb.api.boq_tree.NodeKind
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.api.boq_tree.BoQNode
    options:
      show_root_heading: true
      members_order: source

::: pygaeb.api.boq_tree.BoQTree
    options:
      show_root_heading: true
      members_order: source
