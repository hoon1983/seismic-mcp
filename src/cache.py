"""TTL cache for adapter query() and get_by_id() calls.

Caching at the adapter level means:
  - `find_events` with the same params re-runs in O(microseconds) on a hit.
  - `get_event` reuses the seed lookup and the bbox sweep separately.
  - Custom adapter queries (AFAD, JMA, IMO) cache identically to FDSN ones.

The cache is process-local; restarting the server clears it. That's the right
default for preliminary seismic data — we don't want to serve stale magnitudes
across restarts, and ISC-style reviewed data is queried infrequently enough
that the lack of persistence doesn't matter.

In-flight de-duplication is intentional: if two requests arrive concurrently
for the same (agency, params), both await the same `asyncio.Task` rather than
hitting the network twice.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from cachetools import TTLCache

from .adapters.base import SeismicAdapter
from .schemas import SourceReport

# Default TTL chosen as: long enough that a user clicking around the UI hits
# the cache, short enough that USGS revisions to a preliminary M show up in
# under a minute.
_TTL_SECONDS = 60.0
_MAX_ENTRIES = 1000

_query_cache: TTLCache[tuple, list[SourceReport]] = TTLCache(
    maxsize=_MAX_ENTRIES, ttl=_TTL_SECONDS
)
_byid_cache: TTLCache[tuple, Optional[SourceReport]] = TTLCache(
    maxsize=_MAX_ENTRIES, ttl=_TTL_SECONDS
)

# In-flight task de-dup: same key currently being fetched -> same Task.
_query_inflight: dict[tuple, asyncio.Task] = {}
_byid_inflight: dict[tuple, asyncio.Task] = {}


def _hashable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _query_key(agency: str, params: dict[str, Any]) -> tuple:
    return (agency, tuple(sorted((k, _hashable(v)) for k, v in params.items())))


async def cached_query(adapter: SeismicAdapter, client, **params) -> list[SourceReport]:
    """Run `adapter.query(client, **params)` through the TTL cache."""
    key = _query_key(adapter.agency, params)
    cached = _query_cache.get(key)
    if cached is not None:
        return cached
    pending = _query_inflight.get(key)
    if pending is not None:
        return await pending

    async def _run() -> list[SourceReport]:
        try:
            result = await adapter.query(client, **params)
        except Exception:
            # Don't cache failures.
            raise
        _query_cache[key] = result
        return result

    task = asyncio.ensure_future(_run())
    _query_inflight[key] = task
    try:
        return await task
    finally:
        _query_inflight.pop(key, None)


async def cached_get_by_id(adapter: SeismicAdapter, client, event_id: str) -> Optional[SourceReport]:
    """Run `adapter.get_by_id(client, event_id)` through the TTL cache."""
    key = (adapter.agency, event_id)
    if key in _byid_cache:
        return _byid_cache[key]
    pending = _byid_inflight.get(key)
    if pending is not None:
        return await pending

    async def _run() -> Optional[SourceReport]:
        result = await adapter.get_by_id(client, event_id)
        _byid_cache[key] = result
        return result

    task = asyncio.ensure_future(_run())
    _byid_inflight[key] = task
    try:
        return await task
    finally:
        _byid_inflight.pop(key, None)


def cache_stats() -> dict[str, int]:
    return {
        "query_size": len(_query_cache),
        "query_max": _query_cache.maxsize,
        "byid_size": len(_byid_cache),
        "byid_max": _byid_cache.maxsize,
        "query_inflight": len(_query_inflight),
        "byid_inflight": len(_byid_inflight),
    }


def clear_caches() -> None:
    _query_cache.clear()
    _byid_cache.clear()
