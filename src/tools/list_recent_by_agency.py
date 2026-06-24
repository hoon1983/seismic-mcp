"""list_recent_by_agency: raw events from one agency, no reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from ..adapters import make_adapter, supported_agencies
from ..cache import cached_query
from ..schemas import SourceReport


async def list_recent_by_agency(
    *,
    agency: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    min_magnitude: Optional[float] = None,
    limit: int = 50,
) -> list[SourceReport]:
    """Return recent events as reported by a single agency, unreconciled.

    Use when you want to see what one network alone is reporting (e.g. to see
    small local events the global feeds miss), or to compare an agency's raw
    output to the reconciled view from `find_events`.
    """
    if agency not in supported_agencies():
        return []

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = end_time or now
    start = start_time or (end - timedelta(hours=24))

    async with httpx.AsyncClient(http2=True) as client:
        adapter = make_adapter(agency)
        reports = await cached_query(
            adapter,
            client,
            start_time=start,
            end_time=end,
            min_magnitude=min_magnitude,
            limit=limit,
        )
    reports.sort(key=lambda r: r.time_utc, reverse=True)
    return reports[:limit]
