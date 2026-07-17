"""Guided workflows exposed as MCP prompts.

Prompts are user-initiated templates and cost nothing until invoked. This is
where the drill-down discipline is encoded: left to itself a model will happily
try to read an entire tender, so each template says explicitly which tools to use
and in what order, and which mistakes to avoid.
"""

from __future__ import annotations

__all__ = ["bid_evaluation", "compare_tenders", "tender_review"]

_BUDGET_RULE = (
    "Work top-down and stay inside the context budget: expand one level at a "
    "time with list_structure, and never fetch long text in bulk."
)


def tender_review(handle: str) -> str:
    """Review a tender: structure, cost drivers, and data quality."""
    return f"""Review the GAEB tender already open as handle `{handle}`.

{_BUDGET_RULE}

Suggested approach:
1. Re-run `open_document` if you need the summary again — it is cached and free.
2. `list_structure(handle="{handle}")` for the top level. Follow `subtotal` and
   `item_count` into the expensive sections; do not expand everything.
3. `list_items(handle="{handle}", sort="total_desc", limit=20)` for the cost
   drivers. That is usually enough — resist paging through every item.
4. `list_validation_issues(handle="{handle}")` — read `counts` first and only
   page in if something looks wrong.
5. `get_item` for anything that needs explaining, and `get_item_long_text` only
   when the preview is genuinely insufficient.

Report: what the project is, what it costs, where the money is concentrated, and
any data-quality problems worth flagging. Cite OZ numbers for specific items."""


def compare_tenders(handle_a: str, handle_b: str) -> str:
    """Compare two revisions of a tender and explain what changed."""
    return f"""Compare GAEB documents `{handle_a}` (earlier) and `{handle_b}` (later).

{_BUDGET_RULE}

Suggested approach:
1. `compare_documents(handle_a="{handle_a}", handle_b="{handle_b}")` — start with
   `summary` and `counts`, and check `financial_impact` and `match_ratio`.
2. If there are many changes, re-run with `min_significance="high"` rather than
   paging through low-significance noise.
3. `get_item` on either handle for the changes that need context.

Report: whether these are the same project, the net financial impact, and the
changes that actually matter — grouped by theme, not listed one by one."""


def bid_evaluation(tender_handle: str, bid_handles: str) -> str:
    """Evaluate bids against a tender."""
    return f"""Evaluate bids for the tender open as `{tender_handle}`.

Bid handles: {bid_handles}

{_BUDGET_RULE}

Suggested approach:
1. `analyze_bids(tender_handle="{tender_handle}", bids=[{{"name": "...", "handle": "..."}}])`
   for the ranking and the lowest bidder. For an X82 Preisspiegel, omit `bids`.
2. `list_items(handle="{tender_handle}", sort="total_desc", limit=20)` to find the
   items that actually drive the total.
3. Re-run `analyze_bids` with `spread_for=[<those OZs>]` to see where bidders
   disagree most. Wide spreads on high-value items are where the risk is.

Report: the ranking, the spread on the items that matter, and any bid that looks
anomalous — unusually low on a big item often signals a misreading of the spec."""
