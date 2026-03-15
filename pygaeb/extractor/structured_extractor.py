"""StructuredExtractor — extract typed attributes from classified items into user-defined schemas.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, TypeVar, cast

from pydantic import BaseModel

from pygaeb.cache import CacheBackend
from pygaeb.classifier.cache import compute_hash as compute_item_hash
from pygaeb.config import get_settings
from pygaeb.extractor.extraction_cache import ExtractionCache
from pygaeb.extractor.extraction_prompt import (
    build_extraction_prompt,
    build_extraction_user_message,
)
from pygaeb.extractor.schema_utils import (
    compute_completeness,
    compute_extraction_cache_key,
    compute_schema_hash,
    get_schema_name,
    schema_field_summary,
)
from pygaeb.models.document import GAEBDocument
from pygaeb.models.item import ExtractionResult

logger = logging.getLogger("pygaeb.extractor")

T = TypeVar("T", bound=BaseModel)
ProgressCallback = Callable[[int, int, str], None]


class StructuredExtractor:
    """Extract structured attributes from BoQ items into user-defined Pydantic schemas.

    Workflow:
        1. Base classification tags items (Door, Wall, Pipe, etc.)
        2. User defines a Pydantic schema for a category
        3. StructuredExtractor uses LLM to extract typed attributes from item text

    Usage:
        # Default: in-memory cache (no disk)
        extractor = StructuredExtractor(model="anthropic/claude-sonnet-4-6")

        # Persistent: SQLite cache (opt-in)
        from pygaeb.cache import SQLiteCache
        extractor = StructuredExtractor(cache=SQLiteCache("~/.pygaeb/cache"))

        # By classification filter
        results = await extractor.extract(doc, schema=DoorSpec, element_type="Door")

        # By explicit item list
        results = await extractor.extract_items(my_items, schema=DoorSpec)

        for item, spec in results:
            print(item.oz, spec.fire_rating, spec.width_mm)
    """

    def __init__(
        self,
        model: str | None = None,
        fallbacks: list[str] | None = None,
        cache: CacheBackend | None = None,
        concurrency: int | None = None,
    ) -> None:
        settings = get_settings()
        self.model = model or settings.default_model
        self.fallbacks = fallbacks or []
        self.concurrency = concurrency or settings.classifier_concurrency
        self.cache = ExtractionCache(cache)

    async def extract(
        self,
        doc: GAEBDocument,
        schema: type[T],
        trade: str | None = None,
        element_type: str | None = None,
        sub_type: str | None = None,
        on_progress: ProgressCallback | None = None,
        force_reextract: bool = False,
        attach: bool = True,
    ) -> list[tuple[Any, T]]:
        """Extract structured data from items matching a classification filter.

        Works for both procurement and trade documents.

        Args:
            doc: Parsed GAEB document (items should be classified first).
            schema: User-defined Pydantic model to extract into.
            trade: Filter by classification trade (Level 1).
            element_type: Filter by classification element_type (Level 2).
            sub_type: Filter by classification sub_type (Level 3).
            on_progress: Callback(completed, total, current_label).
            force_reextract: Bypass cache and re-extract all items.
            attach: If True, store results on item.extractions[schema_name].

        Returns:
            List of (item, schema_instance) tuples.
        """
        items = _filter_items(doc, trade, element_type, sub_type)

        if not items:
            logger.info(
                "No items match filter (trade=%s, element_type=%s, sub_type=%s)",
                trade, element_type, sub_type,
            )
            return []

        inferred_trade = trade or ""
        inferred_element = element_type or ""
        if not inferred_trade and not inferred_element and items:
            first_cls = items[0].classification
            if first_cls:
                inferred_trade = first_cls.trade
                inferred_element = first_cls.element_type

        return await self._extract_batch(
            items=items,
            schema=schema,
            trade_context=inferred_trade,
            element_context=inferred_element,
            on_progress=on_progress,
            force_reextract=force_reextract,
            attach=attach,
        )

    async def extract_items(
        self,
        items: list[Any],
        schema: type[T],
        trade_context: str = "",
        element_context: str = "",
        on_progress: ProgressCallback | None = None,
        force_reextract: bool = False,
        attach: bool = True,
    ) -> list[tuple[Any, T]]:
        """Extract structured data from an explicit list of items.

        Use this when you want full control over which items to extract from,
        bypassing classification-based filtering.
        """
        if not items:
            return []
        return await self._extract_batch(
            items=items,
            schema=schema,
            trade_context=trade_context,
            element_context=element_context,
            on_progress=on_progress,
            force_reextract=force_reextract,
            attach=attach,
        )

    def extract_sync(
        self,
        doc: GAEBDocument,
        schema: type[T],
        trade: str | None = None,
        element_type: str | None = None,
        sub_type: str | None = None,
        on_progress: ProgressCallback | None = None,
        force_reextract: bool = False,
        attach: bool = True,
    ) -> list[tuple[Any, T]]:
        """Synchronous convenience wrapper."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = self.extract(
            doc, schema, trade, element_type, sub_type,
            on_progress, force_reextract, attach,
        )

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)

    async def estimate_cost(
        self,
        doc: GAEBDocument,
        schema: type[BaseModel],
        trade: str | None = None,
        element_type: str | None = None,
        sub_type: str | None = None,
    ) -> dict[str, Any]:
        """Estimate cost of extracting structured data from matching items."""
        items = _filter_items(doc, trade, element_type, sub_type)
        s_hash = compute_schema_hash(schema)
        num_fields = len(schema.model_fields)

        cached_count = 0
        to_extract: list[Any] = []
        for item in items:
            item_hash = compute_item_hash(item.short_text, item.long_text_plain[:300])
            cache_key = compute_extraction_cache_key(item_hash, s_hash)
            if self.cache.get(cache_key) is not None:
                cached_count += 1
            else:
                to_extract.append(item)

        avg_chars = sum(
            len(i.short_text) + len(i.long_text_plain) for i in to_extract
        ) / max(len(to_extract), 1)
        avg_input_tokens = int(avg_chars / 3) + 200
        output_tokens_per_field = 30
        total_input = len(to_extract) * avg_input_tokens
        total_output = len(to_extract) * num_fields * output_tokens_per_field

        return {
            "schema": get_schema_name(schema),
            "schema_fields": num_fields,
            "matching_items": len(items),
            "cached_items": cached_count,
            "items_to_extract": len(to_extract),
            "estimated_input_tokens": total_input,
            "estimated_output_tokens": total_output,
            "model": self.model,
        }

    async def _extract_batch(
        self,
        items: list[Any],
        schema: type[T],
        trade_context: str,
        element_context: str,
        on_progress: ProgressCallback | None,
        force_reextract: bool,
        attach: bool,
    ) -> list[tuple[Any, T]]:
        s_hash = compute_schema_hash(schema)
        s_name = get_schema_name(schema)
        system_prompt = build_extraction_prompt(schema, element_context, trade_context)

        logger.info(
            "Extracting %s from %d items (schema: %s)",
            schema_field_summary(schema), len(items), s_name,
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[tuple[Any, T]] = []
        completed = 0
        total = len(items)

        async def _extract_one(item: Any) -> tuple[Any, T]:
            nonlocal completed
            label = str(
                getattr(item, "oz", None)
                or getattr(item, "ele_no", None)
                or getattr(item, "art_no", None)
                or getattr(item, "item_id", "")
            )

            item_hash = compute_item_hash(item.short_text, item.long_text_plain[:300])
            cache_key = compute_extraction_cache_key(item_hash, s_hash)

            if not force_reextract:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    data_dict, completeness = cached
                    instance = schema(**data_dict)
                    if attach:
                        item.extractions[s_name] = ExtractionResult(
                            schema_name=s_name,
                            schema_hash=s_hash,
                            data=data_dict,
                            completeness=completeness,
                            cached=True,
                        )
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, label)
                    return item, instance

            async with semaphore:
                instance = await self._call_llm(item, schema, system_prompt)

            data_dict = instance.model_dump()
            completeness = compute_completeness(instance)

            self.cache.put(cache_key, s_name, s_hash, data_dict, completeness)

            if attach:
                item.extractions[s_name] = ExtractionResult(
                    schema_name=s_name,
                    schema_hash=s_hash,
                    data=data_dict,
                    completeness=completeness,
                    cached=False,
                )

            completed += 1
            if on_progress:
                on_progress(completed, total, label)
            return item, instance

        tasks = [_extract_one(item) for item in items]
        results = await asyncio.gather(*tasks)

        avg_completeness = (
            sum(compute_completeness(r[1]) for r in results) / len(results)
            if results else 0.0
        )
        logger.info(
            "Extraction complete: %d items, avg completeness %.0f%%, schema=%s",
            len(results), avg_completeness * 100, s_name,
        )

        return results

    async def _call_llm(
        self,
        item: Any,
        schema: type[T],
        system_prompt: str,
    ) -> T:
        """Call LLM via LiteLLM + instructor to extract structured data."""
        try:
            import instructor
            import litellm
        except ImportError as err:
            raise ImportError(
                "Structured extraction requires the 'llm' extra: pip install pyGAEB[llm]"
            ) from err

        client = instructor.from_litellm(litellm.acompletion)

        element_context = ""
        if item.classification:
            element_context = (
                f"\nClassification: {item.classification.trade} > "
                f"{item.classification.element_type} > "
                f"{item.classification.sub_type}"
            )

        hierarchy = getattr(item, "hierarchy_path_str", "")
        user_message = build_extraction_user_message(
            hierarchy_path=hierarchy,
            short_text=item.short_text,
            long_text=item.long_text_plain,
            unit=item.unit or "",
            qty=str(item.qty) if item.qty else "",
        )
        if element_context:
            user_message += element_context

        models_to_try = [self.model, *self.fallbacks]
        last_error: Exception | None = None

        for attempt_model in models_to_try:
            try:
                result = await client.create(
                    model=attempt_model,
                    response_model=schema,
                    max_retries=2,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                return cast(T, result)
            except Exception as e:
                logger.warning("Extraction failed with model %s: %s", attempt_model, e)
                last_error = e
                continue

        logger.error("All extraction models failed: %s", last_error)
        return schema()


def _filter_items(
    doc: GAEBDocument,
    trade: str | None = None,
    element_type: str | None = None,
    sub_type: str | None = None,
) -> list[Any]:
    """Filter items by classification fields. Works for both document kinds."""
    items: list[Any] = []
    for item in doc.iter_items():
        if item.classification is None:
            continue
        cls = item.classification
        if trade and cls.trade != trade:
            continue
        if element_type and cls.element_type != element_type:
            continue
        if sub_type and cls.sub_type != sub_type:
            continue
        items.append(item)
    return items
