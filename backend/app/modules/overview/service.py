"""
Overview aggregation — real counts, cheap reads only.

No Groq, no heavy compute: DB count(*) queries and in-memory cache reads.
Each field degrades to null (not a fake number) if its source is
unavailable, so a struggling module shows "—" on the dashboard rather
than a lie.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("citadel.overview.service")

# There are exactly four modules per portal — a structural fact of the
# platform, not a metric to fetch.
GOV_MODULE_COUNT = 4
CITIZEN_MODULE_COUNT = 4


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable: %s", e)
        return None


def _count(table: str, **eq: Any) -> Optional[int]:
    """count(*) with optional equality filters. None if unreachable."""
    sb = _sb()
    if sb is None:
        return None
    try:
        q = sb.table(table).select("id", count="exact")
        for col, val in eq.items():
            q = q.eq(col, val)
        return (q.limit(1).execute()).count
    except Exception as e:  # noqa: BLE001
        log.debug("count %s failed: %s", table, e)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _anomaly_active_alerts() -> Optional[int]:
    """Live count from the anomaly in-memory cache (never triggers a fetch)."""
    try:
        from app.modules.anomaly_monitoring import service as anomaly

        return anomaly.list_alerts().get("counts", {}).get("total")
    except Exception as e:  # noqa: BLE001
        log.debug("anomaly alert count failed: %s", e)
        return None


def _stations_monitored() -> Optional[int]:
    try:
        from app.modules.anomaly_monitoring import sources

        return len(sources.METRO_STATIONS)
    except Exception:  # noqa: BLE001
        return None


def _kb_corpora() -> Optional[int]:
    """Loaded citizen-assistant knowledge corpora (in-memory tree count)."""
    try:
        from app.modules.citizen_assistant import service as assistant

        return assistant.health().get("corpora")
    except Exception as e:  # noqa: BLE001
        log.debug("kb corpora count failed: %s", e)
        return None


def gov_overview() -> dict[str, Any]:
    cams_active = _count("tv_cameras", status="active")
    cams_total = _count("tv_cameras")
    stations = _stations_monitored()

    # "Sensors online" = live traffic cameras + monitored anomaly stations.
    sensors_online = None
    if cams_active is not None or stations is not None:
        sensors_online = (cams_active or 0) + (stations or 0)

    inc_pending = _count("tv_incidents", status="PENDING_REVIEW")
    docs_pending = _count("documents", status="PENDING_REVIEW")
    pending_review = None
    if inc_pending is not None or docs_pending is not None:
        pending_review = (inc_pending or 0) + (docs_pending or 0)

    return {
        "role": "gov",
        "active_gateways": GOV_MODULE_COUNT,
        "sensors_online": sensors_online,
        "sensors_detail": {
            "cameras_active": cams_active,
            "cameras_total": cams_total,
            "stations_monitored": stations,
        },
        "active_alerts": _anomaly_active_alerts(),
        "pending_review": pending_review,
        "generated_at": _now(),
    }


def citizen_overview() -> dict[str, Any]:
    return {
        "role": "citizen",
        "active_services": CITIZEN_MODULE_COUNT,
        "kb_documents": _kb_corpora(),
        "community_issues": _count("tickets"),
        "analyses_run": _count("analyses"),
        "generated_at": _now(),
    }
