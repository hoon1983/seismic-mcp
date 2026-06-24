"""Common adapter protocol.

Every per-agency adapter (FDSN or custom) implements the same async `query`
signature so the orchestration in `find_events` / `get_event` can treat them
uniformly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

import httpx

from ..schemas import SourceReport


class SeismicAdapter(Protocol):
    agency: str

    async def query(
        self,
        client: httpx.AsyncClient,
        *,
        start_time: datetime,
        end_time: datetime,
        min_magnitude: Optional[float] = None,
        max_magnitude: Optional[float] = None,
        min_latitude: Optional[float] = None,
        max_latitude: Optional[float] = None,
        min_longitude: Optional[float] = None,
        max_longitude: Optional[float] = None,
        center_lat: Optional[float] = None,
        center_lon: Optional[float] = None,
        radius_km: Optional[float] = None,
        limit: int = 50,
    ) -> list[SourceReport]: ...

    async def get_by_id(
        self, client: httpx.AsyncClient, event_id: str
    ) -> Optional[SourceReport]: ...


USER_AGENT = "seismic-mcp/0.1 (https://pypi.org/project/seismic-mcp/)"
DEFAULT_TIMEOUT = 10.0
