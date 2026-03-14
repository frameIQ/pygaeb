"""Prompt builder for structured extraction — uses schema + classification context."""

from __future__ import annotations

from pydantic import BaseModel

from pygaeb.extractor.schema_utils import get_field_descriptions


def build_extraction_prompt(
    schema: type[BaseModel],
    element_type: str = "",
    trade: str = "",
) -> str:
    """Build a system prompt for structured attribute extraction.

    The classification result (trade/element_type) is injected as context
    to help the LLM focus on relevant attributes.
    """
    context_parts: list[str] = []
    if trade:
        context_parts.append(f"Trade: {trade}")
    if element_type:
        context_parts.append(f"Element type: {element_type}")
    context_line = ", ".join(context_parts) if context_parts else "Unknown"

    field_descriptions = get_field_descriptions(schema)
    fields_block = "\n".join(
        f"  - {desc}" for desc in field_descriptions.values()
    )

    return f"""\
You are extracting structured technical specifications from a German \
construction Bill of Quantities (Leistungsverzeichnis / GAEB) item.

This item has been classified as: {context_line}.

Extract the following attributes from the item text. The item text is in \
German — interpret DIN references, material specifications, abbreviations, \
and technical codes. If a value cannot be determined from the available text, \
leave it as null or use the default value.

Target schema fields:
{fields_block}

Guidelines:
- Parse German construction terms: Mauerwerk=Masonry, Putz=Plaster, \
Estrich=Screed, Brandschutz=Fire protection, Schallschutz=Sound insulation
- Interpret DIN/EN standards (e.g., DIN 4102-1 → fire resistance class)
- Extract numeric values with units when present (e.g., "240mm" → 240)
- Boolean fields: true if the feature is mentioned, false if absent or \
explicitly excluded
- For enum-like string fields, use concise English values"""


def build_extraction_user_message(
    hierarchy_path: str,
    short_text: str,
    long_text_head: str,
    unit: str,
    qty: str = "",
) -> str:
    """Build the user message containing the item's text signals."""
    parts = [f"Hierarchy: {hierarchy_path}"]
    if short_text:
        parts.append(f"Short text: {short_text}")
    if long_text_head:
        parts.append(f"Long text: {long_text_head}")
    if unit:
        parts.append(f"Unit: {unit}")
    if qty:
        parts.append(f"Quantity: {qty}")
    return "\n".join(parts)
