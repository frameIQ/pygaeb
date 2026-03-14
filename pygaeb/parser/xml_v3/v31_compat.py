"""DA XML 3.1 compatibility — per-phase XSD routing, Zeitvertrag phases."""

from __future__ import annotations

from pygaeb.models.enums import ExchangePhase
from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser

_ZEITVERTRAG_PHASES = {
    ExchangePhase.X83Z,
    ExchangePhase.X84Z,
    ExchangePhase.X86ZR,
    ExchangePhase.X86ZE,
}


class V31Compat(BaseV3Parser):
    """DA XML 3.1 added per-phase XSD routing and Zeitvertrag phases.

    Three date variants exist (all handled transparently by the base parser).
    """

    @staticmethod
    def is_zeitvertrag(phase: ExchangePhase) -> bool:
        return phase in _ZEITVERTRAG_PHASES
