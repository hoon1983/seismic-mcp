"""Tests for prime-report selection and the end-to-end reconcile pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.prime_selection import pick_prime
from src.reconcile import reconcile

from .conftest import make_report


def _t(s: int = 0) -> datetime:
    return datetime(2026, 5, 22, 1, 0, s, tzinfo=timezone.utc)


# ----- prime_selection -----

def test_prime_local_authority_wins_when_present():
    # Italy → INGV authority.
    usgs = make_report("USGS", "u", time_utc=_t(), latitude=41.9, longitude=12.5)
    emsc = make_report("EMSC", "e", time_utc=_t(2), latitude=41.9, longitude=12.5)
    ingv = make_report("INGV", "i", time_utc=_t(4), latitude=41.9, longitude=12.5)
    assert pick_prime([usgs, emsc, ingv]).agency == "INGV"


def test_prime_emsc_when_in_europe_no_local_authority():
    # Open Atlantic in Europe bbox (-30..50, 25..72) but no local-authority bbox.
    usgs = make_report("USGS", "u", time_utc=_t(), latitude=40.0, longitude=-20.0)
    emsc = make_report("EMSC", "e", time_utc=_t(), latitude=40.0, longitude=-20.0)
    assert pick_prime([usgs, emsc]).agency == "EMSC"


def test_prime_usgs_when_not_in_emsc_region():
    # Open Pacific.
    usgs = make_report("USGS", "u", time_utc=_t(), latitude=0.0, longitude=-160.0)
    emsc = make_report("EMSC", "e", time_utc=_t(), latitude=0.0, longitude=-160.0)
    assert pick_prime([usgs, emsc]).agency == "USGS"


def test_prime_reviewed_trumps_preliminary():
    """Even if local-authority is preliminary, a reviewed report from any agency wins."""
    ingv = make_report(
        "INGV", "i", time_utc=_t(), latitude=41.9, longitude=12.5, is_reviewed=False
    )
    isc = make_report(
        "ISC", "isc", time_utc=_t(), latitude=41.9, longitude=12.5, is_reviewed=True
    )
    assert pick_prime([ingv, isc]).agency == "ISC"


def test_prime_reviewed_from_local_authority_wins_over_other_reviewed():
    """If both local-authority and a non-local agency have reviewed reports, local wins."""
    ingv = make_report(
        "INGV", "i", time_utc=_t(), latitude=41.9, longitude=12.5, is_reviewed=True
    )
    isc = make_report(
        "ISC", "isc", time_utc=_t(), latitude=41.9, longitude=12.5, is_reviewed=True
    )
    assert pick_prime([ingv, isc]).agency == "INGV"


def test_prime_falls_back_to_earliest_when_no_globals():
    early = make_report("GFZ", "g", time_utc=_t(0), latitude=0.0, longitude=-160.0)
    late = make_report("IRIS", "i", time_utc=_t(5), latitude=0.0, longitude=-160.0)
    assert pick_prime([late, early]).agency == "GFZ"


def test_prime_empty_raises():
    with pytest.raises(ValueError):
        pick_prime([])


# ----- reconcile (end-to-end on synthetic reports) -----

def test_reconcile_assembles_single_event_with_spreads():
    usgs = make_report("USGS", "u", time_utc=_t(), latitude=16.54, longitude=-46.59, magnitude=5.1, depth_km=10.0)
    emsc = make_report("EMSC", "e", time_utc=_t(1), latitude=16.55, longitude=-46.60, magnitude=5.3, depth_km=12.0)
    events = reconcile([usgs, emsc])
    assert len(events) == 1
    e = events[0]
    assert e.magnitude_spread == pytest.approx(0.2)
    assert e.depth_spread_km == pytest.approx(2.0)
    assert 0 < (e.location_spread_km or 0) < 5
    assert e.reports_disagree is False  # 0.2 magnitude < 0.4 threshold


def test_reconcile_flags_disagreement_when_thresholds_exceeded():
    t = _t()
    usgs = make_report("USGS", "u", time_utc=t, latitude=0, longitude=0, magnitude=6.0)
    emsc = make_report("EMSC", "e", time_utc=t, latitude=0, longitude=0, magnitude=6.5)
    events = reconcile([usgs, emsc])
    assert events[0].reports_disagree is True
    assert events[0].magnitude_spread == pytest.approx(0.5)


def test_reconcile_canonical_id_uses_prime():
    """canonical_id is built from the prime report's agency:event_id."""
    t = _t()
    afad = make_report("AFAD", "552519", time_utc=t, latitude=40, longitude=32, magnitude=3.0)
    emsc = make_report("EMSC", "20260522_0001", time_utc=t, latitude=40, longitude=32, magnitude=3.0)
    events = reconcile([afad, emsc])
    # Turkey → AFAD is local authority → prime.
    assert events[0].canonical_id == "AFAD:552519"


def test_reconcile_orders_events_newest_first():
    early = make_report("USGS", "u1", time_utc=_t(0), latitude=0, longitude=0)
    late = make_report("USGS", "u2", time_utc=_t(0) + timedelta(hours=1), latitude=10, longitude=10)
    events = reconcile([early, late])
    assert events[0].prime_report.source_event_id == "u2"
    assert events[1].prime_report.source_event_id == "u1"


def test_reconcile_magnitudes_by_agency_map():
    t = _t()
    a = make_report("USGS", "u", time_utc=t, latitude=0, longitude=0, magnitude=5.1)
    b = make_report("EMSC", "e", time_utc=t, latitude=0, longitude=0, magnitude=5.2)
    c = make_report("GFZ", "g", time_utc=t, latitude=0, longitude=0, magnitude=None)
    events = reconcile([a, b, c])
    # None magnitudes are excluded from the map.
    assert events[0].magnitudes_by_agency == {"USGS": 5.1, "EMSC": 5.2}
