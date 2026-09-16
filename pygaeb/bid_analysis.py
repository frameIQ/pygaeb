"""Bid analysis for GAEB Preisspiegel (X82) workflows.

Compare multiple bidder responses (X84) against a single tender (X83),
or analyze a Preisspiegel (X82) document carrying multiple bidder prices
per item.

Usage::

    from pygaeb import BidAnalysis, GAEBParser

    # From multiple X84 bid files
    tender = GAEBParser.parse("tender.X83")
    bids = {
        "Bidder A": GAEBParser.parse("bid_a.X84"),
        "Bidder B": GAEBParser.parse("bid_b.X84"),
        "Bidder C": GAEBParser.parse("bid_c.X84"),
    }
    analysis = BidAnalysis.from_x84_bids(tender, bids)
    print(analysis.ranking())             # [("Bidder A", 1234.56), ...]
    print(analysis.lowest_bidder)         # "Bidder A"
    print(analysis.price_spread("01.02.0010"))  # {"min": 45.50, "max": 52.00, ...}

    # From a Preisspiegel X82 document (if bidder_prices are populated)
    doc = GAEBParser.parse("preisspiegel.X82")
    analysis = BidAnalysis.from_x82(doc)

Prices are keyed by the full OZ (``"01.02.0010"``); the leaf ``RNoPart``
alone recurs in every category. Lookups accept a bare leaf when it is
unambiguous and raise ``ValueError`` when several positions share it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from decimal import Decimal

from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import BidderPrice, Item


def _effective_price(item: Item) -> BidderPrice:
    """One bidder's price row for *item*: stated total, else qty x unit price."""
    total = item.total_price if item.total_price is not None else item.computed_total
    return BidderPrice(
        unit_price=item.unit_price,
        total_price=total,
        affects_total=item.item_type.affects_total,
    )


