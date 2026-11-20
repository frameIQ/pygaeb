"""Track C — GAEB 90 fixed-width format parser.

GAEB 90 is the legacy 80-character fixed-width format that predates DA XML.
This parser provides minimal support for the most common record types so
that legacy ``.D8x`` files from long-running infrastructure projects can be
read into the unified GAEBDocument model. ``.P8x`` is GAEB 2000, a different
format that pyGAEB does not read.
"""
