"""Batch classifier: async batching, deduplication, progress reporting, cost estimation."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from pygaeb.cache import CacheBackend
from pygaeb.classifier.cache import ClassificationCache, compute_hash
from pygaeb.classifier.confidence import merge_with_override
from pygaeb.classifier.prompt_templates import CURRENT_PROMPT_VERSION
from pygaeb.config import get_settings
from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import ClassificationResult, CostEstimate, Item

logger = logging.getLogger("pygaeb.classifier")

ProgressCallback = Callable[[int, int, str], None]


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
    ) -> None:
        settings = get_settings()
        self.model = model or settings.default_model
        self.fallbacks = fallbacks or []
        self.concurrency = concurrency or settings.classifier_concurrency
        self.prompt_version = prompt_version
        self.cache = ClassificationCache(cache)

    async def enrich(
        self,
        doc: GAEBDocument,
        on_progress: ProgressCallback | None = None,
        force_reclassify: bool = False,
    ) -> None:
        """Classify all items in the document (async)."""
        items = list(doc.award.boq.iter_items())
        total = len(items)
        if total == 0:
            return

        dedup_map: dict[str, list[Item]] = {}
        for item in items:
            h = compute_hash(item.short_text, item.long_text_plain[:300])
            dedup_map.setdefault(h, []).append(item)

        semaphore = asyncio.Semaphore(self.concurrency)
        completed = 0

        async def _classify_group(text_hash: str, group: list[Item]) -> None:
            nonlocal completed
            representative = group[0]

            if not force_reclassify:
                cached = self.cache.get(text_hash, self.prompt_version)
                if cached is not None:
                    for item in group:
                        item.classification = cached
                    completed += len(group)
                    if on_progress:
                        on_progress(completed, total, representative.oz)
                    return

            async with semaphore:
                result = await self._classify_item(representative)
                self.cache.put(text_hash, self.prompt_version, result)

            for item in group:
                override = self.cache.get(text_hash, self.prompt_version)
                item.classification = merge_with_override(result, override)

            completed += len(group)
            if on_progress:
                on_progress(completed, total, representative.oz)

        tasks = [
            _classify_group(h, group)
            for h, group in dedup_map.items()
        ]
        await asyncio.gather(*tasks)

        cache_stats = self.cache.stats()
        logger.info(
            "Classification complete: %d items, %d unique, cache stats: %s",
            total, len(dedup_map), cache_stats,
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

        items = list(doc.award.boq.iter_items())
        total = len(items)

        dedup_map: dict[str, Item] = {}
        duplicates = 0
        for item in items:
            h = compute_hash(item.short_text, item.long_text_plain[:300])
            if h in dedup_map:
                duplicates += 1
            else:
                dedup_map[h] = item

        cached_count = 0
        to_classify: list[Item] = []
        for h, item in dedup_map.items():
            if self.cache.get(h, self.prompt_version) is not None:
                cached_count += 1
            else:
                to_classify.append(item)

        total_input_tokens = 0
        total_output_tokens = 0
        for item in to_classify:
            inp, out = await estimate_tokens(
                item.hierarchy_path_str,
                item.short_text,
                item.long_text_plain[:300],
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

    async def _classify_item(self, item: Item) -> ClassificationResult:
        from pygaeb.classifier.llm_backend import classify_single_item

        return await classify_single_item(
            model=self.model,
            hierarchy_path=item.hierarchy_path_str,
            short_text=item.short_text,
            long_text_head=item.long_text_plain[:300],
            unit=item.unit or "",
            prompt_version=self.prompt_version,
            fallbacks=self.fallbacks,
        )

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
