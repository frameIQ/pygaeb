"""Filesystem safety for the MCP server.

Every path the server accepts originates from an LLM, so it is untrusted input.
``resolve_within_roots`` is the single choke point: it resolves the path (which
also resolves symlinks), checks containment against an allowlist of roots,
checks the extension, and checks the size — in that order, before any bytes are
read.

XXE, billion-laughs, and recursion depth are already handled upstream by
:mod:`pygaeb.parser._xml_safety`; nothing here duplicates that.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from pygaeb.config import get_settings

__all__ = [
    "DEFAULT_EXTENSION_PATTERN",
    "is_gaeb_suffix",
    "resolve_output_path",
    "resolve_roots",
    "resolve_within_roots",
]

# GAEB extensions: X8x / D8x / P8x, plus real phase variants that carry a
# suffix (e.g. .X86ZE — GAEB publishes a GAEB_DA_XML_86ZE schema). Any case.
DEFAULT_EXTENSION_PATTERN = re.compile(r"^\.[xdp]\d{2}[a-z]{0,2}$", re.IGNORECASE)

_EXTRA_ALLOWED_SUFFIXES = frozenset({".xml", ".gaeb"})


def is_gaeb_suffix(suffix: str) -> bool:
    """Whether a file extension is on the GAEB allowlist (``.X83``, ``.xml``, …)."""
    return (
        DEFAULT_EXTENSION_PATTERN.match(suffix) is not None
        or suffix.lower() in _EXTRA_ALLOWED_SUFFIXES
    )


def _resolve_untrusted(path: str, bases: list[Path]) -> Path:
    """Resolve an LLM-supplied path, anchoring relative ones to *bases*.

    The server's working directory is meaningless to the model — desktop
    clients spawn it from ``/`` — so a bare ``tender.X83`` is tried under each
    base in order and the first existing match wins. Absolute paths (and ``~``)
    resolve as given. A relative path that exists under no base resolves
    against the first base, so the caller's "does not exist" error names a
    sensible location.
    """
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    for base in bases:
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    return (bases[0] / candidate).resolve()


def resolve_roots(roots: list[str] | None = None) -> list[Path]:
    """Resolve the allowlist of directories the server may read from.

    Precedence: *roots* (CLI) > ``PYGAEB_MCP_ROOTS`` env/settings > the process
    working directory.

    Args:
        roots: Explicit root directories, typically from ``--root``.

    Returns:
        Absolute, resolved directories.

    Raises:
        ValueError: If a configured root does not exist or is not a directory.
    """
    if not roots:
        configured = get_settings().mcp_roots
        roots = configured.split(os.pathsep) if configured else [str(Path.cwd())]

    resolved: list[Path] = []
    for raw in roots:
        if not raw.strip():
            continue
        root = Path(raw).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Root is not an existing directory: {root}")
        resolved.append(root)

    if not resolved:
        raise ValueError("No usable roots configured.")
    return resolved


def _check_containment(resolved: Path, roots: list[Path], label: str) -> None:
    if any(resolved.is_relative_to(root) for root in roots):
        return
    allowed = ", ".join(str(r) for r in roots)
    raise ValueError(
        f"{label} is outside the allowed roots. Allowed: {allowed}. "
        f"Start the server with --root to widen access."
    )


def resolve_within_roots(
    path: str,
    roots: list[Path],
    *,
    allow_any_extension: bool = False,
) -> Path:
    """Validate an untrusted read path and return its resolved form.

    Relative paths are anchored to the roots, not to the process working
    directory. ``Path.resolve()`` runs *before* the containment check, so a
    symlink inside a root that points outside it is rejected rather than
    followed.

    Args:
        path: The untrusted path.
        roots: Allowed directories, from :func:`resolve_roots`.
        allow_any_extension: Skip the GAEB extension allowlist.

    Returns:
        The resolved, validated path.

    Raises:
        ValueError: If the path escapes the roots, does not exist, is not a
            file, has a non-GAEB extension, or exceeds ``max_file_size_mb``.
    """
    resolved = _resolve_untrusted(path, roots)
    _check_containment(resolved, roots, "Path")

    if not resolved.exists():
        raise ValueError(
            f"File does not exist: {resolved}. Use list_documents to see the files "
            f"under the allowed roots."
        )
    if not resolved.is_file():
        raise ValueError(f"Not a file: {resolved}")

    if not allow_any_extension:
        suffix = resolved.suffix
        if not is_gaeb_suffix(suffix):
            raise ValueError(
                f"Unrecognised GAEB extension {suffix!r}. Expected .X83/.D83/.P83-style, "
                f".xml, or .gaeb. Use --allow-any-extension to override."
            )

    # Fail before read_bytes(); the parser's own guard is the backstop.
    max_mb = get_settings().max_file_size_mb
    size_mb = resolved.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        raise ValueError(
            f"File is {size_mb:.1f} MB, over the {max_mb} MB limit "
            f"(PYGAEB_MAX_FILE_SIZE_MB)."
        )

    return resolved


def resolve_output_path(path: str, output_dir: Path) -> Path:
    """Validate an untrusted write path against the configured output directory.

    Unlike :func:`resolve_within_roots` the target need not exist, but its parent
    must, and the resolved location must sit inside *output_dir*. Relative
    paths are anchored to *output_dir*.

    Args:
        path: The untrusted destination path.
        output_dir: The only directory writes are permitted under.

    Returns:
        The resolved, validated destination.

    Raises:
        ValueError: If the destination escapes *output_dir* or its parent is missing.
    """
    resolved = _resolve_untrusted(path, [output_dir])
    _check_containment(resolved, [output_dir], "Output path")

    if not resolved.parent.is_dir():
        raise ValueError(f"Parent directory does not exist: {resolved.parent}")
    if resolved.is_dir():
        raise ValueError(f"Output path is a directory: {resolved}")

    return resolved
