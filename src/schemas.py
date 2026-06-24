"""Canonical event schemas used across all adapters and tools.

Every adapter normalizes its agency's raw response into ``SourceReport``.
Matching and prime-selection then assemble ``ReconciledEvent`` objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SourceReport(BaseModel):
    """One agency's report of an earthquake."""

    agency: str = Field(..., description="Agency code, e.g. 'USGS', 'EMSC', 'JMA', 'INGV'.")
    source_event_id: str = Field(..., description="Native event ID at the reporting agency.")
    time_utc: datetime = Field(..., description="Origin time per this agency, UTC.")
    latitude: float
    longitude: float
    depth_km: Optional[float] = None
    magnitude: Optional[float] = None
    magnitude_type: Optional[str] = Field(
        None, description="e.g. 'Mw', 'Ml', 'mb', 'Md'. Different types are not directly comparable."
    )
    region_name: Optional[str] = None
    source_url: Optional[str] = None
    last_updated_utc: Optional[datetime] = None
    is_reviewed: bool = Field(
        False,
        description="True if this is a reviewed/final value (e.g. ISC bulletin, JMA final). Preliminary by default.",
    )


class ReconciledEvent(BaseModel):
    """One physical earthquake, with all known agency reports attached."""

    canonical_id: str = Field(
        ..., description="Stable identifier within this server; not globally canonical."
    )
    prime_report: SourceReport = Field(
        ..., description="The 'headline' single answer. See prime_selection.py for rules."
    )
    all_reports: list[SourceReport] = Field(
        ..., description="Every agency report grouped into this event."
    )
    local_authority_agency: Optional[str] = Field(
        None, description="Which agency is regionally authoritative for this event's location."
    )
    is_local_authority_in_set: bool = Field(
        False,
        description="True if a report from the local-authority agency is present in all_reports.",
    )

    # Discrepancy summary (computed)
    magnitude_spread: Optional[float] = Field(
        None, description="max(magnitude) - min(magnitude) across reports that have a magnitude."
    )
    location_spread_km: Optional[float] = Field(
        None, description="Max pairwise great-circle distance between epicenters, km."
    )
    depth_spread_km: Optional[float] = None
    reports_disagree: bool = Field(
        False,
        description="True if any spread exceeds the threshold (default: magnitude>0.4 or location>30km).",
    )

    magnitudes_by_agency: dict[str, float] = Field(
        default_factory=dict,
        description="Convenience map: {'USGS': 7.0, 'EMSC': 6.9, 'AFAD': 7.1}",
    )

    possible_duplicate_of: Optional[str] = Field(
        None,
        description="If matching was ambiguous, the canonical_id of another candidate cluster.",
    )


class FieldComparison(BaseModel):
    """One field's values across agencies for a single event."""

    field: str = Field(..., description="e.g. 'magnitude', 'latitude', 'depth_km', 'time_utc'.")
    values_by_agency: dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Raw value per agency, stringified (numbers, ISO timestamps, or null).",
    )
    spread: Optional[float] = Field(
        None,
        description="max-min for numeric fields. For time: seconds. None for non-numeric or single-report.",
    )
    unit: Optional[str] = Field(None, description="e.g. 'km', 'deg', 'seconds', or None.")


class SourceComparison(BaseModel):
    """Side-by-side per-field comparison of agency reports for one event."""

    canonical_id: str
    prime_agency: str
    local_authority_agency: Optional[str]
    agencies: list[str] = Field(..., description="Agency codes appearing in this comparison.")
    fields: list[FieldComparison]
    reports_disagree: bool


class AgencyInfo(BaseModel):
    """Static metadata about a seismic agency."""

    code: str
    full_name: str
    coverage: str
    is_authority_for: list[str]
    magnitude_completeness: str
    typical_latency_seconds: int
    notes: str
    adapter_supported: bool = Field(
        False,
        description="True if this server has a working adapter (FDSN or custom) for this agency.",
    )
    fdsn_base_url: Optional[str] = None
    event_page_template: Optional[str] = None
