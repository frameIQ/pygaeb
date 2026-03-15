"""Shared catalog models used across all GAEB document kinds.

``CtlgAssign`` and ``Catalog`` are defined in the common GAEB Lib schema
(``tgCtlgAssign``, ``tgCtlg``) and appear in procurement, trade, cost,
and quantity determination documents.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class CtlgAssign(BaseModel):
    """Catalog assignment — links an item/category to a catalog entry.

    Used at BoQ, category, item, and measurement-row levels across
    all GAEB document kinds.
    """

    ctlg_id: str = ""
    ctlg_code: str = ""
    quantity: Decimal | None = None


class Catalog(BaseModel):
    """Catalog definition (DIN 276 cost groups, BIM, locality, work category, etc.)."""

    ctlg_id: str = ""
    ctlg_type: str = ""
    ctlg_name: str = ""
    assign_type: str = ""
