"""The MCP server adapter.

This is the **only** module in ``pygaeb.mcp`` that imports the MCP SDK, and the
import is function-local. Everything else — tools, views, handles, safety —
depends on ``pygaeb`` and ``pydantic`` alone, which is what lets the surface be
unit-tested without the SDK installed and keeps ``import pygaeb`` free of it.

Because the guard runs at call time, the ``FastMCP`` instance is built inside
:func:`create_server` and tools are registered imperatively via ``add_tool``
rather than with module-level decorators. That is load-bearing, not stylistic.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from pygaeb.config import get_settings
from pygaeb.mcp.handles import DocumentCache
from pygaeb.mcp.prompts import bid_evaluation, compare_tenders, tender_review
from pygaeb.mcp.safety import resolve_roots
from pygaeb.mcp.tools import ToolContext, build_tools

__all__ = ["create_server", "main"]

_INSTRUCTIONS = """\
Read and analyse German GAEB DA XML construction documents (bills of quantities,
bids, invoices, cost estimates).

Start with `open_document` to get a handle; every other tool takes that handle.
If you do not know the file name, `list_documents` shows what can be opened. A
bare file name is looked up under the allowed roots.

These documents are large — a tender can hold thousands of items and megabytes of
specification prose. The tools are therefore query-oriented, not dump-oriented:
they return summaries, counts, and pages. Work top-down (`list_structure`, then
`list_items`, then `get_item`) rather than trying to read everything. Every list
response carries `total_matched` and `has_more` so you can tell what you have not
seen.\
"""


def _ensure_mcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError:
        raise ImportError(
            "The MCP server requires the 'mcp' extra: pip install pyGAEB[mcp]"
        ) from None


def create_server(
    roots: list[str] | None = None,
    *,
    allow_write: bool | None = None,
    output_dir: str | None = None,
    allow_any_extension: bool = False,
    name: str = "pygaeb",
) -> Any:
    """Build a configured ``FastMCP`` server exposing the pyGAEB tools.

    Useful programmatically as well as via the ``pygaeb-mcp`` console script — a
    larger application can build this and mount it alongside its own tools.

    Args:
        roots: Directories the server may read GAEB files from. Defaults to
            ``PYGAEB_MCP_ROOTS`` or the process working directory.
        allow_write: Register the write tools (``export_document``,
            ``convert_document``). Defaults to ``PYGAEB_MCP_ALLOW_WRITE``.
        output_dir: The only directory writes may target. Required when
            *allow_write* is true.
        allow_any_extension: Skip the GAEB extension allowlist on input paths.
        name: Server name reported to the client.

    Returns:
        A ``FastMCP`` instance with the tools and prompts registered.

    Raises:
        ImportError: If the ``mcp`` extra is not installed.
        ValueError: If a root is missing, or writes are enabled without a valid
            output directory.
    """
    fast_mcp = _ensure_mcp()
    settings = get_settings()

    resolved_roots = resolve_roots(roots)
    write_enabled = settings.mcp_allow_write if allow_write is None else allow_write

    resolved_output: Path | None = None
    if write_enabled:
        raw_output = output_dir or settings.mcp_output_dir
        if not raw_output:
            raise ValueError(
                "Write tools need an output directory: pass --output-dir "
                "(or set PYGAEB_MCP_OUTPUT_DIR)."
            )
        resolved_output = Path(raw_output).expanduser().resolve()
        if not resolved_output.is_dir():
            raise ValueError(f"Output directory does not exist: {resolved_output}")

    ctx = ToolContext(
        cache=DocumentCache(),
        roots=resolved_roots,
        allow_any_extension=allow_any_extension,
        allow_write=write_enabled,
        output_dir=resolved_output,
    )

    # Safe to import here: _ensure_mcp() above proved the SDK is installed.
    from mcp.types import ToolAnnotations

    # Clients gate their confirmation UX on these hints — without them, a
    # read-only drill-down call looks indistinguishable from a mutating one and
    # may cost the user an approval prompt per step. The write tools honestly
    # declare destructiveHint=True because they may overwrite an existing file
    # inside --output-dir.
    read_annotations = ToolAnnotations(
        readOnlyHint=True, idempotentHint=True, openWorldHint=False
    )
    write_annotations = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
    )
    write_tool_names = {"export_document", "convert_document"}

    server = fast_mcp(name, instructions=_INSTRUCTIONS)
    for tool in build_tools(ctx):
        is_write = tool.__name__ in write_tool_names
        server.add_tool(
            tool, annotations=write_annotations if is_write else read_annotations
        )
    for prompt in (tender_review, compare_tenders, bid_evaluation):
        server.prompt()(prompt)
    return server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pygaeb-mcp",
        description="Expose GAEB documents to LLM agents over the Model Context Protocol.",
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        metavar="DIR",
        help="Directory the server may read from. Repeatable. "
        "Defaults to PYGAEB_MCP_ROOTS or the working directory.",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        default=None,
        help="Register the export/convert tools. Requires --output-dir.",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        help="The only directory writes may target.",
    )
    parser.add_argument(
        "--allow-any-extension",
        action="store_true",
        help="Accept input files that do not look like GAEB files.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport. stdio (the default) keeps the server local to one client.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point for ``pygaeb-mcp``.

    Uses argparse rather than click so the ``mcp`` extra does not drag in the
    ``cli`` extra.
    """
    args = _build_parser().parse_args(argv)

    if args.transport != "stdio" and not args.roots and not get_settings().mcp_roots:
        raise SystemExit(
            "Refusing to serve over a network transport with the working directory "
            "as the root. Pass --root explicitly."
        )

    server = create_server(
        roots=args.roots,
        allow_write=args.allow_write,
        output_dir=args.output_dir,
        allow_any_extension=args.allow_any_extension,
    )
    server.run(transport=args.transport)


if __name__ == "__main__":  # pragma: no cover
    main()
