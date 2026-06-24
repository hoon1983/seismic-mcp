"""compare_sources: per-field side-by-side view of agency reports for one event."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..schemas import FieldComparison, ReconciledEvent, SourceComparison, SourceReport
from .get_event import get_event


def _numeric_spread(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    return max(values) - min(values)


def _field_row(
    name: str,
    reports: list[SourceReport],
    extractor,
    unit: Optional[str] = None,
    formatter=str,
) -> FieldComparison:
    by_agency: dict[str, Optional[str]] = {}
    numeric: list[float] = []
    for r in reports:
        v = extractor(r)
        if v is None:
            by_agency[r.agency] = None
        else:
            by_agency[r.agency] = formatter(v)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric.append(float(v))
    return FieldComparison(
        field=name,
        values_by_agency=by_agency,
        spread=_numeric_spread(numeric),
        unit=unit,
    )


def comparison_from_event(event: ReconciledEvent) -> SourceComparison:
    reports = sorted(event.all_reports, key=lambda r: r.agency)
    agencies = [r.agency for r in reports]

    fields = [
        _field_row(
            "time_utc",
            reports,
            lambda r: r.time_utc.timestamp(),
            unit="seconds",
            formatter=lambda v: datetime.fromtimestamp(v, tz=timezone.utc).isoformat(),
        ),
        _field_row("magnitude", reports, lambda r: r.magnitude),
        _field_row("magnitude_type", reports, lambda r: r.magnitude_type),
        _field_row("latitude", reports, lambda r: r.latitude, unit="deg"),
        _field_row("longitude", reports, lambda r: r.longitude, unit="deg"),
        _field_row("depth_km", reports, lambda r: r.depth_km, unit="km"),
        _field_row("region_name", reports, lambda r: r.region_name),
        _field_row("is_reviewed", reports, lambda r: r.is_reviewed),
    ]

    return SourceComparison(
        canonical_id=event.canonical_id,
        prime_agency=event.prime_report.agency,
        local_authority_agency=event.local_authority_agency,
        agencies=agencies,
        fields=fields,
        reports_disagree=event.reports_disagree,
    )


async def compare_sources(canonical_id: str) -> Optional[SourceComparison]:
    event = await get_event(canonical_id)
    if event is None:
        return None
    return comparison_from_event(event)
