"""
Live data sources for Anomaly Monitoring.

Everything here is REAL, free and key-less. We poll a handful of public
scientific feeds and normalise them into a single `SensorReading` shape so
the detector (`detect.py`) doesn't care where a number came from.

Feeds
-----
- Open-Meteo Air Quality  https://air-quality-api.open-meteo.com/v1/air-quality
    multi-coordinate, current PM2.5/PM10/NO2/O3/SO2/CO + US AQI
- Open-Meteo Forecast     https://api.open-meteo.com/v1/forecast
    multi-coordinate, current temp / wind / precipitation
- Open-Meteo Flood        https://flood-api.open-meteo.com/v1/flood
    per-coordinate daily river discharge
- USGS Earthquakes        https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
    global seismic events (we keep ones within the India bounding box +
    globally significant M>=5.5)

All fetches are wrapped so a single feed failing never takes the module
down — we just emit fewer readings that cycle.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("citadel.anomaly_monitoring.sources")

# ----------------------------------------------------------------------
# Station registry — real Indian metro coordinates.
# Each becomes a virtual "sensor cluster": one air-quality probe, one
# weather probe and one hydrology probe co-located at the city centroid.
# ----------------------------------------------------------------------
METRO_STATIONS: list[dict[str, Any]] = [
    {"id": "DEL", "city": "Delhi",       "zone": "NCT Delhi",        "lat": 28.6139, "lng": 77.2090, "river": "Yamuna"},
    {"id": "MUM", "city": "Mumbai",      "zone": "Maharashtra",      "lat": 19.0760, "lng": 72.8777, "river": "Mithi"},
    {"id": "BLR", "city": "Bengaluru",   "zone": "Karnataka",        "lat": 12.9716, "lng": 77.5946, "river": "Vrishabhavathi"},
    {"id": "MAA", "city": "Chennai",     "zone": "Tamil Nadu",       "lat": 13.0827, "lng": 80.2707, "river": "Cooum"},
    {"id": "CCU", "city": "Kolkata",     "zone": "West Bengal",      "lat": 22.5726, "lng": 88.3639, "river": "Hooghly"},
    {"id": "HYD", "city": "Hyderabad",   "zone": "Telangana",        "lat": 17.3850, "lng": 78.4867, "river": "Musi"},
    {"id": "PNQ", "city": "Pune",        "zone": "Maharashtra",      "lat": 18.5204, "lng": 73.8567, "river": "Mula-Mutha"},
    {"id": "AMD", "city": "Ahmedabad",   "zone": "Gujarat",          "lat": 23.0225, "lng": 72.5714, "river": "Sabarmati"},
    {"id": "JAI", "city": "Jaipur",      "zone": "Rajasthan",        "lat": 26.9124, "lng": 75.7873, "river": "Dravyavati"},
    {"id": "LKO", "city": "Lucknow",     "zone": "Uttar Pradesh",    "lat": 26.8467, "lng": 80.9462, "river": "Gomti"},
    {"id": "NAG", "city": "Nagpur",      "zone": "Maharashtra",      "lat": 21.1458, "lng": 79.0882, "river": "Nag"},
    {"id": "PAT", "city": "Patna",       "zone": "Bihar",            "lat": 25.5941, "lng": 85.1376, "river": "Ganga"},
    {"id": "BHO", "city": "Bhopal",      "zone": "Madhya Pradesh",   "lat": 23.2599, "lng": 77.4126, "river": "Betwa"},
    {"id": "GUW", "city": "Guwahati",    "zone": "Assam",            "lat": 26.1445, "lng": 91.7362, "river": "Brahmaputra"},
    {"id": "CHD", "city": "Chandigarh",  "zone": "Punjab/Haryana",   "lat": 30.7333, "lng": 76.7794, "river": "Sukhna"},
    {"id": "KOC", "city": "Kochi",       "zone": "Kerala",           "lat": 9.9312,  "lng": 76.2673, "river": "Periyar"},
]

# India bounding box (rough) for filtering the global USGS feed.
_IN_BBOX = {"lat_min": 6.0, "lat_max": 37.5, "lng_min": 68.0, "lng_max": 97.5}

_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
_WX_URL = "https://api.open-meteo.com/v1/forecast"
_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
_USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"

_HTTP_TIMEOUT = 25.0


def _csv(vals: list[float]) -> str:
    return ",".join(f"{v:.4f}" for v in vals)


def fetch_air_quality() -> dict[str, dict[str, Any]]:
    """
    One multi-coordinate call → {station_id: {pm2_5, pm10, no2, o3, so2,
    co, us_aqi, dust}}. Open-Meteo accepts comma-separated lat/lng and
    returns a list aligned to input order.
    """
    lats = [s["lat"] for s in METRO_STATIONS]
    lngs = [s["lng"] for s in METRO_STATIONS]
    params = {
        "latitude": _csv(lats),
        "longitude": _csv(lngs),
        "current": "pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide,us_aqi,dust",
        "timezone": "auto",
    }
    out: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(_AQ_URL, params=params)
            r.raise_for_status()
            data = r.json()
        # When multiple coords are requested Open-Meteo returns a list;
        # a single coord returns a bare object. Normalise to a list.
        items = data if isinstance(data, list) else [data]
        for st, item in zip(METRO_STATIONS, items):
            cur = (item or {}).get("current") or {}
            out[st["id"]] = {
                "pm2_5": cur.get("pm2_5"),
                "pm10": cur.get("pm10"),
                "no2": cur.get("nitrogen_dioxide"),
                "o3": cur.get("ozone"),
                "so2": cur.get("sulphur_dioxide"),
                "co": cur.get("carbon_monoxide"),
                "us_aqi": cur.get("us_aqi"),
                "dust": cur.get("dust"),
                "observed_at": cur.get("time"),
            }
    except Exception as e:
        log.warning("air-quality fetch failed: %s", e)
    return out


def fetch_weather() -> dict[str, dict[str, Any]]:
    """{station_id: {temp_c, wind_kph, precip_mm, observed_at}}."""
    lats = [s["lat"] for s in METRO_STATIONS]
    lngs = [s["lng"] for s in METRO_STATIONS]
    params = {
        "latitude": _csv(lats),
        "longitude": _csv(lngs),
        "current": "temperature_2m,wind_speed_10m,precipitation,relative_humidity_2m",
        "timezone": "auto",
    }
    out: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(_WX_URL, params=params)
            r.raise_for_status()
            data = r.json()
        items = data if isinstance(data, list) else [data]
        for st, item in zip(METRO_STATIONS, items):
            cur = (item or {}).get("current") or {}
            out[st["id"]] = {
                "temp_c": cur.get("temperature_2m"),
                "wind_kph": cur.get("wind_speed_10m"),
                "precip_mm": cur.get("precipitation"),
                "humidity": cur.get("relative_humidity_2m"),
                "observed_at": cur.get("time"),
            }
    except Exception as e:
        log.warning("weather fetch failed: %s", e)
    return out


def fetch_flood() -> dict[str, dict[str, Any]]:
    """
    River discharge (m³/s). The flood API only takes a single coordinate
    per call but it's cheap; we batch with comma-separated coords which
    the endpoint also supports.
    """
    lats = [s["lat"] for s in METRO_STATIONS]
    lngs = [s["lng"] for s in METRO_STATIONS]
    params = {
        "latitude": _csv(lats),
        "longitude": _csv(lngs),
        "daily": "river_discharge,river_discharge_mean",
        "forecast_days": 1,
    }
    out: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(_FLOOD_URL, params=params)
            r.raise_for_status()
            data = r.json()
        items = data if isinstance(data, list) else [data]
        for st, item in zip(METRO_STATIONS, items):
            daily = (item or {}).get("daily") or {}
            disc = (daily.get("river_discharge") or [None])
            mean = (daily.get("river_discharge_mean") or [None])
            out[st["id"]] = {
                "river_discharge": disc[0] if disc else None,
                "river_discharge_mean": mean[0] if mean else None,
            }
    except Exception as e:
        log.warning("flood fetch failed: %s", e)
    return out


def fetch_earthquakes(india_only: bool = False) -> list[dict[str, Any]]:
    """
    USGS last-24h feed. Returns normalised quake events. We keep events
    inside the India bbox plus globally significant ones (M>=5.5) so the
    'seismic / structural' category always has signal to show.
    """
    out: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(_USGS_URL)
            r.raise_for_status()
            data = r.json()
        for feat in data.get("features", []) or []:
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None, None]
            lng, lat, depth = coords[0], coords[1], coords[2] if len(coords) > 2 else None
            mag = props.get("mag")
            if lat is None or lng is None or mag is None:
                continue
            in_india = (
                _IN_BBOX["lat_min"] <= lat <= _IN_BBOX["lat_max"]
                and _IN_BBOX["lng_min"] <= lng <= _IN_BBOX["lng_max"]
            )
            if india_only and not in_india:
                continue
            if not in_india and mag < 5.5:
                continue  # global noise filter
            out.append({
                "usgs_id": feat.get("id"),
                "mag": mag,
                "place": props.get("place"),
                "time_ms": props.get("time"),
                "lat": lat,
                "lng": lng,
                "depth_km": depth,
                "tsunami": props.get("tsunami", 0),
                "felt": props.get("felt"),
                "url": props.get("url"),
                "in_india": in_india,
            })
        out.sort(key=lambda e: e.get("mag") or 0, reverse=True)
    except Exception as e:
        log.warning("USGS fetch failed: %s", e)
    return out


def fetch_all() -> dict[str, Any]:
    """
    Pull every feed once. Returns a single dict the service layer caches.
    Resilient: any sub-feed that fails just contributes an empty section.
    """
    t0 = time.time()
    aq = fetch_air_quality()
    wx = fetch_weather()
    fl = fetch_flood()
    eq = fetch_earthquakes()
    elapsed = round(time.time() - t0, 2)
    log.info(
        "anomaly sources fetched: aq=%d wx=%d flood=%d quakes=%d in %ss",
        len(aq), len(wx), len(fl), len(eq), elapsed,
    )
    return {
        "air_quality": aq,
        "weather": wx,
        "flood": fl,
        "earthquakes": eq,
        "fetch_seconds": elapsed,
    }
