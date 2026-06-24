"""AFAD (Disaster and Emergency Management Authority, Türkiye) adapter.

AFAD publishes a public JSON API at deprem.afad.gov.tr. It is the
authoritative network for events in Türkiye.

Docs (Turkish): https://deprem.afad.gov.tr/apiv2
Endpoint:       https://deprem.afad.gov.tr/apiv2/event/filter

Response is a JSON array of objects roughly like:

    {
      "eventID": "552519",
      "date": "2024-02-04T07:38:38.000Z",
      "latitude": "40.99",
      "longitude": "39.74",
      "depth": "5.0",
      "type": "ML",
      "magnitude": "1.5",
      "location": "Trabzon",
      "country": "Türkiye",
      "isEventUpdate": false,
      "lastUpdateDate": null
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from ..schemas import SourceReport
from .base import DEFAULT_TIMEOUT, USER_AGENT

_BASE_URL = "https://deprem.afad.gov.tr/apiv2/event/filter"
_EVENT_PAGE = "https://deprem.afad.gov.tr/event-detail/{id}"


def _to_iso(t: datetime) -> str:
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc).replace(tzinfo=None)
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_time(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).rstrip("Z")
        # AFAD timestamps look like "2024-02-04T07:38:38.000Z".
        if "." in s:
            head, frac = s.split(".", 1)
            frac = frac[:6]
            s = f"{head}.{frac}"
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_event(obj: dict) -> Optional[SourceReport]:
    event_id = obj.get("eventID") or obj.get("eventId") or obj.get("id")
    if not event_id:
        return None
    t = _parse_time(obj.get("date") or obj.get("eventDate"))
    lat = _parse_float(obj.get("latitude"))
    lon = _parse_float(obj.get("longitude"))
    if t is None or lat is None or lon is None:
        return None
    region = " / ".join(
        s for s in (obj.get("location"), obj.get("province"), obj.get("country")) if s
    ) or None
    return SourceReport(
        agency="AFAD",
        source_event_id=str(event_id),
        time_utc=t,
        latitude=lat,
        longitude=lon,
        depth_km=_parse_float(obj.get("depth")),
        magnitude=_parse_float(obj.get("magnitude")),
        magnitude_type=obj.get("type") or None,
        region_name=region,
        source_url=_EVENT_PAGE.format(id=event_id),
        is_reviewed=False,
    )


class AfadAdapter:
    agency = "AFAD"

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
    ) -> list[SourceReport]:
        params: dict[str, str] = {
            "start": _to_iso(start_time),
            "end": _to_iso(end_time),
            "orderby": "timedesc",
        }
        if min_magnitude is not None:
            params["minmag"] = str(min_magnitude)
        if max_magnitude is not None:
            params["maxmag"] = str(max_magnitude)
        if min_latitude is not None:
            params["minlat"] = str(min_latitude)
        if max_latitude is not None:
            params["maxlat"] = str(max_latitude)
        if min_longitude is not None:
            params["minlon"] = str(min_longitude)
        if max_longitude is not None:
            params["maxlon"] = str(max_longitude)

        try:
            resp = await client.get(
                _BASE_URL,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return []
        if resp.status_code >= 400:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        if not isinstance(data, list):
            return []

        # Client-side radius filter if requested (AFAD doesn't expose radius).
        results: list[SourceReport] = []
        for obj in data:
            rep = _parse_event(obj)
            if rep is None:
                continue
            if center_lat is not None and center_lon is not None and radius_km is not None:
                from ..matching import haversine_km
                if haversine_km(rep.latitude, rep.longitude, center_lat, center_lon) > radius_km:
                    continue
            results.append(rep)
            if len(results) >= limit:
                break
        return results

    async def get_by_id(
        self, client: httpx.AsyncClient, event_id: str
    ) -> Optional[SourceReport]:
        # AFAD's filter API has an `eventID` param.
        params = {"eventID": event_id}
        try:
            resp = await client.get(
                _BASE_URL,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return None
        if resp.status_code >= 400:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if not isinstance(data, list) or not data:
            return None
        return _parse_event(data[0])
