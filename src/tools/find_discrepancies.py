"""find_discrepancies: events where agencies disagree past a threshold."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..schemas import ReconciledEvent
from .find_events import find_events


async def find_discrepancies(
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
    min_magnitude_spread: float = 0.4,
    min_location_spread_km: float = 30.0,
    require_multi_agency: bool = True,
    limit: int = 50,
) -> list[ReconciledEvent]:
    """Find events where agency reports disagree past the given thresholds.

    Filters the result of `find_events` to only events whose magnitude spread
    exceeds `min_magnitude_spread` OR whose location spread exceeds
    `min_location_spread_km`. Useful for surfacing newsworthy disagreements,
    or QA-ing how preliminary magnitudes drift across networks.

    `require_multi_agency` (default True) drops single-agency events, since
    a single report can't disagree with itself.
    """
    # Fetch with a generous internal limit so filtering doesn't return a tiny set.
    events = await find_events(
        start_time=start_time,
        end_time=end_time,
        min_magnitude=min_magnitude,
        max_magnitude=max_magnitude,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
        agencies=agencies,
        limit=max(limit * 5, 200),
    )

    filtered: list[ReconciledEvent] = []
    for e in events:
        if require_multi_agency and len({r.agency for r in e.all_reports}) < 2:
            continue
        mag_ok = e.magnitude_spread is not None and e.magnitude_spread >= min_magnitude_spread
        loc_ok = (
            e.location_spread_km is not None
            and e.location_spread_km >= min_location_spread_km
        )
        if mag_ok or loc_ok:
            filtered.append(e)

    return filtered[:limit]
