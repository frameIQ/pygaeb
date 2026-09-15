# Security Policy

## Supported versions

Security fixes are released against the latest published `1.x` version. Pin at
least the current minor and upgrade promptly when a fix is announced.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's **"Report a
vulnerability"** button under the Security tab of
[frameIQ/pygaeb](https://github.com/frameIQ/pygaeb/security), which opens a
private advisory visible only to the maintainers. Do not open a public issue for
a security report.

Include the affected version, a reproduction, and the impact you observed. We
aim to acknowledge within a few working days.

## Threat model

pyGAEB parses GAEB DA XML files that frequently originate from **external
parties** (a tender arrives from a client; a bid arrives from a competitor).
Parser input is therefore treated as untrusted. The optional MCP server
additionally treats every tool argument as untrusted, since a language model can
be steered by document content.

### Hardening in place

- **XML attacks (XXE, entity expansion, external DTDs).** Every parse — including
  recovery mode and XSD validation — uses an explicit lxml parser configured
  with `resolve_entities=False`, `no_network=True`, and `huge_tree=False`. The
  library never uses lxml's default parser on untrusted input. Billion-laughs,
  recursion depth, and file size are additionally guarded.
- **File size** is checked before reading, bounded by `PYGAEB_MAX_FILE_SIZE_MB`.
- **MCP server** is read-only by default over stdio, confined to an explicit
  roots allowlist (symlink-escape safe), with all heavy work off the event loop.
  See [docs/guides/mcp-server.md](docs/guides/mcp-server.md) → Security.

## Dependency advisories — pyGAEB's exposure

pyGAEB uses its dependencies in a narrow way, so several advisories that a
generic scanner flags against a transitive dependency **do not affect pyGAEB**.
The notable cases, documented so downstream reviewers do not have to
re-investigate:

| Advisory | Dependency | pyGAEB exposure |
|---|---|---|
| CVE-2026-41066 (lxml XXE via default parser) | `lxml` | **Not exposed.** pyGAEB always passes an explicit hardened parser; the vulnerable default-parser path is never used. |
| litellm proxy-server CVEs (RCE, auth bypass, SSRF in `/config/update`, JWT, team endpoints) | `litellm` | **Not exposed.** pyGAEB uses litellm purely as a client SDK for chat completion; it never runs or imports the proxy server. |
| GHSA-4xgf-cpjx-pc3j (pydantic-settings nested-secrets symlink escape) | `pydantic-settings` | **Not exposed.** pyGAEB reads configuration from environment variables only; it does not use `NestedSecretsSettingsSource`. |

These are documented as non-exposure, not dismissed: if pyGAEB's usage of any of
these libraries changes, this table must be revisited. Dependency floors are
kept current as hygiene regardless.
