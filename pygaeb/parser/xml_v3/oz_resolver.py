"""OZ (Ordnungszahl) resolver: splits OZ strings into hierarchy segments per BoQBkdn rules."""

from __future__ import annotations

from pygaeb.models.boq import BoQBkdn


def resolve_oz(oz: str, bkdn: list[BoQBkdn]) -> list[str]:
    """Split a flat OZ string into hierarchy segments based on BoQBkdn length rules.

    Example:
        oz = "01.02.0030"
        bkdn = [BoQBkdn(type=Lot, length=2), BoQBkdn(type=BoQLevel, length=2),
                BoQBkdn(type=Item, length=4)]
        → ["01", "02", "0030"]
    """
    if not bkdn:
        return _split_by_dots(oz)

    cleaned = oz.replace(".", "").replace(" ", "")
    segments: list[str] = []
    pos = 0

    for level in bkdn:
        end = pos + level.length
        if end > len(cleaned):
            seg = cleaned[pos:]
            if seg:
                segments.append(seg)
            break
        segments.append(cleaned[pos:end])
        pos = end

    if pos < len(cleaned):
        segments.append(cleaned[pos:])

    return [s for s in segments if s]


def format_oz(segments: list[str], separator: str = ".") -> str:
    """Re-join OZ segments with the given separator."""
    return separator.join(segments)


def build_hierarchy_path(
    oz: str,
    bkdn: list[BoQBkdn],
    category_labels: dict[str, str],
) -> list[str]:
    """Build a human-readable hierarchy path from OZ + category labels.

    Returns labels for each level, falling back to the OZ segment.
    """
    segments = resolve_oz(oz, bkdn)
    path: list[str] = []
    running = ""
    for seg in segments[:-1]:
        running = f"{running}.{seg}" if running else seg
        label = category_labels.get(running, seg)
        path.append(label)
    return path


def _split_by_dots(oz: str) -> list[str]:
    """Fallback: split OZ by dots."""
    return [s for s in oz.split(".") if s]
