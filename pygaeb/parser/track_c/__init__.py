"""Track C — GAEB 90 fixed-width format parser.

GAEB 90 is the legacy 80-character fixed-width format that predates DA XML.
This parser provides minimal support for the most common record types so
that legacy ``.P83``/``.P84`` files from long-running infrastructure projects
can be read into the unified GAEBDocument model.
"""
