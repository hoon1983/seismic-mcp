"""Cross-agency event matching.

v1 implements Layer 2 only (spatiotemporal clustering). Layer 1 (EMSC eventid)
and Layer 3 (known_aliases.json) are stubs that can be plugged in later.

Strategy: greedy single-link clustering. Sort reports by origin time; for each,
attach to an existing cluster if ANY member satisfies the thresholds, else
start a new cluster.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .schemas import SourceReport


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    r = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _thresholds_for(mag: float | None) -> tuple[float, float, float]:
    """Return (time_seconds, distance_km, magnitude_diff) thresholds.

    Tighter for small events, looser for large ones (per spec section 5).
    """
    if mag is None:
        return 90.0, 100.0, 1.0
    if mag < 4.0:
        return 30.0, 50.0, 1.0
    if mag >= 6.0:
        return 120.0, 150.0, 1.0
    return 90.0, 100.0, 1.0


def _reports_match(a: SourceReport, b: SourceReport) -> bool:
    # Use the looser (larger-event) of the two thresholds when sizes differ.
    mag = None
    if a.magnitude is not None and b.magnitude is not None:
        mag = max(a.magnitude, b.magnitude)
    elif a.magnitude is not None:
        mag = a.magnitude
    elif b.magnitude is not None:
        mag = b.magnitude
    t_thresh, d_thresh, m_thresh = _thresholds_for(mag)

    dt = abs((a.time_utc - b.time_utc).total_seconds())
    if dt > t_thresh:
        return False

    dist = haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
    if dist > d_thresh:
        return False

    if a.magnitude is not None and b.magnitude is not None:
        if abs(a.magnitude - b.magnitude) > m_thresh:
            return False
    return True


def cluster_reports(reports: Iterable[SourceReport]) -> list[list[SourceReport]]:
    """Group reports that plausibly describe the same physical earthquake.

    Same agency reporting the same event_id twice collapses to the latest report.
    Reports from the same agency with different event_ids stay distinct (they're
    treated as separate events at that agency).
    """
    # First, dedupe by (agency, source_event_id) keeping the latest last_updated_utc.
    deduped: dict[tuple[str, str], SourceReport] = {}
    for r in reports:
        key = (r.agency, r.source_event_id)
        prev = deduped.get(key)
        if prev is None:
            deduped[key] = r
            continue
        prev_ts = prev.last_updated_utc or prev.time_utc
        new_ts = r.last_updated_utc or r.time_utc
        if new_ts >= prev_ts:
            deduped[key] = r

    ordered = sorted(deduped.values(), key=lambda r: r.time_utc)

    clusters: list[list[SourceReport]] = []
    for r in ordered:
        attached = False
        for cluster in clusters:
            # Avoid two reports from the same agency landing in one cluster
            # unless they share an event_id (which they wouldn't, post-dedupe).
            if any(m.agency == r.agency for m in cluster):
                continue
            if any(_reports_match(r, m) for m in cluster):
                cluster.append(r)
                attached = True
                break
        if not attached:
            clusters.append([r])
    return clusters
