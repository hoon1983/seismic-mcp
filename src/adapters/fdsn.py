"""Generic FDSN-event adapter.

The FDSN web services specification covers most public seismic agencies (USGS,
EMSC, IRIS, GFZ, INGV, GeoNet, NOA, IPGP, NCEDC, SCEDC, ISC, SED). This single
adapter handles all of them; per-agency quirks are configured via FDSN_AGENCIES.

We use ``format=text`` because it's smaller, faster to parse, and avoids the
QuakeML XML pile. The format is a pipe-delimited table with one comment header
line starting with ``#``. Column order (FDSN-event 1.2):

    EventID | Time | Latitude | Longitude | Depth/km | Author | Catalog |
    Contributor | ContributorID | MagType | Magnitude | MagAuthor |
    EventLocationName
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

from ..schemas import SourceReport


@dataclass(frozen=True)
class FdsnAgencyConfig:
    code: str  # e.g. "USGS"
    base_url: str  # full FDSN query URL (no params)
    event_page: Optional[str] = None  # template with {id} placeholder for human-readable link
    default_reviewed: bool = False  # True for catalogs that are reviewed by default (e.g. ISC)


FDSN_AGENCIES: dict[str, FdsnAgencyConfig] = {
    "USGS": FdsnAgencyConfig(
        code="USGS",
        base_url="https://earthquake.usgs.gov/fdsnws/event/1/query",
        event_page="https://earthquake.usgs.gov/earthquakes/eventpage/{id}",
    ),
    "EMSC": FdsnAgencyConfig(
        code="EMSC",
        base_url="https://www.seismicportal.eu/fdsnws/event/1/query",
        event_page="https://www.seismicportal.eu/eventdetails.html?unid={id}",
    ),
    "IRIS": FdsnAgencyConfig(
        code="IRIS",
        base_url="https://service.iris.edu/fdsnws/event/1/query",
    ),
    "GFZ": FdsnAgencyConfig(
        code="GFZ",
        base_url="https://geofon.gfz.de/fdsnws/event/1/query",
        event_page="https://geofon.gfz.de/eqinfo/event.php?id={id}",
    ),
    "INGV": FdsnAgencyConfig(
        code="INGV",
        base_url="https://webservices.ingv.it/fdsnws/event/1/query",
        event_page="https://terremoti.ingv.it/event/{id}",
    ),
    "GeoNet": FdsnAgencyConfig(
        code="GeoNet",
        base_url="https://service.geonet.org.nz/fdsnws/event/1/query",
        event_page="https://www.geonet.org.nz/earthquake/{id}",
    ),
    "NOA": FdsnAgencyConfig(
        code="NOA",
        base_url="http://eida.gein.noa.gr/fdsnws/event/1/query",
    ),
    "IPGP": FdsnAgencyConfig(
        code="IPGP",
        base_url="https://ws.ipgp.fr/fdsnws/event/1/query",
    ),
    "NCEDC": FdsnAgencyConfig(
        code="NCEDC",
        base_url="https://service.ncedc.org/fdsnws/event/1/query",
    ),
    "SCEDC": FdsnAgencyConfig(
        code="SCEDC",
        base_url="https://service.scedc.caltech.edu/fdsnws/event/1/query",
    ),
    "SED": FdsnAgencyConfig(
        code="SED",
        base_url="http://eida.ethz.ch/fdsnws/event/1/query",
    ),
    "ISC": FdsnAgencyConfig(
        code="ISC",
        base_url="http://www.isc.ac.uk/fdsnws/event/1/query",
        default_reviewed=True,
    ),
    "BMKG": FdsnAgencyConfig(
        code="BMKG",
        base_url="https://geof.bmkg.go.id/fdsnws/event/1/query",
    ),
    "NIEP": FdsnAgencyConfig(
        code="NIEP",
        base_url="https://eida-sc3.infp.ro/fdsnws/event/1/query",
    ),
    "RESIF": FdsnAgencyConfig(
        code="RESIF",
        base_url="https://api.franceseisme.fr/fdsnws/event/1/query",
    ),
    "KNMI": FdsnAgencyConfig(
        code="KNMI",
        base_url="https://rdsa.knmi.nl/fdsnws/event/1/query",
    ),
    "NRCAN": FdsnAgencyConfig(
        code="NRCAN",
        base_url="https://earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query",
        event_page="https://earthquakescanada.nrcan.gc.ca/index-en.php?tpl_region=canada&tpl_output=print&id={id}",
    ),
}


# FDSN expects ISO-8601 without timezone suffix and without sub-second precision.
def _fdsn_time(t: datetime) -> str:
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc).replace(tzinfo=None)
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_float(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# Column name aliases. FDSN agencies vary the header text; map every known
# spelling to a canonical key.
_HEADER_ALIASES = {
    "eventid": "event_id",
    "time": "time",
    "latitude": "latitude",
    "longitude": "longitude",
    "longtitude": "longitude",  # SCEDC typo, preserved for compatibility
    "depth/km": "depth_km",
    "depth": "depth_km",
    "magtype": "mag_type",
    "magnitude": "magnitude",
    "eventlocationname": "region",
}


def _parse_header(line: str) -> Optional[dict[str, int]]:
    """Parse a `#col1|col2|...` header line into a {canonical_key: index} map."""
    if not line.startswith("#"):
        return None
    cols = [c.strip().lstrip("#").strip().lower() for c in line.split("|")]
    indexed: dict[str, int] = {}
    for i, c in enumerate(cols):
        key = _HEADER_ALIASES.get(c)
        if key and key not in indexed:
            indexed[key] = i
    # Need at least event_id, time, lat, lon to make a usable report.
    required = {"event_id", "time", "latitude", "longitude"}
    if not required.issubset(indexed):
        return None
    return indexed


# Default column order per FDSN-event 1.2 spec (when no header is present).
_DEFAULT_COLS = {
    "event_id": 0, "time": 1, "latitude": 2, "longitude": 3, "depth_km": 4,
    "mag_type": 9, "magnitude": 10, "region": 12,
}


def _parse_fdsn_text(body: str, cfg: FdsnAgencyConfig) -> list[SourceReport]:
    reports: list[SourceReport] = []
    cols: dict[str, int] = _DEFAULT_COLS  # may be replaced by an inline header
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            parsed = _parse_header(line)
            if parsed is not None:
                cols = parsed
            continue
        parts = [p.strip() for p in line.split("|")]
        max_needed = max(cols.values())
        if len(parts) <= max_needed:
            # Row is shorter than the header promises — skip rather than guess.
            continue

        event_id = parts[cols["event_id"]]
        time_str = parts[cols["time"]]
        try:
            if "." in time_str:
                head, frac = time_str.split(".", 1)
                frac = frac.rstrip("Z")[:6]
                time_str = f"{head}.{frac}"
            else:
                time_str = time_str.rstrip("Z")
            time_utc = datetime.fromisoformat(time_str).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        lat = _parse_float(parts[cols["latitude"]])
        lon = _parse_float(parts[cols["longitude"]])
        if lat is None or lon is None:
            continue
        depth = _parse_float(parts[cols["depth_km"]]) if "depth_km" in cols else None
        mag_type = (parts[cols["mag_type"]] or None) if "mag_type" in cols else None
        mag = _parse_float(parts[cols["magnitude"]]) if "magnitude" in cols else None
        region = (parts[cols["region"]] or None) if "region" in cols else None
        source_url = cfg.event_page.format(id=event_id) if cfg.event_page else None
        reports.append(
            SourceReport(
                agency=cfg.code,
                source_event_id=event_id,
                time_utc=time_utc,
                latitude=lat,
                longitude=lon,
                depth_km=depth,
                magnitude=mag,
                magnitude_type=mag_type,
                region_name=region or None,
                source_url=source_url,
                is_reviewed=cfg.default_reviewed,
            )
        )
    return reports


def _parse_geojson_feature(feature: dict, cfg: FdsnAgencyConfig) -> Optional[SourceReport]:
    """Parse one FDSN GeoJSON Feature into a SourceReport."""
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        return None
    lon, lat = coords[0], coords[1]
    depth = coords[2] if len(coords) >= 3 else None
    event_id = feature.get("id") or props.get("ids") or ""
    if not event_id:
        return None
    # FDSN GeoJSON `time` is ms since epoch (USGS) or ISO string (others).
    t_raw = props.get("time")
    if t_raw is None:
        return None
    try:
        if isinstance(t_raw, (int, float)):
            time_utc = datetime.fromtimestamp(t_raw / 1000.0, tz=timezone.utc)
        else:
            s = str(t_raw).rstrip("Z")
            time_utc = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None
    source_url = cfg.event_page.format(id=event_id) if cfg.event_page else props.get("url")
    return SourceReport(
        agency=cfg.code,
        source_event_id=str(event_id),
        time_utc=time_utc,
        latitude=float(lat),
        longitude=float(lon),
        depth_km=float(depth) if depth is not None else None,
        magnitude=float(props["mag"]) if props.get("mag") is not None else None,
        magnitude_type=props.get("magType") or None,
        region_name=props.get("place") or None,
        source_url=source_url,
        is_reviewed=cfg.default_reviewed or props.get("status") == "reviewed",
    )


class FdsnAdapter:
    """Async FDSN-event adapter. One instance per agency."""

    USER_AGENT = "seismic-mcp/0.1 (https://github.com/your/seismic-mcp)"

    def __init__(self, agency: str):
        if agency not in FDSN_AGENCIES:
            raise ValueError(f"Unknown FDSN agency: {agency}")
        self.cfg = FDSN_AGENCIES[agency]
        self.agency = agency

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
            "format": "text",
            "starttime": _fdsn_time(start_time),
            "endtime": _fdsn_time(end_time),
            "orderby": "time",
            "limit": str(min(max(limit, 1), 500)),
        }
        if min_magnitude is not None:
            params["minmagnitude"] = str(min_magnitude)
        if max_magnitude is not None:
            params["maxmagnitude"] = str(max_magnitude)
        if min_latitude is not None:
            params["minlatitude"] = str(min_latitude)
        if max_latitude is not None:
            params["maxlatitude"] = str(max_latitude)
        if min_longitude is not None:
            params["minlongitude"] = str(min_longitude)
        if max_longitude is not None:
            params["maxlongitude"] = str(max_longitude)
        if center_lat is not None and center_lon is not None and radius_km is not None:
            params["latitude"] = str(center_lat)
            params["longitude"] = str(center_lon)
            # FDSN uses degrees for maxradius; provide km via maxradiuskm where supported.
            params["maxradiuskm"] = str(radius_km)

        try:
            resp = await client.get(
                self.cfg.base_url,
                params=params,
                headers={"User-Agent": self.USER_AGENT, "Accept": "text/plain"},
                timeout=10.0,
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return []

        # FDSN convention: 204 No Content when zero events match. Treat as empty.
        if resp.status_code == 204:
            return []
        if resp.status_code >= 400:
            return []
        return _parse_fdsn_text(resp.text, self.cfg)

    async def get_by_id(
        self, client: httpx.AsyncClient, event_id: str
    ) -> Optional[SourceReport]:
        """Fetch a single event by its native agency event ID.

        Uses GeoJSON (format=geojson) because some FDSN servers (notably USGS)
        return empty text when combining format=text with eventid.
        """
        params = {"format": "geojson", "eventid": event_id}
        try:
            resp = await client.get(
                self.cfg.base_url,
                params=params,
                headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
                timeout=10.0,
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return None
        if resp.status_code == 204 or resp.status_code >= 400:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        # FDSN GeoJSON: either a Feature (single event) or a FeatureCollection.
        feature: Optional[dict] = None
        if isinstance(data, dict):
            if data.get("type") == "Feature":
                feature = data
            elif data.get("type") == "FeatureCollection":
                features = data.get("features") or []
                if features:
                    feature = features[0]
        if feature is None:
            return None
        return _parse_geojson_feature(feature, self.cfg)
