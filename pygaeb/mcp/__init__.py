"""MCP (Model Context Protocol) server for pyGAEB.

Exposes GAEB documents to LLM agents — ChatGPT, Gemini, Claude, Copilot, Cursor
and any other MCP client — over a bounded, query-oriented tool surface.

MCP is a vendor-neutral standard (stewarded by the Agentic AI Foundation), and
this server calls no model itself: it speaks JSON-RPC over stdio and the client
owns the model relationship. There is no provider coupling and no API key.

Install with::

    pip install pyGAEB[mcp]

Run via the console script::

    pygaeb-mcp --root ~/tenders

Nothing in this package imports the MCP SDK except :mod:`pygaeb.mcp.server`, and
that import is function-local — so importing ``pygaeb`` never pulls in the SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from pygaeb.mcp.server import create_server, main

__all__ = ["create_server", "main"]


def __getattr__(name: str) -> Any:
    """Lazily resolve the server entry points (mirrors ``pygaeb.__getattr__``)."""
    if name in __all__:
        import importlib

        return getattr(importlib.import_module("pygaeb.mcp.server"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
