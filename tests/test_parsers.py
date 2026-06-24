"""Parser unit tests for FDSN text, FDSN GeoJSON, JMA cod, AFAD JSON, IMO GeoJSON."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.adapters.afad import _parse_event as parse_afad_event
from src.adapters.fdsn import (
    FDSN_AGENCIES,
    _parse_fdsn_text,
    _parse_geojson_feature,
)
from src.adapters.imo import _parse_feature as parse_imo_feature
from src.adapters.jma import _parse_cod, _parse_event as parse_jma_event

USGS_CFG = FDSN_AGENCIES["USGS"]
NRCAN_CFG = FDSN_AGENCIES["NRCAN"]
SCEDC_CFG = FDSN_AGENCIES["SCEDC"]


# ----- FDSN text (header-aware) -----

def test_fdsn_text_standard_13col():
    body = (
        "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|"
        "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName\n"
        "us6000sze1|2026-05-22T01:06:52.614|16.5411|-46.5899|10.0|us|us||"
        "us6000sze1|mww|5.1|us|northern Mid-Atlantic Ridge\n"
    )
    reports = _parse_fdsn_text(body, USGS_CFG)
    assert len(reports) == 1
    r = reports[0]
    assert r.agency == "USGS"
    assert r.source_event_id == "us6000sze1"
    assert r.latitude == pytest.approx(16.5411)
    assert r.longitude == pytest.approx(-46.5899)
    assert r.depth_km == pytest.approx(10.0)
    assert r.magnitude == pytest.approx(5.1)
    assert r.magnitude_type == "mww"
    assert r.region_name == "northern Mid-Atlantic Ridge"
    assert r.time_utc == datetime(2026, 5, 22, 1, 6, 52, 614000, tzinfo=timezone.utc)
    assert r.source_url == "https://earthquake.usgs.gov/earthquakes/eventpage/us6000sze1"


def test_fdsn_text_nrcan_8col():
    """NRCAN's response is just EventID|Time|Lat|Lon|Depth|MagType|Mag|Location."""
    body = (
        "#EventID|Time|Latitude|Longitude|Depth/km|MagType|Magnitude|EventLocationName\n"
        "20260521.2108001|2026-05-21T21:08:24.000|58.4318|-137.2982|1|ML|3.01|"
        "168 km W of Juneau, AK/168 km O de Juneau, AK\n"
    )
    reports = _parse_fdsn_text(body, NRCAN_CFG)
    assert len(reports) == 1
    r = reports[0]
    assert r.magnitude_type == "ML"
    assert r.magnitude == pytest.approx(3.01)
    assert r.depth_km == 1.0
    assert r.region_name.startswith("168 km W of Juneau")


def test_fdsn_text_scedc_longtitude_typo():
    """SCEDC's header misspells Longitude — the parser still maps it."""
    body = (
        "#EventID  | Time                | Latitude | Longtitude | Depth/km | Author | "
        "Catalog | Contributor | ContributorID | MagType | Magnitude | MagAuthor | EventLocationName\n"
        "ci40123456|2026-05-21T12:00:00|34.05|-118.25|7.2|ci|ci|ci|ci40123456|ml|3.4|ci|Los Angeles\n"
    )
    reports = _parse_fdsn_text(body, SCEDC_CFG)
    assert len(reports) == 1
    assert reports[0].longitude == pytest.approx(-118.25)


def test_fdsn_text_handles_fractional_seconds_and_z():
    body = (
        "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|"
        "ContributorID|MagType|Magnitude|MagAuthor|EventLocationName\n"
        "e1|2026-05-22T01:06:52.123456789Z|0|0|10||||| mw |5.0||Somewhere\n"
    )
    reports = _parse_fdsn_text(body, USGS_CFG)
    assert len(reports) == 1
    # Fractional seconds get truncated to 6 digits for fromisoformat.
    assert reports[0].time_utc.microsecond == 123456


def test_fdsn_text_skips_unparseable_lines():
    body = (
        "#EventID|Time|Latitude|Longitude|Depth/km|MagType|Magnitude|EventLocationName\n"
        "good|2026-05-22T01:00:00|10|20|5|Ml|3.0|Place\n"
        "broken|not-a-date|10|20|5|Ml|3.0|Place\n"
        "tooshort|2026-05-22T01:00:00|10\n"
        "\n"
    )
    reports = _parse_fdsn_text(body, NRCAN_CFG)
    assert len(reports) == 1
    assert reports[0].source_event_id == "good"


def test_fdsn_text_no_header_falls_back_to_spec_columns():
    """If a server returns rows without a header line, parser uses default 13-col layout."""
    body = "us123|2026-05-22T01:00:00|10|20|15|us|us||us123|mb|4.5|us|Somewhere\n"
    reports = _parse_fdsn_text(body, USGS_CFG)
    assert len(reports) == 1
    assert reports[0].magnitude == 4.5
    assert reports[0].depth_km == 15.0


