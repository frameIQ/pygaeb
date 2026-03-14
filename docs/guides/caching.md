# Caching

LLM classification and structured extraction results are cached to avoid redundant API calls. pyGAEB uses a pluggable cache architecture with three options.

## In-Memory Cache (Default)

The default cache lives in memory and lasts for the current Python session:

```python
from pygaeb import LLMClassifier, StructuredExtractor

classifier = LLMClassifier(model="gpt-4o")
extractor = StructuredExtractor(model="gpt-4o")
```

No configuration needed. When the process exits, the cache is lost.

**Best for:** scripts, notebooks, one-off processing.

## SQLite Cache (Persistent)

For caching across runs (e.g., during development or repeated processing):

```python
from pygaeb import LLMClassifier, StructuredExtractor, SQLiteCache

cache = SQLiteCache("~/.pygaeb/cache")

classifier = LLMClassifier(model="gpt-4o", cache=cache)
extractor = StructuredExtractor(model="gpt-4o", cache=cache)
```

The SQLite database is created automatically in the specified directory. It uses WAL mode for safe concurrent reads.

### Context Manager

`SQLiteCache` supports `with` blocks for automatic cleanup:

```python
from pygaeb import SQLiteCache, LLMClassifier

with SQLiteCache("/tmp/project-cache") as cache:
    classifier = LLMClassifier(model="gpt-4o", cache=cache)
    await classifier.enrich(doc)
# Connection closed automatically
```

### Shared Cache

Use a single cache backend for both classifier and extractor:

```python
shared = SQLiteCache("/tmp/project-cache")
classifier = LLMClassifier(model="gpt-4o", cache=shared)
extractor = StructuredExtractor(model="gpt-4o", cache=shared)
```

Classification and extraction keys are namespaced internally, so they never collide.

## Custom Cache Backend

Implement the `CacheBackend` protocol to use Redis, DynamoDB, or any other store:

```python
from pygaeb import CacheBackend

class RedisCache:
    """Example custom cache backend."""

    def __init__(self, redis_client):
        self._r = redis_client

    def get(self, key: str) -> str | None:
        val = self._r.get(f"pygaeb:{key}")
        return val.decode() if val else None

    def put(self, key: str, value: str) -> None:
        self._r.set(f"pygaeb:{key}", value)

    def delete(self, key: str) -> None:
        self._r.delete(f"pygaeb:{key}")

    def clear(self) -> None:
        for key in self._r.keys("pygaeb:*"):
            self._r.delete(key)

    def keys(self) -> list[str]:
        return [k.decode().removeprefix("pygaeb:") for k in self._r.keys("pygaeb:*")]

    def close(self) -> None:
        pass  # Redis client manages its own lifecycle
```

Then use it:

```python
import redis
from pygaeb import LLMClassifier

r = redis.Redis(host="localhost")
classifier = LLMClassifier(model="gpt-4o", cache=RedisCache(r))
```

## Cache Statistics

Check cache hit rates:

```python
stats = classifier.cache.stats()
for entry in stats:
    print(f"Prompt v{entry['prompt_version']}: {entry['count']} entries")
```

## Clearing the Cache

```python
# Clear all entries (except manual overrides)
classifier.cache.clear()

# Clear extraction cache for a specific schema
extractor.cache.clear(schema_name="DoorSpec")
```

## How Cache Keys Work

Cache keys are deterministic hashes of the input data:

- **Classification:** hash of `(short_text, long_text, unit, hierarchy_path, prompt_version)`
- **Extraction:** hash of `(item_content_hash, schema_json_hash)`

This means identical items always hit the cache, even across different documents.
