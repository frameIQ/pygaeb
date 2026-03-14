"""DA XML 3.0 compatibility — monolithic single-schema differences."""

from __future__ import annotations

from pygaeb.parser.xml_v3.base_v3_parser import BaseV3Parser


class V30Compat(BaseV3Parser):
    """DA XML 3.0 has a single monolithic schema (no per-phase XSDs).

    Minor differences from 3.2 baseline:
    - No X89B invoice phase
    - No Zeitvertrag phases (X83Z, X84Z, X86ZR, X86ZE)
    - Namespace may differ
    """
    pass
