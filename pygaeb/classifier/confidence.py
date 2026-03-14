"""Confidence scoring and flag routing."""

from __future__ import annotations

from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import ClassificationResult


def apply_confidence_flag(result: ClassificationResult) -> ClassificationResult:
    """Apply confidence-based flag to a classification result."""
    if result.flag == ClassificationFlag.MANUAL_OVERRIDE:
        return result

    if result.confidence >= 0.85:
        result.flag = ClassificationFlag.AUTO_CLASSIFIED
    elif result.confidence >= 0.60:
        result.flag = ClassificationFlag.NEEDS_SPOT_CHECK
    else:
        result.flag = ClassificationFlag.NEEDS_REVIEW

    return result


def merge_with_override(
    llm_result: ClassificationResult,
    override: ClassificationResult | None,
) -> ClassificationResult:
    """Prefer manual override over LLM result."""
    if override and override.flag == ClassificationFlag.MANUAL_OVERRIDE:
        return override
    return llm_result
