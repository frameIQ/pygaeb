"""Phase transition helpers for GAEB procurement workflow.

Create new documents from existing ones while respecting phase-specific
field rules. Each transition returns a deep copy — the original document
is never modified.

Usage::

    from pygaeb import PhaseTransition

    bid = PhaseTransition.tender_to_bid(tender)
    addendum = PhaseTransition.contract_to_addendum(contract, "NT-001")
    invoice = PhaseTransition.contract_to_invoice(contract)
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime

from pygaeb.models.document import GAEBDocument, GAEBInfo
from pygaeb.models.enums import ExchangePhase

logger = logging.getLogger("pygaeb.transition")


class PhaseTransition:
    """Create phase-transitioned documents from existing GAEB documents.

    Each method returns a **deep copy** — the source document is unchanged.
    """

    @staticmethod
    def tender_to_bid(source: GAEBDocument) -> GAEBDocument:
        """Create an X84 bid scaffold from an X83 tender.

        Preserves the full BoQ structure (lots, categories, items, OZ numbers,
        quantities, descriptions). Unit prices and total prices are cleared so
        the bidder can fill them in. The exchange phase is set to X84.

        Args:
            source: A parsed X83 tender document.

        Returns:
            A new GAEBDocument with phase X84 ready for price entry.
        """
        doc = copy.deepcopy(source)
        doc.exchange_phase = ExchangePhase.X84
        doc.gaeb_info = GAEBInfo(
            version=source.gaeb_info.version,
            prog_system="pyGAEB",
            date=datetime.now(),
        )
        doc.validation_results = []

        for item in doc.award.boq.iter_items():
            item.unit_price = None
            item.total_price = None

        logger.info(
            "Created X84 bid from X83 tender (%d items)",
            doc.item_count,
        )
        return doc

    @staticmethod
    def contract_to_addendum(
        source: GAEBDocument,
        change_order: str = "",
    ) -> GAEBDocument:
        """Create an X88 addendum (Nachtrag) scaffold from an X86 contract.

        Preserves the full BoQ structure. All items receive the given
        change order number (CONo) for traceability. New items can be added
        after creation via the editing API.

        Args:
            source: A parsed X86 contract document.
            change_order: Change order reference (e.g., "NT-001").

        Returns:
            A new GAEBDocument with phase X88.
        """
        doc = copy.deepcopy(source)
        doc.exchange_phase = ExchangePhase.X88
        doc.gaeb_info = GAEBInfo(
            version=source.gaeb_info.version,
            prog_system="pyGAEB",
            date=datetime.now(),
        )
        doc.validation_results = []

        if change_order:
            for item in doc.award.boq.iter_items():
                item.change_order_number = change_order

        logger.info(
            "Created X88 addendum from X86 contract (%d items, CONo=%s)",
            doc.item_count, change_order or "(none)",
        )
        return doc

    @staticmethod
    def contract_to_invoice(source: GAEBDocument) -> GAEBDocument:
        """Create an X89 invoice scaffold from an X86 contract.

        Preserves OZ numbers and unit prices from the contract. Quantities
        are carried over as initial executed quantities (Abrechnungsmenge)
        which the user can adjust to reflect actual work done.

        Args:
            source: A parsed X86 contract document.

        Returns:
            A new GAEBDocument with phase X89.
        """
        doc = copy.deepcopy(source)
        doc.exchange_phase = ExchangePhase.X89
        doc.gaeb_info = GAEBInfo(
            version=source.gaeb_info.version,
            prog_system="pyGAEB",
            date=datetime.now(),
        )
        doc.validation_results = []

        logger.info(
            "Created X89 invoice from X86 contract (%d items)",
            doc.item_count,
        )
        return doc