# ----- FDSN GeoJSON (USGS by-id) -----

def test_geojson_usgs_ms_epoch_time():
    feature = {
        "type": "Feature",
        "id": "us6000sze1",
        "geometry": {"type": "Point", "coordinates": [-46.5899, 16.5411, 10]},
        "properties": {
            "mag": 5.1,
            "place": "northern Mid-Atlantic Ridge",
            "time": 1779412012614,  # ms since epoch
            "magType": "mww",
            "status": "reviewed",
            "url": "https://example/usgs/url",
        },
    }
    r = _parse_geojson_feature(feature, USGS_CFG)
    assert r is not None
    assert r.source_event_id == "us6000sze1"
    assert r.latitude == pytest.approx(16.5411)
    assert r.longitude == pytest.approx(-46.5899)
    assert r.depth_km == 10.0
    assert r.magnitude == 5.1
    assert r.magnitude_type == "mww"
    assert r.is_reviewed is True
    assert r.time_utc.tzinfo == timezone.utc


def test_geojson_missing_geometry_returns_none():
    feature = {"type": "Feature", "id": "e1", "properties": {"time": 1779412012614}}
    assert _parse_geojson_feature(feature, USGS_CFG) is None


# ----- JMA cod parsing -----

def test_jma_cod_parses_lat_lon_depth():
    lat, lon, depth = _parse_cod("+37.5+141.4-50000/")
    assert lat == 37.5
    assert lon == 141.4
    assert depth == 50.0  # meters → km, sign flipped


def test_jma_cod_negative_lat():
    lat, lon, depth = _parse_cod("-12.3+45.6-10000/")
    assert lat == -12.3
    assert lon == 45.6
    assert depth == 10.0


def test_jma_event_jst_to_utc():
    obj = {
        "eid": "20260521120322",
        "at": "2026-05-21T21:00:00+09:00",  # JST
        "cod": "+38.9+142.0-50000/",
        "mag": "3.9",
        "anm_en": "Off Miyagi Pref.",
    }
    r = parse_jma_event(obj)
    assert r is not None
    assert r.time_utc == datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert r.latitude == 38.9
    assert r.magnitude == 3.9
    assert r.magnitude_type == "Mj"
    assert r.region_name == "Off Miyagi Pref."


def test_jma_event_skips_when_missing_required():
    assert parse_jma_event({"eid": "x"}) is None  # no time, no cod
    assert parse_jma_event({"at": "2026-05-21T12:00:00+09:00"}) is None  # no eid


# ----- AFAD parsing -----

def test_afad_event_parses_string_floats():
    obj = {
        "eventID": "552519",
        "date": "2026-05-22T02:55:19.000Z",
        "latitude": "40.99",
        "longitude": "39.74",
        "depth": "5.0",
        "type": "ML",
        "magnitude": "1.5",
        "location": "Trabzon",
        "province": "Trabzon",
        "country": "Türkiye",
    }
    r = parse_afad_event(obj)
    assert r is not None
    assert r.source_event_id == "552519"
    assert r.latitude == 40.99
    assert r.magnitude == 1.5
    assert r.magnitude_type == "ML"
    assert "Trabzon" in (r.region_name or "")
    assert r.source_url == "https://deprem.afad.gov.tr/event-detail/552519"


def test_afad_event_skips_missing_id():
    assert parse_afad_event({"latitude": "40", "longitude": "30"}) is None


# ----- IMO parsing -----

def test_imo_feature_prefers_mlw_over_ml_over_autmag():
    feat = {
        "properties": {
            "event_id": 999,
            "time": "2026-05-22T03:45:41.2",
            "depth": 7.6,
            "m_mlw": 2.5,
            "m_ml": 2.7,
            "m_autmag": 0.6,
            "originating_system": "SIL manual",
        },
        "geometry": {"type": "Point", "coordinates": [-21.40, 63.95]},
    }
    r = parse_imo_feature(feat)
    assert r is not None
    assert r.magnitude == 2.5
    assert r.magnitude_type == "Mlw"
    assert r.is_reviewed is True  # SIL manual


def test_imo_feature_falls_back_to_autmag():
    feat = {
        "properties": {
            "event_id": 1000,
            "time": "2026-05-22T03:45:41.2",
            "m_autmag": 0.4,
            "originating_system": "SIL aut.mag",
        },
        "geometry": {"type": "Point", "coordinates": [-21.4, 63.9]},
    }
    r = parse_imo_feature(feat)
    assert r is not None
    assert r.magnitude == 0.4
    assert r.magnitude_type == "Mautmag"
    assert r.is_reviewed is False


def test_imo_feature_skips_bad_geometry():
    feat = {"properties": {"event_id": 1, "time": "2026-05-22T03:45:41.2"}, "geometry": {"type": "Point", "coordinates": [None]}}
    assert parse_imo_feature(feat) is None
