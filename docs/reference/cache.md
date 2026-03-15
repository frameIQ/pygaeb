# Cache

Pluggable cache backends for LLM classification and extraction results.

## CacheBackend Protocol

::: pygaeb.cache.CacheBackend
    options:
      show_root_heading: true
      members_order: source

## InMemoryCache

LRU-bounded in-memory cache. Default `maxsize=10,000` entries. When full, the least recently accessed entry is evicted.

::: pygaeb.cache.InMemoryCache
    options:
      show_root_heading: true
      members_order: source

## SQLiteCache

::: pygaeb.cache.SQLiteCache
    options:
      show_root_heading: true
      members_order: source
