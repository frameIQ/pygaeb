"""DA XML 3.2 compatibility — federal mandate, X89B invoice phase."""

from __future__ import annotations

from pygaeb.models.enums import ExchangePhase
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser


class V32Compat(BaseV3Parser):
    """DA XML 3.2 — the federal mandate version.

    New features:
    - X89B extended invoice phase (cumulative billing, partial invoices)
    - Additional procurement types
    """

    @staticmethod
    def supports_x89b() -> bool:
        return True

    @staticmethod
    def is_extended_invoice(phase: ExchangePhase) -> bool:
        return phase == ExchangePhase.X89B
