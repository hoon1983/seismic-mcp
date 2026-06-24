"""Seismic MCP server entry point.

Run locally with stdio (for Claude Desktop / VS Code):
    uv run python server.py

The FastMCP `mcp.run()` call defaults to stdio; pass transport="http" for HTTP.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastmcp import FastMCP

from src.schemas import AgencyInfo, ReconciledEvent, SourceComparison, SourceReport
from src.tools.compare_sources import compare_sources as _compare_sources
from src.tools.find_discrepancies import find_discrepancies as _find_discrepancies
from src.tools.find_events import find_events as _find_events
from src.tools.get_agency_info import get_agency_info as _get_agency_info
from src.tools.get_agency_info import list_agencies as _list_agencies
from src.tools.get_event import get_event as _get_event
from src.tools.list_recent_by_agency import list_recent_by_agency as _list_recent_by_agency

SAFETY_NOTE = (
    "Reports earthquake data from multiple seismic agencies for research, "
    "journalism, situational awareness, and curiosity. NOT an early-warning "
    "system: events are reported AFTER shaking has already occurred where it "
    "was felt. Magnitudes and locations are preliminary and routinely revised; "
    "never make safety decisions based on a single reading."
)

mcp = FastMCP(
    "seismic-mcp",
    instructions=(
        "Unified earthquake data across USGS, EMSC, JMA, INGV, GeoNet, AFAD, "
        "and other agencies, with cross-agency report reconciliation. "
        + SAFETY_NOTE
    ),
)


@mcp.tool
async def find_events(
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
    limit: int = 50,
) -> list[ReconciledEvent]:
    """Find recent or historical earthquakes, reconciled across multiple seismic agencies.

    Queries every supported agency in parallel (~20 networks including USGS,
    EMSC, JMA, INGV, GeoNet, AFAD, and others) and clusters their reports so
    each returned event lists every agency that picked it up — the agent sees
    cross-network disagreement explicitly when it exists. Unreachable agencies
    fail gracefully and are skipped; a 60s TTL cache makes repeat queries cheap.

    Pass `agencies=["USGS", "EMSC", ...]` to restrict the source set. Use
    `list_agencies` to see all supported codes.

    NOT for emergency or early-warning use; data is preliminary.

    Defaults: last 24 hours, no magnitude filter, limit 50.
    """
    return await _find_events(
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
        limit=limit,
    )


@mcp.tool
async def get_event(canonical_id: str) -> Optional[ReconciledEvent]:
    """Fetch one reconciled event by canonical_id (format: 'AGENCY:event_id').

    Re-queries the seed agency by ID, then sweeps every supported agency in
    parallel within ±10 minutes and ~3° of the seed to find matching reports.
    Returns the reconciled cluster, or None if the seed cannot be found.

    Use canonical_ids from `find_events` (e.g. 'USGS:us6000sze1') to drill
    into a single event with the full cross-agency view.
    """
    return await _get_event(canonical_id)


@mcp.tool
async def compare_sources(canonical_id: str) -> Optional[SourceComparison]:
    """Side-by-side per-field comparison of every agency's report for one event.

    Returns a field-major view (magnitude, lat, lon, depth, time, ...) with
    one column per agency and the numeric spread per field. Use this when an
    agent needs to explain *why* sources disagree on a specific earthquake.
    """
    return await _compare_sources(canonical_id)


@mcp.tool
async def find_discrepancies(
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
    """Return events where agency reports disagree past the given thresholds.

    Same query params as `find_events`, plus tunable spread thresholds. By
    default keeps only events reported by 2+ agencies, since a lone report
    cannot disagree with itself. Useful for journalism, QA of preliminary
    feeds, or surfacing where the global picture is genuinely uncertain.
    """
    return await _find_discrepancies(
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
        min_magnitude_spread=min_magnitude_spread,
        min_location_spread_km=min_location_spread_km,
        require_multi_agency=require_multi_agency,
        limit=limit,
    )


@mcp.tool
async def list_recent_by_agency(
    agency: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    min_magnitude: Optional[float] = None,
    limit: int = 50,
) -> list[SourceReport]:
    """Raw recent events from a single agency, without cross-agency reconciliation.

    Returns `SourceReport` objects exactly as the agency reported them. Use
    this to see what one network alone is publishing (often includes small
    local events the global feeds miss) or to compare against the reconciled
    view from `find_events`.
    """
    return await _list_recent_by_agency(
        agency=agency,
        start_time=start_time,
        end_time=end_time,
        min_magnitude=min_magnitude,
        limit=limit,
    )


@mcp.tool
def get_agency_info(agency: str) -> Optional[AgencyInfo]:
    """Static metadata about a seismic agency: coverage, latency, magnitude completeness, notes.

    Use to interpret cross-agency disagreement (e.g. JMA magnitudes are
    systematically lower than USGS Mw for the same event) or to decide which
    agency is authoritative for a region.
    """
    return _get_agency_info(agency)


@mcp.tool
def list_agencies() -> list[str]:
    """All agency codes this server knows about (whether FDSN-wired or not)."""
    return _list_agencies()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
