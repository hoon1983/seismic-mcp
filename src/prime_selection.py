"""Pick the 'prime' report for a cluster of cross-agency reports.

Priority (per spec section 6):
  1. Local authority (by epicenter), if present.
  2. EMSC if epicenter falls in the Europe/Mediterranean region.
  3. USGS otherwise.
  4. Earliest-reporting agency as final fallback.

Exception: if any report has is_reviewed=True and the would-be prime is not
reviewed, prefer the reviewed one.
"""

from __future__ import annotations

from .authorities import authority_for
from .schemas import SourceReport

# Loose EMSC primary region: Europe + Mediterranean basin.
_EMSC_BBOX = (-30.0, 25.0, 50.0, 72.0)  # (minlon, minlat, maxlon, maxlat)


def _in_emsc_region(lat: float, lon: float) -> bool:
    minlon, minlat, maxlon, maxlat = _EMSC_BBOX
    return minlat <= lat <= maxlat and minlon <= lon <= maxlon


def pick_prime(reports: list[SourceReport]) -> SourceReport:
    if not reports:
        raise ValueError("pick_prime called with empty reports list")

    # Use the median-ish epicenter (first report sorted by time) to decide region.
    anchor = sorted(reports, key=lambda r: r.time_utc)[0]
    lat, lon = anchor.latitude, anchor.longitude

    by_agency = {r.agency: r for r in reports}

    auth = authority_for(lat, lon)
    candidate: SourceReport | None = None
    if auth and auth in by_agency:
        candidate = by_agency[auth]
    elif _in_emsc_region(lat, lon) and "EMSC" in by_agency:
        candidate = by_agency["EMSC"]
    elif "USGS" in by_agency:
        candidate = by_agency["USGS"]
    else:
        candidate = anchor

    # Reviewed-trumps-preliminary exception.
    if not candidate.is_reviewed:
        reviewed = [r for r in reports if r.is_reviewed]
        if reviewed:
            # Prefer reviewed report from the local authority if available, else any reviewed.
            for r in reviewed:
                if r.agency == auth:
                    return r
            return reviewed[0]
    return candidate
