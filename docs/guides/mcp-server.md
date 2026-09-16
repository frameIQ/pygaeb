# MCP Server

Expose GAEB documents to LLM agents over the [Model Context Protocol](https://modelcontextprotocol.io) — ChatGPT, Gemini, Claude, Copilot, Cursor, or any other MCP client.

MCP is a vendor-neutral standard stewarded by the Agentic AI Foundation. **pyGAEB's server calls no model itself**: it speaks JSON-RPC over stdio and the client owns the model relationship. There is no provider coupling, no API key, and no `anthropic`/`openai` dependency.

## Installation

```bash
pip install pyGAEB[mcp]
```

Requires Python 3.10+.

## Quick Start

The server is a **local subprocess**, not a hosted service — your MCP client spawns it. There is nothing to deploy.

```bash
claude mcp add pygaeb -- pygaeb-mcp --root ~/tenders
```

Or configure it directly (`claude_desktop_config.json`, or your client's equivalent):

```json
{
  "mcpServers": {
    "pygaeb": {
      "command": "pygaeb-mcp",
      "args": ["--root", "/Users/you/tenders"]
    }
  }
}
```

Then ask your assistant:

> What's the grand total of tender.X83, and which five items cost the most?

It will call `open_document`, then `list_items(sort="total_desc", limit=5)`.

## Tool Reference

Every tool except `list_documents` and `open_document` takes a `handle`.

| Tool | Purpose | Bounding |
|---|---|---|
| `list_documents` | GAEB files under the allowed roots, so the model can find a file by name | paginated; scan capped at 5 000 files |
| `open_document` | Parse a file, return a handle + summary | ~25 scalars, fixed size |
| `list_structure` | Direct children of a level, with `item_count` and `subtotal` | paginated, `depth=1` |
| `list_items` | Filtered, sorted item rows | paginated; no long text |
| `get_item` | One item in full | long text previewed to 500 chars |
| `get_item_long_text` | Full specification prose | explicit character paging |
| `search_items` | Find text, return ±80-char snippets | paginated; windows, not fields |
| `list_validation_issues` | Parse problems | counts always; entries paginated |
| `compare_documents` | Diff two procurement docs | counts + paginated change stream |
| `analyze_bids` | Rank bidders, price spreads | ranking + capped spreads |

Two more appear only with `--allow-write`: `export_document` and `convert_document`.

**Paths.** A bare file name such as `tender.X83` is looked up under each `--root` in order, never against the server's working directory (desktop clients spawn the server from `/`). Absolute paths work as given, and `open_document` accepts the `path` values that `list_documents` returns. Write tools resolve relative destinations against `--output-dir`.

**Unpriced tenders.** An X83 before bids has no prices. `open_document` then reports `is_priced: false` and `grand_total: null` rather than `"0"`, and `list_items` returns `sum_of_matched_totals: null`, so an assistant cannot mistake a blank tender for a free one.

## Context Budget

This is the part that matters, and it is what makes the server usable on real files.

A GAEB tender serialized whole is megabytes — thousands of items, unbounded specification prose, and binary attachments. A tool that returned a document would exhaust an LLM's context window on the first call. So the surface is **query-oriented, not dump-oriented**.

**Never returned, under any circumstance:**

- `Attachment.data` — attachments are projected to `{filename, mime_type, size_bytes}` only.
- `Item.raw_data`, `source_element`, `xml_root`.
- A whole-document JSON dump. `to_json_string()` is not exposed to any tool.

**Always truncated, with the true length reported:**

| Field | Limit | Companion |
|---|---|---|
| `short_text` | 120 chars | `short_text_chars` |
| `long_text_preview` | 500 chars | `long_text_chars` |
| validation `message` | 200 chars | `message_chars` |

**Always paginated.** Every list tool takes `offset`/`limit` (default 50, hard cap 200) and returns `total_matched` — the size of the *whole* match set, not the page — plus `has_more`. You can always tell what you did not see.

**Backstop.** Responses are capped at `PYGAEB_MCP_MAX_RESPONSE_CHARS` (default 20 000). If a payload would exceed it, trailing list entries are dropped and `truncated: true` is set. Text windows are clamped against the same budget.

The practical upshot: `list_items(sort="total_desc", limit=20)` answers "where is the money?" on a 5 000-item tender in about 2 KB.

## Handles & Caching

`open_document` parses once and returns a handle derived from the file's path, mtime, size, and validation mode.

- **Idempotent** — re-opening an unchanged file returns the same handle with no re-parse, and `cached: true`.
- **Never stale** — if the file changes on disk, the handle changes.
- **Bounded** — an LRU capped by both document count (default 8) and total megabytes (default 512).
- **No auto-rehydration** — an evicted handle raises with an actionable message rather than silently re-parsing 50 MB inside an unrelated call.

The cache lives for the life of the process, which under stdio is exactly one client session.

## Security

- **One choke point.** `open_document` is the only read tool that accepts a path; everything else takes a handle. `list_documents` takes no path at all — it only ever walks the configured roots, skipping hidden directories and symlinks.
- **Roots allowlist.** `--root` (repeatable) or `PYGAEB_MCP_ROOTS`. Paths are resolved *before* the containment check, so a symlink inside a root pointing outside it is rejected.
- **Extension allowlist.** `.X83`/`.D83`/`.P83`-style, `.xml`, `.gaeb`. Override with `--allow-any-extension`.
- **Size limit.** Enforced against `PYGAEB_MAX_FILE_SIZE_MB` before any bytes are read.
- **XXE and friends** are already handled by the parser's safety layer.
- **Writes are off by default.** `--allow-write` requires `--output-dir`, and writes may not escape it.
- **Client-supplied roots are not consumed (deliberate, v1).** MCP clients can advertise user-granted directories via the protocol's roots capability; this server honours only its own `--root` allowlist and ignores client-supplied roots. Configure `--root` as the single source of truth. Intersecting the two would tighten this further and is a candidate for a future release.

!!! note "What actually leaves your machine"
    The **file** never leaves — there is no upload. But the bounded query results the model reads do reach your MCP client's model provider. The context budget shrinks that from megabytes to kilobytes, which is a real difference, but it is not zero. For fully-local processing, use the library directly, or point the [classification](classification.md) layer at a local model via Ollama.

## Transports

stdio is the default and the right choice: the client and the files share a machine and a trust domain, and the cache has one obvious owner and lifetime.

```bash
pygaeb-mcp --transport streamable-http --root /srv/tenders
```

is available for containerised deployments, but it turns a local file reader into a remote one — the roots allowlist becomes the only barrier between a network peer and the disk. The server refuses to start on a network transport without an explicit `--root`.

!!! warning "The HTTP transports carry no authentication"
    `sse` and `streamable-http` expose the tools to anyone who can reach the port — there is no built-in auth, and every session shares one document cache. Never bind them to an untrusted network; put a reverse proxy with authentication in front, or stay on stdio.

## Prompts

Three guided workflows: `tender_review`, `compare_tenders`, and `bid_evaluation`. They encode the drill-down discipline, so the model expands one level at a time instead of trying to read everything.

## Programmatic use

`create_server()` returns a configured `FastMCP` instance, so you can mount pyGAEB's tools inside a larger server:

```python
from pygaeb import create_server

server = create_server(roots=["/srv/tenders"])
server.run()  # stdio
```

## Configuration

| Setting | Env var | Default |
|---|---|---|
| `mcp_roots` | `PYGAEB_MCP_ROOTS` | working directory |
| `mcp_allow_write` | `PYGAEB_MCP_ALLOW_WRITE` | `false` |
| `mcp_output_dir` | `PYGAEB_MCP_OUTPUT_DIR` | — |
| `mcp_max_open_documents` | `PYGAEB_MCP_MAX_OPEN_DOCUMENTS` | `8` |
| `mcp_max_cache_mb` | `PYGAEB_MCP_MAX_CACHE_MB` | `512` |
| `mcp_max_page_size` | `PYGAEB_MCP_MAX_PAGE_SIZE` | `200` |
| `mcp_max_response_chars` | `PYGAEB_MCP_MAX_RESPONSE_CHARS` | `20000` |

CLI flags take precedence over environment variables. `--xsd-dir DIR` (or
`PYGAEB_XSD_DIR`) points at the official GAEB DA XML schemas so every
`open_document` also validates against the XSD; without it the summary carries
one info note saying schema validation was skipped.

## Troubleshooting

**"Unknown or expired handle"** — the document was evicted from the cache, or the file changed. Call `open_document` again.

**"Path is outside the allowed roots"** — add the directory with `--root`.

**"File does not exist"** — the name was looked up under every root and not found. Ask the assistant to run `list_documents`, or check the spelling.

**"Unrecognised GAEB extension"** — pass `--allow-any-extension`, or rename the file.

**"is a quantity document and has no bill-of-quantities structure"** — `list_structure`, `get_item`, and `compare_documents` are procurement-only. Use `list_items`, which works across all document kinds.
