"""Async wrappers for pyGAEB I/O operations.

The core parser is synchronous (lxml is sync). These wrappers run the
sync calls in a worker thread so they're safe to call from async code
(FastAPI, aiohttp, asyncio scripts) without blocking the event loop.

Usage::

    import asyncio
    from pygaeb import aparse, awrite

    async def main():
        doc = await aparse("tender.X83")
        await awrite(doc, "out.X83")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pygaeb.models.document import GAEBDocument


async def aparse(path: str | Path, **kwargs: Any) -> GAEBDocument:
    """Async wrapper for :meth:`GAEBParser.parse`.

    Runs the sync parser in a worker thread to avoid blocking the
    event loop. All keyword arguments are forwarded to ``parse()``.
    """
    from pygaeb.parser import GAEBParser
    return await asyncio.to_thread(GAEBParser.parse, path, **kwargs)


async def aparse_bytes(data: bytes, **kwargs: Any) -> GAEBDocument:
    """Async wrapper for :meth:`GAEBParser.parse_bytes`."""
    from pygaeb.parser import GAEBParser
    return await asyncio.to_thread(GAEBParser.parse_bytes, data, **kwargs)


async def awrite(
    doc: GAEBDocument, path: str | Path, **kwargs: Any,
) -> list[str]:
    """Async wrapper for :meth:`GAEBWriter.write`."""
    from pygaeb.writer import GAEBWriter
    return await asyncio.to_thread(GAEBWriter.write, doc, path, **kwargs)


__all__ = ["aparse", "aparse_bytes", "awrite"]
