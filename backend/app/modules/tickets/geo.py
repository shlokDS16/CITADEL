"""
Geospatial helpers — the PostGIS replacement for this project.

The spec called for `geo GEOGRAPHY(POINT,4326)` with a GIST index and
`ST_DWithin` radius queries. This Supabase project has no PostGIS
extension available (only vector, pgcrypto, uuid-ossp,
pg_stat_statements), so proximity is done app-side:

  * storage    — plain geo_lat / geo_lng doubles, plus an H3 cell id in
                 geo_h3 for cheap grouping
  * radius     — a latitude/longitude bounding box narrows the candidate
                 set in SQL (using ix_tickets_geo_latlng), then haversine
                 filters exactly in Python
  * clustering — group by H3 cell at a resolution chosen from the zoom

H3 resolution guide (approximate edge length):
    r6 ~3.2km   r7 ~1.2km   r8 ~460m   r9 ~174m   r10 ~65m
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

log = logging.getLogger("citadel.tickets.geo")

EARTH_RADIUS_KM = 6371.0
DEFAULT_H3_RESOLUTION = 8


def h3_available() -> bool:
    try:
        import h3  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def cell_for(lat: float, lng: float, resolution: int = DEFAULT_H3_RESOLUTION) -> Optional[str]:
    """H3 cell id for a point, or None when h3 is unavailable.

    Returning None rather than raising keeps ticket creation working on a
    box without h3 — the map degrades, submission does not.
    """
    try:
        import h3

        return h3.latlng_to_cell(float(lat), float(lng), int(resolution))
    except Exception as e:  # noqa: BLE001
        log.debug("h3 cell_for failed: %s", e)
        return None


def cell_center(cell: str) -> Optional[tuple[float, float]]:
    try:
        import h3

        lat, lng = h3.cell_to_latlng(cell)
        return float(lat), float(lng)
    except Exception as e:  # noqa: BLE001
        log.debug("h3 cell_center failed: %s", e)
        return None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lng, max_lng) enclosing the radius.

    A cheap SQL prefilter — it over-selects the box corners, which
    haversine then trims. Longitude degrees shrink with latitude, so the
    lng delta is divided by cos(lat); near the poles that blows up, hence
    the clamp.
    """
    lat_delta = radius_km / 111.0
    cos_lat = math.cos(math.radians(lat))
    lng_delta = radius_km / (111.0 * cos_lat) if abs(cos_lat) > 1e-6 else 180.0
    return (
        max(-90.0, lat - lat_delta),
        min(90.0, lat + lat_delta),
        max(-180.0, lng - lng_delta),
        min(180.0, lng + lng_delta),
    )


def resolution_for_radius(radius_km: float) -> int:
    """Pick an H3 resolution that yields a useful number of clusters for
    the area being viewed."""
    if radius_km <= 1:
        return 10
    if radius_km <= 3:
        return 9
    if radius_km <= 10:
        return 8
    if radius_km <= 30:
        return 7
    return 6


def cluster(rows: list[dict[str, Any]], resolution: int) -> list[dict[str, Any]]:
    """Group located tickets into H3 cells.

    Falls back to one cluster per ticket when h3 is unavailable, so the
    caller always gets a usable response shape.
    """
    if not h3_available():
        return [
            {
                "cell": None,
                "lat": r.get("geo_lat"),
                "lng": r.get("geo_lng"),
                "count": 1,
                "max_severity": r.get("priority") or "NORMAL",
                "ticket_ids": [r.get("id")],
            }
            for r in rows
            if r.get("geo_lat") is not None
        ]

    order = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "CRITICAL": 3}
    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        lat, lng = r.get("geo_lat"), r.get("geo_lng")
        if lat is None or lng is None:
            continue
        cell = cell_for(float(lat), float(lng), resolution)
        if cell is None:
            continue
        b = buckets.setdefault(cell, {
            "cell": cell,
            "lat": None,
            "lng": None,
            "count": 0,
            "max_severity": "LOW",
            "ticket_ids": [],
        })
        b["count"] += 1
        b["ticket_ids"].append(r.get("id"))
        pri = r.get("priority") or "NORMAL"
        if order.get(pri, 1) > order.get(b["max_severity"], 0):
            b["max_severity"] = pri

    for cell, b in buckets.items():
        centre = cell_center(cell)
        if centre:
            b["lat"], b["lng"] = centre
    return sorted(buckets.values(), key=lambda b: b["count"], reverse=True)
