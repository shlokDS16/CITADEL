"""
Anomaly Monitoring — service layer.

A daemon thread refreshes every live feed on a fixed cadence, runs the
detector, attaches an impact brief to each anomaly, and caches the whole
rollup in memory. HTTP handlers read the cache (instant) — they never
block on the upstream APIs.

State that must survive a refresh (acks, work orders) is kept in small
in-memory dicts keyed by a stable alert fingerprint, plus a best-effort
write to Supabase `am_*` tables when they exist (degrades silently).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.modules.anomaly_monitoring import detect, playbook, sources

log = logging.getLogger("citadel.anomaly_monitoring.service")

_REFRESH_SECS = 120  # feeds update slowly; 2-min cadence is plenty
_CACHE: dict[str, Any] = {"ts": 0.0, "alerts": [], "raw": None, "generated_at": None}
_CACHE_LOCK = threading.Lock()
_BG_THREAD: Optional[threading.Thread] = None
_BG_STOP = threading.Event()

# Stable per-anomaly state across refreshes (alerts are recomputed each cycle)
_ACK_STATE: dict[str, dict[str, Any]] = {}      # fp -> {acked, actor, at}
_WORK_ORDERS: dict[str, dict[str, Any]] = {}    # wo_id -> order
_WO_SEQ = {"n": 3840}


def _fingerprint(category: str, station_id: str, metric: str) -> str:
    """Stable id for an anomaly so ack/work-order survive recompute."""
    h = hashlib.md5(f"{category}|{station_id}|{metric}".encode()).hexdigest()[:8]
    return f"ANM-{h.upper()}"


def _supabase_safe():
    try:
        from app.database import get_supabase
        return get_supabase()
    except Exception:
        return None


def _audit(action: str, entity_id: str, actor: str, payload: dict[str, Any]) -> None:
    sb = _supabase_safe()
    if not sb:
        return
    try:
        sb.table("am_audit_log").insert({
            "entity_type": "alert", "entity_id": entity_id,
            "action": action, "actor": actor, "payload": payload,
        }).execute()
    except Exception:
        pass  # table may not exist — non-fatal


# ----------------------------------------------------------------------
# Core: build the alert list from a raw source snapshot
# ----------------------------------------------------------------------
def _build_alerts(raw: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    alerts: list[dict[str, Any]] = []
    st_by_id = {s["id"]: s for s in sources.METRO_STATIONS}

    aq = raw.get("air_quality") or {}
    wx = raw.get("weather") or {}
    fl = raw.get("flood") or {}

    for st in sources.METRO_STATIONS:
        sid = st["id"]
        findings: list[dict[str, Any]] = []
        findings += detect.score_air_quality(st, aq.get(sid) or {})
        findings += detect.score_weather(st, wx.get(sid) or {})
        findings += detect.score_flood(st, fl.get(sid) or {})
        for f in findings:
            fp = _fingerprint(f["category"], sid, f["metric"])
            impact = playbook.build_impact(f["category"], f["severity"])
            impact["affected_zones"] = playbook.affected_zones(st, impact["impact_radius_km"])
            ack = _ACK_STATE.get(fp, {})
            alerts.append({
                "id": fp,
                "title": f"{f['metric']} anomaly — {st['city']}",
                "category": f["category"],
                "severity": f["severity"],
                "confidence": int(f["confidence"]),
                "metric": f["metric"],
                "value": f["value"],
                "unit": f["unit"],
                "threshold": f["threshold"],
                "city": st["city"],
                "zone": st["zone"],
                "station_id": sid,
                "lat": st["lat"],
                "lng": st["lng"],
                "detected_at": now_iso,
                "why": f["why"],
                "acked": bool(ack.get("acked")),
                "status": ack.get("status", "open"),
                "source": "open-meteo",
                "impact": impact,
            })

    # USGS earthquakes — independent of metro stations
    for eq in raw.get("earthquakes") or []:
        scored = detect.score_earthquake(eq)
        if not scored:
            continue
        # nearest metro for naming / zone context
        nearest = min(
            sources.METRO_STATIONS,
            key=lambda s: (s["lat"] - eq["lat"]) ** 2 + (s["lng"] - eq["lng"]) ** 2,
        )
        fp = f"ANM-EQ{(eq.get('usgs_id') or '')[-6:].upper()}"
        impact = playbook.build_impact(scored["category"], scored["severity"])
        impact["affected_zones"] = [
            eq.get("place") or "Epicentre region",
            f"~{impact['impact_radius_km']:.0f} km felt radius",
        ]
        ms = eq.get("time_ms")
        det_iso = (
            datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
            if ms else now_iso
        )
        ack = _ACK_STATE.get(fp, {})
        alerts.append({
            "id": fp,
            "title": f"M{eq['mag']:.1f} earthquake — {(eq.get('place') or 'Unknown')[:60]}",
            "category": scored["category"],
            "severity": scored["severity"],
            "confidence": int(scored["confidence"]),
            "metric": scored["metric"],
            "value": scored["value"],
            "unit": scored["unit"],
            "threshold": scored["threshold"],
            "city": nearest["city"] if eq.get("in_india") else (eq.get("place") or "—"),
            "zone": nearest["zone"] if eq.get("in_india") else "International",
            "station_id": "USGS",
            "lat": eq["lat"],
            "lng": eq["lng"],
            "detected_at": det_iso,
            "why": scored["why"],
            "acked": bool(ack.get("acked")),
            "status": ack.get("status", "open"),
            "source": "usgs",
            "impact": impact,
        })

    sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    alerts.sort(key=lambda a: (sev_rank.get(a["severity"], 0), a["confidence"]), reverse=True)
    return alerts


def _refresh_once() -> None:
    raw = sources.fetch_all()
    alerts = _build_alerts(raw)
    with _CACHE_LOCK:
        _CACHE["raw"] = raw
        _CACHE["alerts"] = alerts
        _CACHE["ts"] = time.time()
        _CACHE["generated_at"] = datetime.now(timezone.utc).isoformat()
    log.info("anomaly cache refreshed: %d alerts", len(alerts))


def _ensure_fresh() -> None:
    """Lazy first-load / staleness guard for HTTP handlers."""
    with _CACHE_LOCK:
        ts = _CACHE["ts"]
        have = _CACHE["alerts"] is not None and ts > 0
    if not have or (time.time() - ts) > _REFRESH_SECS * 2:
        try:
            _refresh_once()
        except Exception as e:
            log.warning("anomaly refresh failed: %s", e)


def _bg_loop() -> None:
    # initial load immediately, then every _REFRESH_SECS
    try:
        _refresh_once()
    except Exception as e:
        log.warning("initial anomaly refresh failed: %s", e)
    while not _BG_STOP.wait(_REFRESH_SECS):
        try:
            _refresh_once()
        except Exception as e:
            log.warning("anomaly bg refresh failed: %s", e)


def start_background_refresh() -> None:
    global _BG_THREAD
    if _BG_THREAD and _BG_THREAD.is_alive():
        return
    _BG_STOP.clear()
    _BG_THREAD = threading.Thread(target=_bg_loop, name="anomaly-refresh", daemon=True)
    _BG_THREAD.start()
    log.info("Anomaly Monitoring: background refresh loop started")


def stop_background_refresh() -> None:
    _BG_STOP.set()


# ----------------------------------------------------------------------
# Read APIs (served from cache)
# ----------------------------------------------------------------------
def _alerts_snapshot() -> tuple[list[dict[str, Any]], str]:
    _ensure_fresh()
    with _CACHE_LOCK:
        return list(_CACHE["alerts"] or []), (_CACHE["generated_at"] or datetime.now(timezone.utc).isoformat())


def list_alerts(severity: Optional[str] = None, category: Optional[str] = None,
                status: Optional[str] = None) -> dict[str, Any]:
    alerts, gen = _alerts_snapshot()
    # Resolved alerts are off the active board unless explicitly requested.
    if (status or "").lower() != "resolved":
        alerts = [a for a in alerts if a["status"] != "resolved"]
    if severity:
        alerts = [a for a in alerts if a["severity"] == severity.upper()]
    if category:
        alerts = [a for a in alerts if a["category"].lower() == category.lower()]
    if status:
        alerts = [a for a in alerts if a["status"] == status.lower()]
    counts = {"total": len(alerts), "CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0,
              "unacked": 0, "acked": 0, "resolved": 0}
    for a in alerts:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1
        if a["status"] == "resolved":
            counts["resolved"] += 1
        elif a["acked"]:
            counts["acked"] += 1
        else:
            counts["unacked"] += 1
    return {"total": len(alerts), "counts": counts, "generated_at": gen, "alerts": alerts}


def get_alert(alert_id: str) -> Optional[dict[str, Any]]:
    alerts, _ = _alerts_snapshot()
    return next((a for a in alerts if a["id"] == alert_id), None)


def list_sensors() -> dict[str, Any]:
    _ensure_fresh()
    with _CACHE_LOCK:
        raw = _CACHE["raw"] or {}
    aq = raw.get("air_quality") or {}
    wx = raw.get("weather") or {}
    fl = raw.get("flood") or {}
    rows: list[dict[str, Any]] = []
    online = warning = offline = 0
    for st in sources.METRO_STATIONS:
        sid = st["id"]
        triples = [
            ("AQ", "Air Quality", aq.get(sid, {}).get("us_aqi"), "AQI"),
            ("WX", "Weather", wx.get(sid, {}).get("temp_c"), "°C"),
            ("HY", "Hydrology", fl.get(sid, {}).get("river_discharge"), "m³/s"),
        ]
        for suf, typ, val, unit in triples:
            if val is None:
                health, offline = "offline", offline + 1
            elif suf == "AQ" and val and val > 150:
                health, warning = "warning", warning + 1
            elif suf == "WX" and val is not None and (val >= 43 or val <= 4):
                health, warning = "warning", warning + 1
            else:
                health, online = "healthy", online + 1
            rows.append({
                "id": f"SNS-{sid}-{suf}",
                "city": st["city"], "zone": st["zone"], "type": typ,
                "lat": st["lat"], "lng": st["lng"],
                "metric": typ, "value": round(val, 1) if isinstance(val, (int, float)) else None,
                "unit": unit, "health": health,
                "last_seen": "live" if val is not None else "stale",
            })
    return {"total": len(rows), "online": online, "warning": warning,
            "offline": offline, "sensors": rows}


def map_data() -> dict[str, Any]:
    alerts, gen = _alerts_snapshot()
    alerts = [a for a in alerts if a["status"] != "resolved"]
    by_station: dict[str, list[dict[str, Any]]] = {}
    for a in alerts:
        by_station.setdefault(a["station_id"], []).append(a)
    sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    zones: list[dict[str, Any]] = []
    for st in sources.METRO_STATIONS:
        st_alerts = by_station.get(st["id"], [])
        if st_alerts:
            worst = max(st_alerts, key=lambda a: sev_rank.get(a["severity"], 0))
            level = {"CRITICAL": "critical", "HIGH": "high",
                     "MEDIUM": "medium", "LOW": "nominal"}[worst["severity"]]
            summary = f"{len(st_alerts)} active · worst: {worst['metric']} {worst['value']}{worst['unit']}"
            wm, wv = worst["metric"], worst["value"]
        else:
            level, summary, wm, wv = "nominal", "All readings nominal", None, None
        zones.append({
            "station_id": st["id"], "city": st["city"], "zone": st["zone"],
            "lat": st["lat"], "lng": st["lng"], "level": level,
            "worst_metric": wm, "worst_value": wv,
            "alert_count": len(st_alerts), "summary": summary,
        })
    # earthquakes get their own pins
    for a in alerts:
        if a["source"] == "usgs":
            zones.append({
                "station_id": a["id"], "city": a["city"], "zone": "Seismic",
                "lat": a["lat"], "lng": a["lng"],
                "level": {"CRITICAL": "critical", "HIGH": "high",
                          "MEDIUM": "medium", "LOW": "nominal"}[a["severity"]],
                "worst_metric": "Magnitude", "worst_value": a["value"],
                "alert_count": 1, "summary": a["title"],
            })
    return {"generated_at": gen, "center": {"lat": 22.0, "lng": 79.0}, "zones": zones}


def analytics_summary(window_hours: int = 24) -> dict[str, Any]:
    alerts, gen = _alerts_snapshot()
    alerts = [a for a in alerts if a["status"] != "resolved"]
    total = len(alerts)
    sev_rank = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    by_sev = [{"level": s, "count": sum(1 for a in alerts if a["severity"] == s)} for s in sev_rank]
    cat_counts: dict[str, int] = {}
    city_counts: dict[str, int] = {}
    for a in alerts:
        cat_counts[a["category"]] = cat_counts.get(a["category"], 0) + 1
        city_counts[a["city"]] = city_counts.get(a["city"], 0) + 1
    by_cat = sorted(({"category": k, "count": v} for k, v in cat_counts.items()),
                    key=lambda x: -x["count"])
    by_city = sorted(({"city": k, "count": v} for k, v in city_counts.items()),
                     key=lambda x: -x["count"])[:10]
    crit = sum(1 for a in alerts if a["severity"] == "CRITICAL")
    high = sum(1 for a in alerts if a["severity"] == "HIGH")
    acked = sum(1 for a in alerts if a["acked"])
    pop = sum((a.get("impact") or {}).get("population_at_risk_est", 0) for a in alerts)
    # crude 12-bucket timeline by category share (live snapshot has one ts)
    timeline = [{"bucket": c["category"], "count": c["count"]} for c in by_cat]
    return {
        "generated_at": gen,
        "window_hours": window_hours,
        "kpis": {
            "active_alerts": total,
            "critical": crit,
            "high": high,
            "acknowledged": acked,
            "open_work_orders": sum(1 for w in _WORK_ORDERS.values() if w["status"] != "resolved"),
            "population_at_risk_est": pop,
            "stations_monitored": len(sources.METRO_STATIONS),
        },
        "by_category": by_cat,
        "by_severity": by_sev,
        "by_city": by_city,
        "timeline": timeline,
        "top_zones": [
            {"city": c["city"], "count": c["count"]} for c in by_city[:6]
        ],
    }


# ----------------------------------------------------------------------
# Write APIs (ack / work order / notify)
# ----------------------------------------------------------------------
def ack_alert(alert_id: str, actor: str = "rsd") -> dict[str, Any]:
    a = get_alert(alert_id)
    if not a:
        raise ValueError(f"Alert {alert_id} not found")
    _ACK_STATE[alert_id] = {"acked": True, "status": "acked",
                            "actor": actor, "at": datetime.now(timezone.utc).isoformat()}
    a["acked"] = True
    a["status"] = "acked"
    _audit("acknowledged", alert_id, actor, {"category": a["category"], "severity": a["severity"]})
    return {"alert_id": alert_id, "acked": True, "status": "acked"}


def resolve_alert(alert_id: str, actor: str = "rsd", note: Optional[str] = None) -> dict[str, Any]:
    """
    Close an alert out. Resolved alerts leave the active board — they drop
    out of the alert list, the severity counts, the map zone colouring and
    the analytics rollups. State is keyed by the stable fingerprint so the
    resolution survives the 120 s recompute (until the live reading itself
    clears, at which point the anomaly stops being generated anyway).
    """
    a = get_alert(alert_id)
    if not a:
        raise ValueError(f"Alert {alert_id} not found")
    _ACK_STATE[alert_id] = {"acked": True, "status": "resolved",
                            "actor": actor, "note": note,
                            "at": datetime.now(timezone.utc).isoformat()}
    a["acked"] = True
    a["status"] = "resolved"
    _audit("resolved", alert_id, actor,
           {"category": a["category"], "severity": a["severity"], "note": note})
    return {"alert_id": alert_id, "acked": True, "status": "resolved"}


def create_work_order(alert_id: str, actor: str = "rsd") -> dict[str, Any]:
    a = get_alert(alert_id)
    if not a:
        raise ValueError(f"Alert {alert_id} not found")
    _WO_SEQ["n"] += 1
    wo_id = f"WO-{_WO_SEQ['n']}"
    impact = a.get("impact") or {}
    sla_hours = {"CRITICAL": 4, "HIGH": 12, "MEDIUM": 48, "LOW": 120}.get(a["severity"], 48)
    order = {
        "id": wo_id,
        "alert_id": alert_id,
        "title": (impact.get("immediate_actions") or [a["title"]])[0],
        "category": a["category"],
        "severity": a["severity"],
        "city": a["city"],
        "department": impact.get("owning_department", "City Ops"),
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sla_due": (datetime.now(timezone.utc) + timedelta(hours=sla_hours)).isoformat(),
    }
    _WORK_ORDERS[wo_id] = order
    _ACK_STATE[alert_id] = {"acked": True, "status": "work_order",
                            "actor": actor, "at": order["created_at"]}
    _audit("work_order_created", alert_id, actor, {"work_order": wo_id})
    return order


def list_work_orders() -> dict[str, Any]:
    orders = sorted(_WORK_ORDERS.values(), key=lambda w: w["created_at"], reverse=True)
    return {"total": len(orders), "orders": orders}


def notify_alert(alert_id: str, actor: str = "rsd") -> dict[str, Any]:
    from app.modules.anomaly_monitoring import telegram as tg
    a = get_alert(alert_id)
    if not a:
        raise ValueError(f"Alert {alert_id} not found")
    msg_id: Optional[str] = None
    err: Optional[str] = None
    try:
        m = tg.send_alert(a)
        if m:
            msg_id = str(m.get("message_id") or "")
    except Exception as e:
        err = str(e)
        log.warning("anomaly notify failed for %s: %s", alert_id, e)
    _audit("telegram_sent" if not err else "telegram_failed", alert_id, actor,
           {"message_id": msg_id, "error": err})
    return {"alert_id": alert_id, "notified": msg_id is not None,
            "telegram_message_id": msg_id, "error": err}


def force_refresh() -> dict[str, Any]:
    _refresh_once()
    alerts, gen = _alerts_snapshot()
    active = [a for a in alerts if a["status"] != "resolved"]
    return {
        "refreshed": True,
        "alerts": len(active),                 # active board count (matches UI)
        "total_tracked": len(alerts),          # incl. resolved still pinned
        "generated_at": gen,
    }
