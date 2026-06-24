"""HTTP frontend for seismic-mcp.

Wraps the same tool functions used by the MCP server and serves a small
single-page UI at `/`. Run with:

    uv run python web.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.adapters import supported_agencies
from src.cache import cache_stats, clear_caches
from src.schemas import AgencyInfo, ReconciledEvent, SourceComparison, SourceReport
from src.tools.compare_sources import compare_sources as _compare_sources
from src.tools.find_discrepancies import find_discrepancies as _find_discrepancies
from src.tools.find_events import find_events as _find_events
from src.tools.get_agency_info import get_agency_info as _get_agency_info
from src.tools.get_agency_info import list_agencies as _list_agencies
from src.tools.get_event import get_event as _get_event
from src.tools.list_recent_by_agency import list_recent_by_agency as _list_recent_by_agency

app = FastAPI(title="seismic-mcp web")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/api/agencies")
def agencies_supported() -> list[str]:
    """Agencies with a working adapter (FDSN or custom). These are queryable."""
    return sorted(supported_agencies())


@app.get("/api/all_agencies")
def all_agencies() -> list[str]:
    """All agencies with metadata, including ones without an adapter yet."""
    return _list_agencies()


@app.get("/api/cache_stats")
def api_cache_stats() -> dict:
    return cache_stats()


@app.post("/api/cache/clear")
def api_cache_clear() -> dict:
    clear_caches()
    return {"cleared": True}


@app.get("/api/find_events", response_model=list[ReconciledEvent])
async def api_find_events(
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
    agencies: Optional[list[str]] = Query(default=None),
    limit: int = 50,
) -> list[ReconciledEvent]:
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


@app.get("/api/find_discrepancies", response_model=list[ReconciledEvent])
async def api_find_discrepancies(
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
    agencies: Optional[list[str]] = Query(default=None),
    min_magnitude_spread: float = 0.4,
    min_location_spread_km: float = 30.0,
    require_multi_agency: bool = True,
    limit: int = 50,
) -> list[ReconciledEvent]:
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


@app.get("/api/event/{canonical_id:path}", response_model=ReconciledEvent)
async def api_get_event(canonical_id: str) -> ReconciledEvent:
    event = await _get_event(canonical_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"event not found: {canonical_id}")
    return event


@app.get("/api/compare/{canonical_id:path}", response_model=SourceComparison)
async def api_compare_sources(canonical_id: str) -> SourceComparison:
    comparison = await _compare_sources(canonical_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail=f"event not found: {canonical_id}")
    return comparison


@app.get("/api/recent/{agency}", response_model=list[SourceReport])
async def api_list_recent_by_agency(
    agency: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    min_magnitude: Optional[float] = None,
    limit: int = 50,
) -> list[SourceReport]:
    if agency not in supported_agencies():
        raise HTTPException(status_code=400, detail=f"no adapter for agency: {agency}")
    return await _list_recent_by_agency(
        agency=agency,
        start_time=start_time,
        end_time=end_time,
        min_magnitude=min_magnitude,
        limit=limit,
    )


@app.get("/api/agency_info/{agency}", response_model=AgencyInfo)
def api_get_agency_info(agency: str) -> AgencyInfo:
    info = _get_agency_info(agency)
    if info is None:
        raise HTTPException(status_code=404, detail=f"unknown agency: {agency}")
    return info


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("web:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
