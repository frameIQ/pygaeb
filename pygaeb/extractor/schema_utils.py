"""Schema utilities: hashing, field introspection, completeness scoring."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def compute_schema_hash(schema: type[BaseModel]) -> str:
    """Deterministic hash of a Pydantic model's JSON schema.

    Changes when the user modifies their schema — triggers cache miss.
    """
    json_schema = schema.model_json_schema()
    canonical = json.dumps(json_schema, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_extraction_cache_key(
    item_text_hash: str,
    schema_hash: str,
) -> str:
    """Cache key combining item text hash + schema hash."""
    combined = f"{item_text_hash}:{schema_hash}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def get_schema_name(schema: type[BaseModel]) -> str:
    """Human-readable name of the schema class."""
    return schema.__name__


def get_field_descriptions(schema: type[BaseModel]) -> dict[str, str]:
    """Extract field name → description mapping from Pydantic model.

    Uses Field(description=...) if provided, otherwise the field type annotation.
    """
    descriptions: dict[str, str] = {}
    for name, field_info in schema.model_fields.items():
        desc = field_info.description or ""
        annotation = str(field_info.annotation) if field_info.annotation else ""
        default = field_info.default
        parts = [name]
        if desc:
            parts.append(f"({desc})")
        if annotation:
            parts.append(f"[{annotation}]")
        if default is not None and default is not ...:
            parts.append(f"default={default!r}")
        descriptions[name] = " ".join(parts)
    return descriptions


def compute_completeness(instance: BaseModel) -> float:
    """Score how many fields were populated vs total optional fields.

    Fields with non-default, non-None values count as populated.
    Returns 0.0-1.0.
    """
    total = 0
    populated = 0

    for name, field_info in type(instance).model_fields.items():
        total += 1
        value = getattr(instance, name)
        default = field_info.default

        if value is None:
            continue
        if value == default and default is not None:
            continue
        if isinstance(value, str) and value == "":
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue

        populated += 1

    return populated / total if total > 0 else 0.0


def schema_field_summary(schema: type[BaseModel]) -> str:
    """One-line summary of schema fields for logging."""
    fields = list(schema.model_fields.keys())
    if len(fields) <= 5:
        return ", ".join(fields)
    return f"{', '.join(fields[:4])}, ... ({len(fields)} fields)"
