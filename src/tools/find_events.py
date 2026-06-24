"""find_events: query configured agencies in parallel, reconcile, return ReconciledEvents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..adapters import make_adapter, supported_agencies
from ..cache import cached_query
from ..reconcile import reconcile
from ..schemas import ReconciledEvent, SourceReport


async def find_events(
    *,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    min_magnitude: Optional[float] = None,
    max_magnitude: Optional[float] = None,
    min_latitude: Optional[float] = None,
    max_latitude: Optional[float] = None,
    min_longitude: Optional[float] = None,
    max_longitude: Optional[float] = None,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    radius_km: Optional[float] = None,
    agencies: Optional[list[str]] = None,
    limit: int = 50,
) -> list[ReconciledEvent]:
    # Snap "now" defaults to the nearest minute so identical-looking requests
    # from a UI poll loop produce the same cache key.
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = end_time or now
    start = start_time or (end - timedelta(hours=24))

    supported = supported_agencies()
    if agencies is None:
        # Default: query every supported agency in parallel. Adapters that don't
        # cover the requested time/region simply return []. The TTL cache makes
        # repeated calls cheap; per-adapter timeouts cap the wait at ~10s.
        agency_set = sorted(supported)
    else:
        agency_set = [a for a in agencies if a in supported]
        if not agency_set:
            return []

    # Pool sized to let every adapter run in parallel.
    limits = httpx.Limits(
        max_connections=max(len(agency_set) + 4, 20),
        max_keepalive_connections=10,
    )
    async with httpx.AsyncClient(http2=True, limits=limits) as client:
        adapters = [make_adapter(a) for a in agency_set]
        results = await asyncio.gather(
            *(
                cached_query(
                    a,
                    client,
                    start_time=start,
                    end_time=end,
                    min_magnitude=min_magnitude,
                    max_magnitude=max_magnitude,
                    min_latitude=min_latitude,
                    max_latitude=max_latitude,
                    min_longitude=min_longitude,
                    max_longitude=max_longitude,
                    center_lat=center_lat,
                    center_lon=center_lon,
                    radius_km=radius_km,
                    limit=limit,
                )
                for a in adapters
            ),
            return_exceptions=True,
        )

    all_reports: list[SourceReport] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        all_reports.extend(r)

    events = reconcile(all_reports)
    return events[:limit]
