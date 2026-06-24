"""Assemble ReconciledEvent objects from a flat list of cross-agency reports."""

from __future__ import annotations

from collections.abc import Iterable

from .authorities import authority_for
from .matching import cluster_reports, haversine_km
from .prime_selection import pick_prime
from .schemas import ReconciledEvent, SourceReport

# Defaults for the "reports_disagree" flag.
_MAG_SPREAD_THRESHOLD = 0.4
_LOCATION_SPREAD_THRESHOLD_KM = 30.0


def _spread(values: list[float]) -> float | None:
    if not values:
        return None
    return max(values) - min(values)


def _location_spread_km(reports: list[SourceReport]) -> float | None:
    if len(reports) < 2:
        return 0.0 if reports else None
    worst = 0.0
    for i in range(len(reports)):
        for j in range(i + 1, len(reports)):
            d = haversine_km(
                reports[i].latitude,
                reports[i].longitude,
                reports[j].latitude,
                reports[j].longitude,
            )
            if d > worst:
                worst = d
    return worst


def _build_canonical_id(prime: SourceReport) -> str:
    return f"{prime.agency}:{prime.source_event_id}"


def reconcile(reports: Iterable[SourceReport]) -> list[ReconciledEvent]:
    events: list[ReconciledEvent] = []
    for cluster in cluster_reports(reports):
        prime = pick_prime(cluster)
        mags = [r.magnitude for r in cluster if r.magnitude is not None]
        depths = [r.depth_km for r in cluster if r.depth_km is not None]
        mag_spread = _spread(mags)
        loc_spread = _location_spread_km(cluster)
        depth_spread = _spread(depths)

        disagree = bool(
            (mag_spread is not None and mag_spread > _MAG_SPREAD_THRESHOLD)
            or (loc_spread is not None and loc_spread > _LOCATION_SPREAD_THRESHOLD_KM)
        )

        local_auth = authority_for(prime.latitude, prime.longitude)
        agencies_present = {r.agency for r in cluster}

        events.append(
            ReconciledEvent(
                canonical_id=_build_canonical_id(prime),
                prime_report=prime,
                all_reports=sorted(cluster, key=lambda r: r.agency),
                local_authority_agency=local_auth,
                is_local_authority_in_set=local_auth in agencies_present if local_auth else False,
                magnitude_spread=mag_spread,
                location_spread_km=loc_spread,
                depth_spread_km=depth_spread,
                reports_disagree=disagree,
                magnitudes_by_agency={
                    r.agency: r.magnitude for r in cluster if r.magnitude is not None
                },
            )
        )

    events.sort(key=lambda e: e.prime_report.time_utc, reverse=True)
    return events
