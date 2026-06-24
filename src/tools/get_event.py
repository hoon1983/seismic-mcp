"""get_event: fetch one reconciled event by canonical_id.

Strategy:
  1. Parse canonical_id ("AGENCY:event_id") and fetch the seed report from
     that agency's FDSN endpoint by event ID.
  2. Use the seed's time/location to query every supported agency in parallel
     over a ±10-minute window and ~3° bbox around the seed.
  3. Reconcile and return the single cluster that contains the seed.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Optional

import httpx

from ..adapters import make_adapter, supported_agencies
from ..cache import cached_get_by_id, cached_query
from ..reconcile import reconcile
from ..schemas import ReconciledEvent, SourceReport

_WINDOW = timedelta(minutes=10)


def _parse_canonical_id(canonical_id: str) -> Optional[tuple[str, str]]:
    if ":" not in canonical_id:
        return None
    agency, _, event_id = canonical_id.partition(":")
    if not agency or not event_id:
        return None
    return agency, event_id


async def get_event(canonical_id: str) -> Optional[ReconciledEvent]:
    parsed = _parse_canonical_id(canonical_id)
    if parsed is None:
        return None
    agency, event_id = parsed
    supported = supported_agencies()
    if agency not in supported:
        return None

    # Pool sized to let every adapter run in parallel, matching find_events.
    limits = httpx.Limits(
        max_connections=max(len(supported) + 4, 20),
        max_keepalive_connections=10,
    )
    async with httpx.AsyncClient(http2=True, limits=limits) as client:
        seed = await cached_get_by_id(make_adapter(agency), client, event_id)
        if seed is None:
            return None

        # Query every supported agency in parallel. The tight ±10min / 3° window
        # keeps the load bounded; the TTL cache absorbs repeats. Adapters that
        # don't cover the window simply return [].
        agency_set = sorted(supported)

        start = seed.time_utc - _WINDOW
        end = seed.time_utc + _WINDOW
        # ~3 degree buffer (~330 km) — wider than the matching tolerance, so
        # we won't miss a slightly mislocated cross-agency report. We use a
        # bbox rather than center+radius because `maxradiuskm` is a USGS
        # extension not all FDSN servers honor (notably EMSC).
        buf = 3.0
        min_lat = max(seed.latitude - buf, -90.0)
        max_lat = min(seed.latitude + buf, 90.0)
        min_lon = seed.longitude - buf
        max_lon = seed.longitude + buf

        results = await asyncio.gather(
            *(
                cached_query(
                    make_adapter(a),
                    client,
                    start_time=start,
                    end_time=end,
                    min_latitude=min_lat,
                    max_latitude=max_lat,
                    min_longitude=min_lon,
                    max_longitude=max_lon,
                    limit=20,
                )
                for a in agency_set
            ),
            return_exceptions=True,
        )

    all_reports: list[SourceReport] = [seed]
    seen_keys = {(seed.agency, seed.source_event_id)}
    for r in results:
        if isinstance(r, Exception):
            continue
        for rep in r:
            key = (rep.agency, rep.source_event_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_reports.append(rep)

    events = reconcile(all_reports)

    # Return the cluster containing our seed.
    for e in events:
        for rep in e.all_reports:
            if rep.agency == seed.agency and rep.source_event_id == seed.source_event_id:
                return e
    return None
