"""LLM backend using LiteLLM + instructor for structured ClassificationResult output."""

from __future__ import annotations

import logging

from pygaeb.classifier.confidence import apply_confidence_flag
from pygaeb.classifier.prompt_templates import get_prompt
from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import ClassificationResult

logger = logging.getLogger("pygaeb.classifier")


async def classify_single_item(
    model: str,
    hierarchy_path: str,
    short_text: str,
    long_text_head: str,
    unit: str,
    prompt_version: str = "v1",
    max_retries: int = 2,
    fallbacks: list[str] | None = None,
) -> ClassificationResult:
    """Classify a single construction item using LiteLLM + instructor.

    Returns a validated ClassificationResult — guaranteed by instructor.
    """
    try:
        import instructor
        import litellm
    except ImportError as err:
        raise ImportError(
            "LLM classification requires the 'llm' extra: pip install pyGAEB[llm]"
        ) from err

    client = instructor.from_litellm(litellm.acompletion)
    prompt = get_prompt(prompt_version)

    user_message = (
        f"Hierarchy: {hierarchy_path}\n"
        f"Short text: {short_text}\n"
        f"Long text: {long_text_head}\n"
        f"Unit: {unit}"
    )

    models_to_try = [model] + (fallbacks or [])
    last_error: Exception | None = None

    for attempt_model in models_to_try:
        try:
            result = await client.create(
                model=attempt_model,
                response_model=ClassificationResult,
                max_retries=max_retries,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            result.prompt_version = prompt_version
            result = apply_confidence_flag(result)
            return result

        except Exception as e:
            logger.warning(
                "Classification failed with model %s: %s", attempt_model, e
            )
            last_error = e
            continue

    logger.error("All classification models failed: %s", last_error)
    return ClassificationResult(
        trade="Other",
        element_type="Unclassifiable",
        confidence=0.0,
        flag=ClassificationFlag.LLM_ERROR,
        prompt_version=prompt_version,
    )


async def estimate_tokens(
    hierarchy_path: str,
    short_text: str,
    long_text_head: str,
    unit: str,
) -> tuple[int, int]:
    """Estimate input and output tokens for a single classification.

    Returns (input_tokens, output_tokens).
    """
    input_text = f"{hierarchy_path}\n{short_text}\n{long_text_head}\n{unit}"
    input_tokens = len(input_text) // 3 + 200  # ~system prompt overhead
    output_tokens = 100
    return input_tokens, output_tokens
