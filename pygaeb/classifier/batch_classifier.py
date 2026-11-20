"""Batch classifier: async batching, deduplication, progress reporting, cost estimation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from pygaeb.cache import CacheBackend
from pygaeb.classifier.cache import (
    LONG_TEXT_HEAD,
    ClassificationCache,
    compute_hash,
    config_version,
    item_input_hash,
)
from pygaeb.classifier.prompt_templates import CURRENT_PROMPT_VERSION, PROMPTS, get_prompt
from pygaeb.classifier.taxonomy import TAXONOMY
from pygaeb.config import get_settings
from pygaeb.events import EventType, emit
from pygaeb.models.document import GAEBDocument
from pygaeb.models.enums import ClassificationFlag
from pygaeb.models.item import ClassificationResult, CostEstimate

logger = logging.getLogger("pygaeb.classifier")

ProgressCallback = Callable[[int, int, str], None]


def _classifiable(item: Any) -> bool:
    """Items with text to classify; quantity determination rows have none."""
    return (
        isinstance(getattr(item, "short_text", None), str)
        and hasattr(item, "long_text_plain")
        and hasattr(item, "classification")
    )


def _is_manual(result: ClassificationResult | None) -> bool:
    return result is not None and result.flag == ClassificationFlag.MANUAL_OVERRIDE


def _item_label(item: Any) -> str:
    """Return a human-readable label for progress reporting."""
    return str(
        getattr(item, "oz", None)
        or getattr(item, "ele_no", None)
        or getattr(item, "art_no", None)
        or getattr(item, "item_id", "")
    )


class LLMClassifier:
    """Production-ready LLM classifier with batching, caching, and cost control.

    Usage:
        # Default: in-memory cache (no disk)
        classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")
        await classifier.enrich(doc)

        # Persistent: SQLite cache (opt-in)
        from pygaeb.cache import SQLiteCache
        classifier = LLMClassifier(cache=SQLiteCache("~/.pygaeb/cache"))
    """

    def __init__(
        self,
        model: str | None = None,
        fallbacks: list[str] | None = None,
        cache: CacheBackend | None = None,
        concurrency: int | None = None,
        prompt_version: str = CURRENT_PROMPT_VERSION,
        taxonomy: dict[str, dict[str, list[str]]] | None = None,
        prompt_template: str | None = None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.default_model
        self.fallbacks = fallbacks or []
        self.concurrency = concurrency or settings.classifier_concurrency
        self.prompt_version = prompt_version
        self.taxonomy = taxonomy
        self.prompt_template = prompt_template
        self.cache = ClassificationCache(cache)

    async def enrich(
        self,
        doc: GAEBDocument,
        on_progress: ProgressCallback | None = None,
        force_reclassify: bool = False,
    ) -> None:
        """Classify all items in the document (async).

        Works for procurement, trade and cost documents via ``doc.iter_items()``;
        items without text, such as quantity determination rows, are skipped.

        An item whose classification is a manual override is left alone. A saved
        override (:meth:`ClassificationCache.save_override`) wins over the model
        even with *force_reclassify*, which bypasses cached model answers only. A
        failed call is not cached, so the next run asks again.
        """
        items = [item for item in doc.iter_items() if _classifiable(item)]
        # Someone decided these by hand: never overwritten.
        pending = [item for item in items if not _is_manual(item.classification)]
        total = len(pending)

        dedup_map: dict[str, list[Any]] = {}
        for item in pending:
            dedup_map.setdefault(item_input_hash(item), []).append(item)

        version = self._cache_version()
        semaphore = asyncio.Semaphore(self.concurrency)
        completed = 0
        cache_hits = 0
        llm_calls = 0

        async def _classify_group(text_hash: str, group: list[Any]) -> None:
            nonlocal completed, cache_hits, llm_calls
            representative = group[0]

            result = self._saved_override(text_hash, representative)
            if result is None and not force_reclassify:
                result = self.cache.get(text_hash, version)
            if result is not None:
                cache_hits += 1
            else:
                async with semaphore:
                    llm_calls += 1
                    result = await self._classify_item(representative)
                # A failure is not an answer: caching it would stop every retry.
                if result.flag != ClassificationFlag.LLM_ERROR:
                    self.cache.put(text_hash, version, result)

            # A copy each: items sharing one object would change together.
            for item in group:
                item.classification = result.model_copy()
            completed += len(group)
            if on_progress:
                on_progress(completed, total, _item_label(representative))

        await asyncio.gather(*(_classify_group(h, g) for h, g in dedup_map.items()))

        logger.info(
            "Classification complete: %d items, %d unique, %d manual overrides kept, "
            "cache stats: %s",
            total, len(dedup_map), len(items) - total, self.cache.stats(),
        )
        errors = sum(
            1 for item in pending
            if item.classification is not None
            and item.classification.flag == ClassificationFlag.LLM_ERROR
        )
        self._announce(
            item_count=len(items), unique_texts=len(dedup_map),
            cache_hits=cache_hits, llm_calls=llm_calls, errors=errors,
        )

    def _cache_version(self) -> str:
        """Key half for model answers: model, prompt text as sent, taxonomy."""
        prompt = (
            self.prompt_template if self.prompt_template is not None
            else get_prompt(self.prompt_version)
        )
        return config_version(self.prompt_version, self.model, prompt, self.taxonomy)

    def _saved_override(self, input_hash: str, item: Any) -> ClassificationResult | None:
        return self.cache.get_override(
            input_hash,
            legacy_hash=compute_hash(item.short_text, item.long_text_plain[:LONG_TEXT_HEAD]),
            legacy_version=self.prompt_version,
        )

    def _check_taxonomy(self, result: ClassificationResult) -> ClassificationResult:
        """Flag an answer outside the taxonomy the prompt allowed, for review."""
        if result.flag in (ClassificationFlag.LLM_ERROR, ClassificationFlag.MANUAL_OVERRIDE):
            return result
        if self._outside_taxonomy(result):
            logger.info(
                "Answer outside the taxonomy, flagged for review: %s > %s > %s",
                result.trade, result.element_type, result.sub_type,
            )
            result.flag = ClassificationFlag.NEEDS_REVIEW
        return result

    def _outside_taxonomy(self, result: ClassificationResult) -> bool:
        if self.taxonomy is not None:
            # Sent in the prompt as "trade > element: sub-types".
            elements = self.taxonomy.get(result.trade)
            if elements is None or result.element_type not in elements:
                return True
            subtypes = elements[result.element_type]
            return bool(subtypes and result.sub_type and result.sub_type not in subtypes)
        if self.prompt_template is None and get_prompt(self.prompt_version) in PROMPTS.values():
            # The built-in prompt lists the trades; element types are only examples.
            return result.trade not in TAXONOMY
        return False  # a custom prompt sets its own rules

    def _announce(
        self, *, item_count: int, unique_texts: int, cache_hits: int, llm_calls: int,
        errors: int,
    ) -> None:
        """Emit CLASSIFICATION_COMPLETED. Hits and calls count unique texts, not items."""
        emit(
            EventType.CLASSIFICATION_COMPLETED,
            model=self.model,
            item_count=item_count,
            unique_texts=unique_texts,
            cache_hits=cache_hits,
            llm_calls=llm_calls,
            errors=errors,
        )

    def enrich_sync(
        self,
        doc: GAEBDocument,
        on_progress: ProgressCallback | None = None,
        force_reclassify: bool = False,
    ) -> None:
        """Synchronous convenience wrapper — manages event loop internally."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.enrich(doc, on_progress, force_reclassify),
                )
                future.result()
        else:
            asyncio.run(self.enrich(doc, on_progress, force_reclassify))

    async def estimate_cost(self, doc: GAEBDocument) -> CostEstimate:
        """Estimate the cost of classifying all items in the document."""
        from pygaeb.classifier.llm_backend import estimate_tokens

        items = [item for item in doc.iter_items() if _classifiable(item)]
        total = len(items)
        version = self._cache_version()

        dedup_map: dict[str, Any] = {}
        duplicates = 0
        for item in items:
            if _is_manual(item.classification):
                continue
            h = item_input_hash(item)
            if h in dedup_map:
                duplicates += 1
            else:
                dedup_map[h] = item

        cached_count = 0
        to_classify: list[Any] = []
        for h, item in dedup_map.items():
            known = self._saved_override(h, item) or self.cache.get(h, version)
            if known is not None:
                cached_count += 1
            else:
                to_classify.append(item)

        total_input_tokens = 0
        total_output_tokens = 0
        for item in to_classify:
            hierarchy = getattr(item, "hierarchy_path_str", "")
            inp, out = await estimate_tokens(
                hierarchy,
                item.short_text,
                item.long_text_plain[:LONG_TEXT_HEAD],
                item.unit or "",
            )
            total_input_tokens += inp
            total_output_tokens += out

        estimated_cost = self._estimate_cost_usd(total_input_tokens, total_output_tokens)
        estimated_duration = len(to_classify) / max(self.concurrency, 1) * 0.8

        return CostEstimate(
            total_items=total,
            cached_items=cached_count,
            duplicate_items=duplicates,
            items_to_classify=len(to_classify),
            estimated_input_tokens=total_input_tokens,
            estimated_output_tokens=total_output_tokens,
            estimated_cost_usd=estimated_cost,
            estimated_duration_s=estimated_duration,
            model=self.model,
        )

    async def _classify_item(self, item: Any) -> ClassificationResult:
        from pygaeb.classifier.llm_backend import classify_single_item

        hierarchy = getattr(item, "hierarchy_path_str", "")
        result = await classify_single_item(
            model=self.model,
            hierarchy_path=hierarchy,
            short_text=item.short_text,
            long_text_head=item.long_text_plain[:LONG_TEXT_HEAD],
            unit=item.unit or "",
            prompt_version=self.prompt_version,
            fallbacks=self.fallbacks,
            prompt_template=self.prompt_template,
            taxonomy=self.taxonomy,
        )
        return self._check_taxonomy(result)

    def _estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost using LiteLLM's cost data when available."""
        try:
            import litellm
            input_cost = litellm.completion_cost(
                model=self.model,
                prompt="x" * input_tokens,
                completion="x" * output_tokens,
            )
            return float(input_cost)
        except Exception:
            input_cost_per_m = 3.0
            output_cost_per_m = 15.0
            cost = (input_tokens / 1_000_000 * input_cost_per_m +
                    output_tokens / 1_000_000 * output_cost_per_m)
            return round(cost, 4)
