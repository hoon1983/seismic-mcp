"""Shared pytest helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from src.schemas import SourceReport


def make_report(
    agency: str = "USGS",
    event_id: str = "evt1",
    *,
    time_utc: datetime | None = None,
    latitude: float = 0.0,
    longitude: float = 0.0,
    depth_km: float | None = 10.0,
    magnitude: float | None = 5.0,
    magnitude_type: str | None = "Mw",
    region_name: str | None = None,
    is_reviewed: bool = False,
) -> SourceReport:
    return SourceReport(
        agency=agency,
        source_event_id=event_id,
        time_utc=time_utc or datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        latitude=latitude,
        longitude=longitude,
        depth_km=depth_km,
        magnitude=magnitude,
        magnitude_type=magnitude_type,
        region_name=region_name,
        is_reviewed=is_reviewed,
    )
