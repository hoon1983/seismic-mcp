"""IMO (Icelandic Meteorological Office) adapter.

IMO publishes a public REST API at api.vedur.is. The earthquakes endpoint is

    GET https://api.vedur.is/skjalftalisa/quakes
        ?start_time=YYYY-MM-DDTHH:MM:SSZ
        &end_time=YYYY-MM-DDTHH:MM:SSZ
        &size_min=...&size_max=...
        &area_id=... (optional)

Default response is GeoJSON. Each feature looks like:

    {
      "type": "Feature",
      "properties": {
        "event_id": 1439471,
        "time": "2026-05-20T03:40:57.8",        # UTC, naive
        "originating_system": "SIL aut.mag",     # or "SIL manual"
        "depth": 5.2,                            # km
        "m_autmag": 0.4,                         # one of m_autmag / m_ml / m_mlw
        "event_type": "qu",
        "quality": 63.3
      },
      "geometry": {"type": "Point", "coordinates": [-21.385, 63.963]}
    }

We prefer m_mlw > m_ml > m_autmag for magnitude (Mlw is moment magnitude;
m_autmag is the automatic preliminary value).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from ..schemas import SourceReport
from .base import DEFAULT_TIMEOUT, USER_AGENT

_QUERY_URL = "https://api.vedur.is/skjalftalisa/quakes"
_EVENT_URL = "https://api.vedur.is/skjalftalisa/quakes/{id}"
_EVENT_PAGE = "https://en.vedur.is/earthquakes-and-volcanism/earthquakes/"


def _iso_utc(t: datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _parse_time(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).rstrip("Z")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _pick_magnitude(props: dict) -> tuple[Optional[float], Optional[str]]:
    # Reviewed-first: Mlw (moment) > Ml > automatic mag.
    for key, label in (("m_mlw", "Mlw"), ("m_ml", "Ml"), ("m_autmag", "Mautmag")):
        v = _safe_float(props.get(key))
        if v is not None:
            return v, label
    return None, None


def _parse_feature(feat: dict) -> Optional[SourceReport]:
    props = feat.get("properties") or {}
    geom = feat.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        return None
    lon = _safe_float(coords[0])
    lat = _safe_float(coords[1])
    if lat is None or lon is None:
        return None
    event_id = props.get("event_id")
    if event_id is None:
        return None
    t = _parse_time(props.get("time"))
    if t is None:
        return None
    mag, mag_type = _pick_magnitude(props)
    is_reviewed = props.get("originating_system") == "SIL manual"
    return SourceReport(
        agency="IMO",
        source_event_id=str(event_id),
        time_utc=t,
        latitude=lat,
        longitude=lon,
        depth_km=_safe_float(props.get("depth")),
        magnitude=mag,
        magnitude_type=mag_type,
        region_name="Iceland",
        source_url=_EVENT_PAGE,
        is_reviewed=is_reviewed,
    )


class ImoAdapter:
    agency = "IMO"

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
            "start_time": _iso_utc(start_time),
            "end_time": _iso_utc(end_time),
        }
        if min_magnitude is not None:
            params["size_min"] = str(min_magnitude)
        if max_magnitude is not None:
            params["size_max"] = str(max_magnitude)

        try:
            resp = await client.get(
                _QUERY_URL,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError:
            return []
        if resp.status_code >= 400:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        features = data.get("features") if isinstance(data, dict) else None
        if not isinstance(features, list):
            return []

        from ..matching import haversine_km

        reports: list[SourceReport] = []
        for feat in features:
            rep = _parse_feature(feat)
            if rep is None:
                continue
            if min_latitude is not None and rep.latitude < min_latitude:
                continue
            if max_latitude is not None and rep.latitude > max_latitude:
                continue
            if min_longitude is not None and rep.longitude < min_longitude:
                continue
            if max_longitude is not None and rep.longitude > max_longitude:
                continue
            if center_lat is not None and center_lon is not None and radius_km is not None:
                if haversine_km(rep.latitude, rep.longitude, center_lat, center_lon) > radius_km:
                    continue
            reports.append(rep)
        reports.sort(key=lambda r: r.time_utc, reverse=True)
        return reports[:limit]

    async def get_by_id(
        self, client: httpx.AsyncClient, event_id: str
    ) -> Optional[SourceReport]:
        try:
            resp = await client.get(
                _EVENT_URL.format(id=event_id),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError:
            return None
        if resp.status_code >= 400:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        # /quakes/{id} returns a single Feature; some impls return a FeatureCollection.
        if isinstance(data, dict):
            if data.get("type") == "Feature":
                return _parse_feature(data)
            if data.get("type") == "FeatureCollection":
                feats = data.get("features") or []
                return _parse_feature(feats[0]) if feats else None
        return None
