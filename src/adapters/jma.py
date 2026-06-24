"""JMA (Japan Meteorological Agency) adapter.

JMA does not offer a free FDSN endpoint. The public list of recent events is:

    https://www.jma.go.jp/bosai/quake/data/list.json

That JSON is a list (newest first) of objects like:

    {
      "rdt": "20260521120322",                # report time (JST)
      "ift": "20260521120000",                # forecast issue time
      "eid": "20260521120322",                # event id
      "ctt": "20260521120322",                # content time
      "ser": "1",
      "at":  "2026-05-21T12:00:22+09:00",     # origin time (JST)
      "anm": "Off Fukushima Pref.",            # English name (when present)
      "anm_en": "Off Fukushima Pref.",
      "cod": "+37.5+141.4-50000/",             # signed lat/lon/depth(meters), trailing /
      "mag": "4.5",
      "maxi": "2",                             # max JMA intensity (shindo)
      "ttl": "震源・震度に関する情報"
    }

The `cod` field is positional-signed lat+lon+depth (meters), terminated with /.
We pull magnitude, latitude, longitude, depth_km, and an English region name.

Magnitudes from JMA are Mj (JMA magnitude), systematically lower than Mw for
the same event above ~M7, per JMA's own documentation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..schemas import SourceReport
from .base import DEFAULT_TIMEOUT, USER_AGENT

_LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
_EVENT_PAGE = "https://www.jma.go.jp/bosai/quake/index.html?eid={id}"

# JMA `cod` is a sequence of signed decimals; e.g. "+37.5+141.4-50000/".
_COD_RE = re.compile(r"([+-]\d+(?:\.\d+)?)")


def _parse_cod(cod: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (lat, lon, depth_km) from a JMA `cod` string."""
    if not cod:
        return None, None, None
    parts = _COD_RE.findall(cod)
    if len(parts) < 2:
        return None, None, None
    try:
        lat = float(parts[0])
        lon = float(parts[1])
    except ValueError:
        return None, None, None
    depth_km: Optional[float] = None
    if len(parts) >= 3:
        try:
            # `cod` reports depth in meters, positive-down → flip sign and scale.
            depth_km = -float(parts[2]) / 1000.0
        except ValueError:
            pass
    return lat, lon, depth_km


def _parse_time(at: str) -> Optional[datetime]:
    """JMA `at` is JST (e.g. '2026-05-21T12:00:22+09:00'). Normalize to UTC."""
    if not at:
        return None
    try:
        dt = datetime.fromisoformat(at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _parse_event(obj: dict) -> Optional[SourceReport]:
    eid = obj.get("eid")
    at = obj.get("at")
    cod = obj.get("cod") or ""
    if not eid or not at:
        return None
    t = _parse_time(at)
    lat, lon, depth = _parse_cod(cod)
    if t is None or lat is None or lon is None:
        return None
    mag_raw = obj.get("mag")
    mag = None
    if mag_raw not in (None, ""):
        try:
            mag = float(mag_raw)
        except (TypeError, ValueError):
            mag = None
    region = obj.get("anm_en") or obj.get("anm") or None
    return SourceReport(
        agency="JMA",
        source_event_id=str(eid),
        time_utc=t,
        latitude=lat,
        longitude=lon,
        depth_km=depth,
        magnitude=mag,
        magnitude_type="Mj" if mag is not None else None,
        region_name=region,
        source_url=_EVENT_PAGE.format(id=eid),
        is_reviewed=False,
    )


class JmaAdapter:
    agency = "JMA"

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
        try:
            resp = await client.get(
                _LIST_URL,
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
        if not isinstance(data, list):
            return []

        # JMA can report the same earthquake multiple times (initial + updated
        # bulletins) under different `eid` values. Collapse to one report per
        # origin-time + epicenter signature, keeping the latest content time.
        from ..matching import haversine_km  # local import: avoid cycles

        deduped: dict[tuple, SourceReport] = {}
        for obj in data:
            rep = _parse_event(obj)
            if rep is None:
                continue
            if rep.time_utc < start_time or rep.time_utc > end_time:
                continue
            if min_magnitude is not None and (rep.magnitude is None or rep.magnitude < min_magnitude):
                continue
            if max_magnitude is not None and rep.magnitude is not None and rep.magnitude > max_magnitude:
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
            # Bucket within ~5s + ~5km of an earlier report → same physical event.
            key = (
                round(rep.time_utc.timestamp() / 5.0),
                round(rep.latitude * 20.0),  # ~0.05 deg buckets
                round(rep.longitude * 20.0),
            )
            prev = deduped.get(key)
            if prev is None or rep.source_event_id > prev.source_event_id:
                deduped[key] = rep

        reports = sorted(deduped.values(), key=lambda r: r.time_utc, reverse=True)
        return reports[:limit]

    async def get_by_id(
        self, client: httpx.AsyncClient, event_id: str
    ) -> Optional[SourceReport]:
        # No public per-event endpoint; scan the recent list.
        try:
            resp = await client.get(
                _LIST_URL,
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
        if not isinstance(data, list):
            return None
        for obj in data:
            if str(obj.get("eid")) == event_id:
                return _parse_event(obj)
        return None