class BidAnalysis:
    """Analysis of multiple bidder prices for tender comparison.

    Carries a per-item mapping of bidder names to their submitted prices,
    and exposes ranking, price spread, and per-item lookup methods.

    Construct via :meth:`from_x84_bids` or :meth:`from_x82`.
    """

    def __init__(
        self,
        tender: GAEBDocument,
        bidder_prices: dict[str, dict[str, BidderPrice]],
    ) -> None:
        """Initialize from a tender and a {bidder_name: {oz: BidderPrice}} mapping.

        Most callers should use :meth:`from_x84_bids` or :meth:`from_x82`
        instead of this constructor directly.
        """
        self.tender = tender
        self._by_bidder = bidder_prices
        # Ranks live on the analysis instance, NOT on the BidderPrice models.
        # Mutating shared model fields would pollute the source documents
        # when the same bid is reused across multiple analyses.
        self._ranks: dict[str, int] = {}

    @staticmethod
    def from_x84_bids(
        tender: GAEBDocument,
        bids: Mapping[str, GAEBDocument],
    ) -> BidAnalysis:
        """Build a BidAnalysis from a tender and a mapping of bidder X84 documents.

        Args:
            tender: The X83 tender document (used as the OZ reference).
            bids: Mapping of ``bidder_name -> bid_document``.

        Returns:
            A populated :class:`BidAnalysis`.
        """
        by_bidder: dict[str, dict[str, BidderPrice]] = {}
        for bidder_name, bid_doc in bids.items():
            prices: dict[str, BidderPrice] = {}
            for item in bid_doc.iter_items():
                bp = _effective_price(item)
                bp.bidder_name = bidder_name
                prices[item.full_oz] = bp
            by_bidder[bidder_name] = prices

        analysis = BidAnalysis(tender, by_bidder)
        analysis._compute_ranks()
        return analysis

    @staticmethod
    def from_x82(doc: GAEBDocument) -> BidAnalysis:
        """Build a BidAnalysis from a Preisspiegel (X82) document.

        Reads ``item.bidder_prices`` for each item and groups by bidder name.

        Args:
            doc: A parsed X82 document with populated ``bidder_prices``.

        Returns:
            A populated :class:`BidAnalysis`.
        """
        by_bidder: dict[str, dict[str, BidderPrice]] = {}
        for item in doc.iter_items():
            for bp in item.bidder_prices:
                if bp.bidder_name not in by_bidder:
                    by_bidder[bp.bidder_name] = {}
                # Defensive copy — never mutate models owned by the source doc
                row = copy.copy(bp)
                row.affects_total = item.item_type.affects_total
                by_bidder[bp.bidder_name][item.full_oz] = row

        analysis = BidAnalysis(doc, by_bidder)
        analysis._compute_ranks()
        return analysis

    def _compute_ranks(self) -> None:
        """Compute rank values (1 = lowest grand total) into ``_ranks``.

        Bidders who priced nothing sort last — a missing bid is not a zero bid.
        Ranks are stored on the analysis instance, never written back to the
        BidderPrice models, which may be shared with the source documents.
        """
        self._ranks = {name: rank for rank, (name, _) in enumerate(self.ranking(), start=1)}

    @staticmethod
    def _grand_total(prices: dict[str, BidderPrice]) -> Decimal:
        """Sum the totals that count toward the contract (VOB/A)."""
        return sum(
            (
                bp.total_price
                for bp in prices.values()
                if bp.total_price is not None and bp.affects_total
            ),
            Decimal("0"),
        )

    @staticmethod
    def _priced_count(prices: dict[str, BidderPrice]) -> int:
        return sum(1 for bp in prices.values() if bp.unit_price is not None)

    @property
    def bidders(self) -> list[str]:
        """Return all bidder names."""
        return list(self._by_bidder.keys())

    @property
    def lowest_bidder(self) -> str | None:
        """The bidder with the lowest grand total; None if nobody priced anything."""
        for name, _ in self.ranking():
            if self.priced_item_count(name):
                return name
        return None

    def ranking(self) -> list[tuple[str, Decimal]]:
        """Return [(bidder_name, grand_total), ...] sorted ascending by total.

        Bidders without a single priced item come last, whatever their (zero) total.
        """
        results = [
            (name, self._grand_total(prices), self._priced_count(prices) == 0)
            for name, prices in self._by_bidder.items()
        ]
        results.sort(key=lambda x: (x[2], x[1]))
        return [(name, total) for name, total, _ in results]

    def grand_total(self, bidder_name: str) -> Decimal | None:
        """Return the grand total for a specific bidder."""
        prices = self._by_bidder.get(bidder_name)
        if prices is None:
            return None
        return self._grand_total(prices)

    def priced_item_count(self, bidder_name: str) -> int:
        """How many positions this bidder gave a unit price for."""
        prices = self._by_bidder.get(bidder_name)
        return self._priced_count(prices) if prices is not None else 0

    def resolve_oz(self, oz: str) -> str | None:
        """The stored key for *oz*: exact, or the single position with that leaf.

        Raises ``ValueError`` when the leaf is shared by several positions.
        """
        keys = {k for prices in self._by_bidder.values() for k in prices}
        if oz in keys:
            return oz
        candidates = sorted(k for k in keys if k.endswith("." + oz))
        if len(candidates) > 1:
            raise ValueError(f"ambiguous OZ {oz!r}: {', '.join(candidates)}")
        return candidates[0] if candidates else None

    def price_spread(self, oz: str) -> dict[str, Decimal | int] | None:
        """Return min/max/avg/spread for unit prices on a given item.

        Args:
            oz: Item OZ to look up (full, or an unambiguous leaf).

        Returns:
            ``{"min": Decimal, "max": Decimal, "avg": Decimal,
            "spread": Decimal, "count": int}`` or ``None`` if no bidders
            priced this item.
        """
        key = self.resolve_oz(oz)
        if key is None:
            return None
        unit_prices: list[Decimal] = []
        for prices in self._by_bidder.values():
            bp = prices.get(key)
            if bp and bp.unit_price is not None:
                unit_prices.append(bp.unit_price)

        if not unit_prices:
            return None

        min_p = min(unit_prices)
        max_p = max(unit_prices)
        avg_p = sum(unit_prices, Decimal("0")) / Decimal(len(unit_prices))
        return {
            "min": min_p,
            "max": max_p,
            "avg": avg_p,
            "spread": max_p - min_p,
            "count": len(unit_prices),
        }

    def get_bidder_price(self, bidder_name: str, oz: str) -> BidderPrice | None:
        """Look up a specific bidder's price for a specific item.

        Returns a copy of the BidderPrice with ``rank`` populated from the
        analysis. The original model on the source document is never mutated.
        """
        prices = self._by_bidder.get(bidder_name)
        if prices is None:
            return None
        key = self.resolve_oz(oz)
        bp = prices.get(key) if key is not None else None
        if bp is None:
            return None
        result = copy.copy(bp)
        result.rank = self._ranks.get(bidder_name)
        return result

    def rank(self, bidder_name: str) -> int | None:
        """Return the rank (1 = lowest total) for a given bidder, or None."""
        return self._ranks.get(bidder_name)

    def items_priced_by_all(self) -> list[str]:
        """Return OZ list of items that all bidders priced (no missing items)."""
        if not self._by_bidder:
            return []
        priced_sets = [
            {oz for oz, bp in prices.items() if bp.unit_price is not None}
            for prices in self._by_bidder.values()
        ]
        return sorted(set.intersection(*priced_sets))
