"""Tests for the adapter TTL cache."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import pytest

from src import cache as cache_mod
from src.cache import cached_get_by_id, cached_query, clear_caches
from src.schemas import SourceReport

from .conftest import make_report


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_caches()
    yield
    clear_caches()


class _CountingAdapter:
    """Test double: records every query/get_by_id call."""

    def __init__(self, agency: str = "USGS", result: Optional[list[SourceReport]] = None):
        self.agency = agency
        self.query_calls = 0
        self.byid_calls = 0
        self._result = result or [make_report(agency, "e1")]

    async def query(self, client, **params) -> list[SourceReport]:
        self.query_calls += 1
        return self._result

    async def get_by_id(self, client, event_id: str) -> Optional[SourceReport]:
        self.byid_calls += 1
        return self._result[0] if self._result else None


async def test_cached_query_hit_skips_network():
    adapter = _CountingAdapter()
    params = dict(
        start_time=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
        min_magnitude=4.5,
        limit=50,
    )
    r1 = await cached_query(adapter, None, **params)
    r2 = await cached_query(adapter, None, **params)
    assert r1 == r2
    assert adapter.query_calls == 1


async def test_cached_query_keys_on_params():
    adapter = _CountingAdapter()
    base = dict(
        start_time=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
    )
    await cached_query(adapter, None, **base, min_magnitude=4.5)
    await cached_query(adapter, None, **base, min_magnitude=5.0)
    assert adapter.query_calls == 2  # different params → different keys


async def test_cached_query_keys_on_agency():
    a = _CountingAdapter(agency="USGS")
    b = _CountingAdapter(agency="EMSC")
    params = dict(start_time=datetime(2026, 5, 22, tzinfo=timezone.utc),
                  end_time=datetime(2026, 5, 22, 1, tzinfo=timezone.utc))
    await cached_query(a, None, **params)
    await cached_query(b, None, **params)
    assert a.query_calls == 1
    assert b.query_calls == 1


async def test_cached_get_by_id_caches_per_id():
    adapter = _CountingAdapter()
    await cached_get_by_id(adapter, None, "us6000sze1")
    await cached_get_by_id(adapter, None, "us6000sze1")
    await cached_get_by_id(adapter, None, "other")
    assert adapter.byid_calls == 2  # one per unique id


async def test_cached_query_dedupes_concurrent_calls():
    """Two coroutines that race for the same key should produce one network call."""
    started = asyncio.Event()
    release = asyncio.Event()

    class _SlowAdapter:
        agency = "USGS"
        calls = 0

        async def query(self, client, **params):
            type(self).calls += 1
            started.set()
            await release.wait()
            return [make_report("USGS", "e1")]

        async def get_by_id(self, client, event_id):  # not used here
            return None

    adapter = _SlowAdapter()
    params = dict(start_time=datetime(2026, 5, 22, tzinfo=timezone.utc),
                  end_time=datetime(2026, 5, 22, 1, tzinfo=timezone.utc))

    t1 = asyncio.create_task(cached_query(adapter, None, **params))
    t2 = asyncio.create_task(cached_query(adapter, None, **params))
    await started.wait()
    release.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1 == r2
    assert _SlowAdapter.calls == 1


async def test_cache_stats_reflects_size():
    adapter = _CountingAdapter()
    assert cache_mod.cache_stats()["query_size"] == 0
    await cached_query(adapter, None,
                       start_time=datetime(2026, 5, 22, tzinfo=timezone.utc),
                       end_time=datetime(2026, 5, 22, 1, tzinfo=timezone.utc))
    assert cache_mod.cache_stats()["query_size"] == 1
