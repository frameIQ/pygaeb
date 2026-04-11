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
    print(analysis.price_spread("01.0010"))  # {"min": 45.50, "max": 52.00, ...}

    # From a Preisspiegel X82 document (if bidder_prices are populated)
    doc = GAEBParser.parse("preisspiegel.X82")
    analysis = BidAnalysis.from_x82(doc)
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from decimal import Decimal

from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import BidderPrice


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
                prices[item.oz] = BidderPrice(
                    bidder_name=bidder_name,
                    unit_price=item.unit_price,
                    total_price=item.total_price,
                )
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
                by_bidder[bp.bidder_name][item.oz] = copy.copy(bp)

        analysis = BidAnalysis(doc, by_bidder)
        analysis._compute_ranks()
        return analysis

    def _compute_ranks(self) -> None:
        """Compute rank values (1 = lowest grand total) into ``_ranks``.

        Ranks are stored on the analysis instance — never written back to
        the BidderPrice models, which may be shared with the source bid
        documents.
        """
        sorted_bidders = sorted(
            self._by_bidder.items(),
            key=lambda kv: self._grand_total(kv[1]),
        )
        self._ranks = {
            name: rank
            for rank, (name, _) in enumerate(sorted_bidders, start=1)
        }

    @staticmethod
    def _grand_total(prices: dict[str, BidderPrice]) -> Decimal:
        """Sum all total_price values from a bidder's price set."""
        return sum(
            (bp.total_price for bp in prices.values() if bp.total_price is not None),
            Decimal("0"),
        )

    @property
    def bidders(self) -> list[str]:
        """Return all bidder names."""
        return list(self._by_bidder.keys())

    @property
    def lowest_bidder(self) -> str | None:
        """Return the bidder name with the lowest grand total, or None if no bidders."""
        ranking = self.ranking()
        return ranking[0][0] if ranking else None

    def ranking(self) -> list[tuple[str, Decimal]]:
        """Return [(bidder_name, grand_total), ...] sorted ascending by total."""
        results = [
            (name, self._grand_total(prices))
            for name, prices in self._by_bidder.items()
        ]
        results.sort(key=lambda x: x[1])
        return results

    def grand_total(self, bidder_name: str) -> Decimal | None:
        """Return the grand total for a specific bidder."""
        prices = self._by_bidder.get(bidder_name)
        if prices is None:
            return None
        return self._grand_total(prices)

    def price_spread(self, oz: str) -> dict[str, Decimal | int] | None:
        """Return min/max/avg/spread for unit prices on a given item.

        Args:
            oz: Item OZ to look up.

        Returns:
            ``{"min": Decimal, "max": Decimal, "avg": Decimal,
            "spread": Decimal, "count": int}`` or ``None`` if no bidders
            priced this item.
        """
        unit_prices: list[Decimal] = []
        for prices in self._by_bidder.values():
            bp = prices.get(oz)
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
        bp = prices.get(oz)
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
