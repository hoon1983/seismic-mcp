"""Tests for cross-agency event matching and clustering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.matching import cluster_reports, haversine_km

from .conftest import make_report


def test_haversine_zero_for_same_point():
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0


def test_haversine_known_distance():
    # NYC -> LA, ~3940 km great-circle.
    d = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
    assert 3900 < d < 4000


def test_cluster_groups_close_in_time_and_space():
    t = datetime(2026, 5, 22, 1, 0, 0, tzinfo=timezone.utc)
    a = make_report("USGS", "u1", time_utc=t, latitude=16.54, longitude=-46.59, magnitude=5.1)
    b = make_report("EMSC", "e1", time_utc=t + timedelta(seconds=2), latitude=16.55, longitude=-46.60, magnitude=5.1)
    clusters = cluster_reports([a, b])
    assert len(clusters) == 1
    assert {r.agency for r in clusters[0]} == {"USGS", "EMSC"}


def test_cluster_separates_distant_events():
    t = datetime(2026, 5, 22, 1, 0, 0, tzinfo=timezone.utc)
    a = make_report("USGS", "u1", time_utc=t, latitude=10, longitude=20, magnitude=5.0)
    b = make_report("EMSC", "e1", time_utc=t, latitude=40, longitude=120, magnitude=5.0)
    clusters = cluster_reports([a, b])
    assert len(clusters) == 2


def test_cluster_dedupes_same_agency_event_id_keeps_latest():
    t = datetime(2026, 5, 22, 1, 0, 0, tzinfo=timezone.utc)
    early = make_report("USGS", "u1", time_utc=t, magnitude=5.0)
    late = make_report(
        "USGS", "u1", time_utc=t, magnitude=5.3,
    )
    # last_updated_utc decides; give `late` a later one.
    late = late.model_copy(update={"last_updated_utc": t + timedelta(minutes=5)})
    clusters = cluster_reports([early, late])
    assert len(clusters) == 1
    assert len(clusters[0]) == 1
    assert clusters[0][0].magnitude == 5.3


def test_cluster_same_agency_different_event_ids_stay_separate():
    """Two reports from the same agency with different event_ids never share a cluster."""
    t = datetime(2026, 5, 22, 1, 0, 0, tzinfo=timezone.utc)
    a = make_report("USGS", "u1", time_utc=t, latitude=10, longitude=20)
    b = make_report("USGS", "u2", time_utc=t + timedelta(seconds=5), latitude=10.01, longitude=20.01)
    clusters = cluster_reports([a, b])
    assert len(clusters) == 2


def test_cluster_uses_looser_threshold_for_large_events():
    """M6.0+ events get a 120s / 150km tolerance per matching._thresholds_for."""
    t = datetime(2026, 5, 22, 1, 0, 0, tzinfo=timezone.utc)
    a = make_report("USGS", "u1", time_utc=t, latitude=0, longitude=0, magnitude=6.5)
    # Place EMSC report ~100km / 110s away. Within M>=6.0 window (120s/150km),
    # outside the default (90s/100km).
    b = make_report(
        "EMSC", "e1",
        time_utc=t + timedelta(seconds=110),
        latitude=0.9,  # ~100 km north
        longitude=0.0,
        magnitude=6.5,
    )
    clusters = cluster_reports([a, b])
    assert len(clusters) == 1


def test_cluster_rejects_large_magnitude_difference():
    """Even with close space/time, a >1.0 mag delta is treated as different events."""
    t = datetime(2026, 5, 22, 1, 0, 0, tzinfo=timezone.utc)
    a = make_report("USGS", "u1", time_utc=t, latitude=0, longitude=0, magnitude=4.0)
    b = make_report("EMSC", "e1", time_utc=t + timedelta(seconds=5), latitude=0.01, longitude=0.01, magnitude=6.5)
    clusters = cluster_reports([a, b])
    assert len(clusters) == 2
