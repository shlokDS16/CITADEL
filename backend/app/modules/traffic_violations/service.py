"""
Traffic Violations — data layer.

All Supabase queries go through `get_supabase()` (service-role) per project
convention (see app/database.py). Authorization is enforced in the HTTP layer.

The aggregation helpers (`top_offenders`, `challan_kpis`, `analytics_summary`)
do small in-Python rollups while volumes are tiny. Phase 6 will swap them for
materialized views once detection rates are non-trivial.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.database import get_supabase

log = logging.getLogger("citadel.traffic_violations.service")


# ============================================================
# Constants — shared with the frontend's rendering
# ============================================================

VIOLATION_LABEL = {
    "no_helmet": "NO HELMET",
    "speeding": "SPEEDING",
    "wrong_lane": "WRONG LANE",
    "red_light": "RED LIGHT",
    "no_seatbelt": "NO SEATBELT",
    "illegal_parking": "ILLEGAL PARK",
    # Groq-Vision-only labels (Phase 3++++)
    "accident": "ACCIDENT",
    "rash_driving": "RASH DRIVING",
    "lane_violation": "LANE VIOLATION",
    "overload": "OVERLOAD",
    "overturned": "OVERTURNED VEHICLE",
    "debris": "ROAD DEBRIS",
}


# ============================================================
# Cameras
# ============================================================

def list_cameras(gateway: Optional[str] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("tv_cameras").select("*").order("id")
    if gateway:
        q = q.eq("gateway", gateway)
    if status:
        q = q.eq("status", status)
    return q.execute().data or []


def delete_camera(cam_id: str, actor: str = "rsd") -> Optional[dict[str, Any]]:
    """Remove a camera from the fleet.

    `tv_incidents.cam_id` REFERENCES tv_cameras(id) with no ON DELETE clause
    (Postgres default = RESTRICT), so a raw delete is blocked once a camera
    has incidents. We first unlink those incidents (cam_id -> NULL — the
    ON DELETE SET NULL the FK should have declared), which preserves every
    incident's evidence/plate/violation while letting the camera row go.
    Audited to tv_audit_log. Returns None if the camera doesn't exist.

    No background job re-seeds tv_cameras, so a delete is permanent (the
    snapshot loop reads the table live and simply stops polling the cam).
    """
    sb = get_supabase()
    existing = (
        sb.table("tv_cameras").select("*").eq("id", cam_id).limit(1).execute()
    ).data or []
    if not existing:
        return None
    cam = existing[0]

    unlinked = 0
    try:
        res = (
            sb.table("tv_incidents").update({"cam_id": None})
            .eq("cam_id", cam_id).execute()
        )
        unlinked = len(res.data or [])
    except Exception as e:  # noqa: BLE001
        log.warning("Unlinking incidents for camera %s failed: %s", cam_id, e)

    sb.table("tv_cameras").delete().eq("id", cam_id).execute()

    try:
        sb.table("tv_audit_log").insert({
            "entity_type": "camera", "entity_id": cam_id,
            "action": "camera_deleted", "actor": actor,
            "payload": {"name": cam.get("name"), "gateway": cam.get("gateway"),
                        "unlinked_incidents": unlinked},
        }).execute()
    except Exception:  # noqa: BLE001
        pass

    log.info("Camera deleted: %s (%s) by %s — unlinked %d incident(s)",
             cam_id, cam.get("name"), actor, unlinked)
    return {"deleted": cam_id, "name": cam.get("name"),
            "unlinked_incidents": unlinked}


def delete_incidents(inc_ids: list[str], actor: str = "rsd") -> dict[str, Any]:
    """Permanently delete incidents and their evidence footage.

    For each inc_id (the human INC-xxxx): removes the tv_incidents row and
    every local evidence artifact under CLIPS_DIR ({inc}.jpg / {inc}.raw.jpg
    / {inc}.mp4). Any linked challan is preserved: the
    tv_challans.incident_id FK is ON DELETE SET NULL, so the financial
    record survives with its incident link cleared (a challan is a legal
    record, footage is not). Best-effort removes the Supabase Storage clip
    if the row carried a storage path. Each deletion is audited.

    Returns {deleted: [...], not_found: [...], count, challans_unlinked}.
    """
    sb = get_supabase()
    deleted: list[str] = []
    not_found: list[str] = []
    challans_unlinked = 0

    for raw_id in inc_ids or []:
        safe = "".join(c for c in str(raw_id) if c.isalnum() or c == "-")
        if not safe:
            continue
        rows = (
            sb.table("tv_incidents").select("id, inc_id, video_clip_path")
            .eq("inc_id", safe).limit(1).execute()
        ).data or []
        if not rows:
            not_found.append(raw_id)
            continue
        pk = rows[0]["id"]

        # count challans that will be unlinked (for the audit/report)
        try:
            ch = (sb.table("tv_challans").select("id", count="exact")
                  .eq("incident_id", pk).limit(1).execute())
            challans_unlinked += ch.count or 0
        except Exception:  # noqa: BLE001
            pass

        # DB row (challan FK is SET NULL, so no cascade block)
        sb.table("tv_incidents").delete().eq("id", pk).execute()

        # local evidence artifacts
        for suffix in (".jpg", ".raw.jpg", ".mp4"):
            f = CLIPS_DIR / f"{safe}{suffix}"
            try:
                if f.exists():
                    f.unlink()
            except Exception as e:  # noqa: BLE001
                log.debug("evidence unlink %s failed: %s", f, e)

        # best-effort Supabase Storage clip removal
        path = rows[0].get("video_clip_path")
        if path and not str(path).startswith("http"):
            try:
                sb.storage.from_("incidents").remove([path])
            except Exception:  # noqa: BLE001
                pass

        try:
            sb.table("tv_audit_log").insert({
                "entity_type": "incident", "entity_id": safe,
                "action": "incident_deleted", "actor": actor,
                "payload": {"via": "incidents_ui"},
            }).execute()
        except Exception:  # noqa: BLE001
            pass
        deleted.append(safe)

    log.info("Deleted %d incident(s) by %s (%d not found, %d challans unlinked)",
             len(deleted), actor, len(not_found), challans_unlinked)
    return {"deleted": deleted, "not_found": not_found,
            "count": len(deleted), "challans_unlinked": challans_unlinked}


# ============================================================
# Header stats (camera_count + detections_today)
# ============================================================

def header_stats() -> dict[str, Any]:
    sb = get_supabase()
    cams = sb.table("tv_cameras").select("id", count="exact").execute()
    camera_count = cams.count or len(cams.data or [])

    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    detections = (
        sb.table("tv_incidents")
        .select("id", count="exact")
        .gte("detected_at", start_of_day.isoformat())
        .execute()
    )
    return {
        "camera_count": camera_count,
        "detections_today": detections.count or 0,
        "pipeline": "YOLOv8 + DEEPSORT + CRNN OCR",
    }


# ============================================================
# Incidents
# ============================================================

def _incident_status_to_ui(status: Optional[str]) -> str:
    """tv_incidents.status (PENDING_REVIEW / APPROVED / REJECTED) -> UI (pending / approved / rejected)."""
    s = (status or "").upper()
    return {
        "PENDING_REVIEW": "pending",
        "APPROVED": "approved",
        "REJECTED": "rejected",
    }.get(s, "pending")


def _shape_incident(row: dict) -> dict[str, Any]:
    detected_at = row.get("detected_at") or ""
    time_str = detected_at[11:19] if len(detected_at) >= 19 else ""
    conf_raw = row.get("detection_confidence") or 0
    # accept both 0..1 and 0..100 storage
    conf_pct = int(round(conf_raw * 100)) if conf_raw <= 1 else int(conf_raw)
    meta = row.get("frame_metadata") or {}
    return {
        "id": row.get("inc_id"),
        "type": VIOLATION_LABEL.get(row.get("violation_type", ""), (row.get("violation_type") or "").upper()),
        "plate": row.get("plate") or "—",
        "cam": row.get("cam_id") or "—",
        "time": time_str,
        "conf": conf_pct,
        "severity": (row.get("severity") or "medium").upper(),
        "status": _incident_status_to_ui(row.get("status")),
        "description": (meta.get("description") or "") if isinstance(meta, dict) else "",
        "scene":       (meta.get("groq_scene") or "") if isinstance(meta, dict) else "",
        "detected_at": detected_at,
    }


def list_incidents(
    type_: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("tv_incidents").select("*").order("detected_at", desc=True).limit(limit)
    if type_:
        q = q.eq("violation_type", type_.lower().replace(" ", "_"))
    if severity:
        q = q.eq("severity", severity.lower())
    if status:
        db_status = {
            "pending": "PENDING_REVIEW",
            "approved": "APPROVED",
            "rejected": "REJECTED",
        }.get(status.lower(), status.upper())
        q = q.eq("status", db_status)
    rows = q.execute().data or []
    return [_shape_incident(r) for r in rows]


# ============================================================
# Challans
# ============================================================

def _shape_challan(c: dict) -> dict[str, Any]:
    issued = (c.get("issued_at") or "")[:10]
    due = (c.get("due_by") or "")[:10]
    return {
        "id": c.get("challan_id"),
        "plate": c.get("plate"),
        "driver": c.get("driver_name") or "—",
        "type": VIOLATION_LABEL.get(c.get("violation_type", ""), (c.get("violation_type") or "").upper()),
        "amt": c.get("amount") or 0,
        "issued": issued,
        "due": due,
        "status": c.get("status"),
    }


def list_challans(status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
    sb = get_supabase()
    q = sb.table("tv_challans").select("*").order("issued_at", desc=True).limit(limit)
    if status:
        q = q.eq("status", status.upper())
    rows = q.execute().data or []
    return [_shape_challan(c) for c in rows]


def challan_kpis() -> dict[str, Any]:
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rows = (
        sb.table("tv_challans")
        .select("amount, status")
        .gte("issued_at", cutoff)
        .execute()
    ).data or []
    issued_30d = len(rows)
    paid = [r for r in rows if (r.get("status") or "").upper() == "PAID"]
    disputed = [r for r in rows if (r.get("status") or "").upper() == "DISPUTED"]
    total_collected = sum(r.get("amount") or 0 for r in paid)
    return {
        "issued_30d": issued_30d,
        "total_collected": total_collected,
        "collection_rate": round(len(paid) / issued_30d * 100, 1) if issued_30d else 0.0,
        "disputed_pct": round(len(disputed) / issued_30d * 100, 1) if issued_30d else 0.0,
    }


# ============================================================
# Repeat offenders (aggregation)
# ============================================================

def _humanize_since(iso_ts: str) -> str:
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        days = delta.days
        if days < 1:
            return "today"
        if days == 1:
            return "1 day"
        if days < 7:
            return f"{days} days"
        weeks = days // 7
        return f"{weeks} week" if weeks == 1 else f"{weeks} weeks"
    except Exception:
        return "—"


def top_offenders(days: int = 90, limit: int = 5) -> list[dict[str, Any]]:
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    incidents = (
        sb.table("tv_incidents")
        .select("plate, detected_at, status")
        .gte("detected_at", cutoff)
        .execute()
    ).data or []
    challans = (
        sb.table("tv_challans")
        .select("plate, amount, status, issued_at")
        .gte("issued_at", cutoff)
        .execute()
    ).data or []
    drivers = {
        d["plate"]: d.get("driver_name")
        for d in (sb.table("tv_drivers").select("plate, driver_name").execute().data or [])
    }

    agg: dict[str, dict[str, Any]] = {}
    for i in incidents:
        p = i.get("plate") or "—"
        a = agg.setdefault(p, {"plate": p, "offenses": 0, "pending": 0, "last_at": ""})
        a["offenses"] += 1
        if (i.get("detected_at") or "") > (a["last_at"] or ""):
            a["last_at"] = i.get("detected_at") or ""
    for c in challans:
        if (c.get("status") or "").upper() != "PAID":
            p = c.get("plate") or "—"
            a = agg.setdefault(p, {"plate": p, "offenses": 0, "pending": 0, "last_at": ""})
            a["pending"] += c.get("amount") or 0

    ranked = sorted(agg.values(), key=lambda x: x["offenses"], reverse=True)[:limit]
    out = []
    for rank, r in enumerate(ranked, start=1):
        offenses = r["offenses"]
        risk = "HIGH" if offenses >= 10 else "MEDIUM" if offenses >= 5 else "LOW"
        out.append({
            "rank": rank,
            "plate": r["plate"],
            "driver": drivers.get(r["plate"]) or "—",
            "offenses": offenses,
            "total": r["pending"],
            "last": _humanize_since(r["last_at"]),
            "risk": risk,
        })
    return out


# ============================================================
# Phase 5 — Per-plate timeline & Notify
# ============================================================

_SEV_COLOR = {
    "CRITICAL": "red",
    "HIGH":     "red",
    "MEDIUM":   "gold",
    "LOW":      "cyan",
}

_CHALLAN_STATUS_COLOR = {
    "PAID":     "green",
    "DISPUTED": "gold",
    "UNPAID":   "red",
}


def offender_timeline(plate: str) -> dict[str, Any]:
    """
    Build a unified, chronological event stream for a plate:
      - every incident detection
      - every challan (issued, mark-paid, mark-disputed, telegram_sent, etc.)
      - every audit-log entry tied to those incidents/challans
    """
    sb = get_supabase()

    challans = (
        sb.table("tv_challans")
        .select("*")
        .eq("plate", plate)
        .order("issued_at", desc=False)
        .execute()
    ).data or []
    incidents_by_plate = (
        sb.table("tv_incidents")
        .select("*")
        .eq("plate", plate)
        .order("detected_at", desc=False)
        .execute()
    ).data or []
    incident_pks_via_challan = [c.get("incident_id") for c in challans if c.get("incident_id")]
    incidents_by_challan: list[dict[str, Any]] = []
    if incident_pks_via_challan:
        try:
            incidents_by_challan = (
                sb.table("tv_incidents")
                .select("*")
                .in_("id", incident_pks_via_challan)
                .execute()
            ).data or []
        except Exception:
            incidents_by_challan = []
    seen = set()
    incidents: list[dict[str, Any]] = []
    for row in incidents_by_plate + incidents_by_challan:
        pk = row.get("id")
        if pk in seen:
            continue
        seen.add(pk)
        incidents.append(row)
    incidents.sort(key=lambda r: r.get("detected_at") or "")

    inc_ids = [i.get("inc_id") for i in incidents if i.get("inc_id")]
    ch_ids = [c.get("challan_id") for c in challans if c.get("challan_id")]
    audit: list[dict[str, Any]] = []
    if inc_ids or ch_ids:
        try:
            ent_ids = inc_ids + ch_ids
            # tv_audit_log's timestamp column is `ts`, not `created_at`.
            # Alias it so downstream event shaping keeps its `created_at` key.
            audit = (
                sb.table("tv_audit_log")
                .select("*, created_at:ts")
                .in_("entity_id", ent_ids)
                .order("ts", desc=False)
                .execute()
            ).data or []
        except Exception:
            log.exception("offender_timeline: tv_audit_log lookup failed")
            audit = []

    driver_row = _driver_for(plate)
    driver_name = driver_row.get("driver_name")
    chat_id = driver_row.get("telegram_chat_id")

    events: list[dict[str, Any]] = []
    for i in incidents:
        sev = (i.get("severity") or "MEDIUM").upper()
        events.append({
            "kind": "incident",
            "at": i.get("detected_at") or "",
            "label": f"Detected: {VIOLATION_LABEL.get(i.get('violation_type') or '', (i.get('violation_type') or 'VIOLATION').upper())}",
            "badge": sev,
            "badge_color": _SEV_COLOR.get(sev, "gold"),
            "detail": f"Cam {i.get('cam_id') or '—'} · conf {int(round((i.get('detection_confidence') or 0) * (100 if (i.get('detection_confidence') or 0) <= 1 else 1)))}%",
            "ref_id": i.get("inc_id"),
        })

    total_out = 0
    total_paid = 0
    for c in challans:
        status = (c.get("status") or "UNPAID").upper()
        amt = c.get("amount") or 0
        if status == "PAID":
            total_paid += amt
        else:
            total_out += amt
        events.append({
            "kind": "challan",
            "at": c.get("issued_at") or "",
            "label": f"Challan issued: {c.get('offense') or '—'}",
            "badge": status,
            "badge_color": _CHALLAN_STATUS_COLOR.get(status, "gold"),
            "detail": f"{c.get('challan_id')} · ₹{amt:,} · due {c.get('due_by','')[:10]}",
            "ref_id": c.get("challan_id"),
        })

    for a in audit:
        action = (a.get("action") or "").lower()
        if action in ("approved", "challan_issued"):
            continue
        label_map = {
            "telegram_sent":   "Telegram delivered to driver",
            "telegram_failed": "Telegram delivery failed",
            "marked_paid":     "Challan marked PAID",
            "marked_disputed": "Challan marked DISPUTED",
            "marked_unpaid":   "Challan reset to UNPAID",
            "rejected":        "Incident rejected",
            "telegram_callback": "Driver responded via Telegram",
            "offender_notified": "Offender Telegram nag sent",
        }
        label = label_map.get(action, action.replace("_", " ").title() or "Audit event")
        events.append({
            "kind": "audit",
            "at": a.get("created_at") or "",
            "label": label,
            "badge": None,
            "badge_color": None,
            "detail": (a.get("actor") or "system"),
            "ref_id": a.get("entity_id"),
        })

    events.sort(key=lambda e: e.get("at") or "", reverse=True)

    return {
        "plate": plate,
        "driver": driver_name,
        "chat_id": chat_id,
        "incident_count": len(incidents),
        "challan_count": len(challans),
        "total_outstanding": total_out,
        "total_paid": total_paid,
        "events": events,
    }


def notify_offender(plate: str, actor: str = "rsd") -> dict[str, Any]:
    """
    Send a Telegram nag for a repeat-offender plate.
    Uses the driver's chat_id when known, falls back to TELEGRAM_DEFAULT_CHAT_ID
    (for hackathon-demo wiring).
    """
    from app.modules.traffic_violations import telegram as tg

    sb = get_supabase()
    challans = (
        sb.table("tv_challans").select("amount, status, incident_id").eq("plate", plate).execute()
    ).data or []
    inc_pks_via_ch = [c.get("incident_id") for c in challans if c.get("incident_id")]
    incident_ids: set[Any] = set()
    incidents_direct = (
        sb.table("tv_incidents").select("id").eq("plate", plate).execute()
    ).data or []
    for r in incidents_direct:
        if r.get("id"):
            incident_ids.add(r["id"])
    incident_ids.update(pid for pid in inc_pks_via_ch if pid)
    offense_count = len(incident_ids)
    total_out = sum(
        c.get("amount") or 0 for c in challans if (c.get("status") or "").upper() != "PAID"
    )

    driver = _driver_for(plate)
    chat_id = driver.get("telegram_chat_id")
    driver_name = driver.get("driver_name")

    msg_id: Optional[str] = None
    err: Optional[str] = None
    try:
        msg = tg.send_offender_nag(
            chat_id=chat_id,
            plate=plate,
            driver_name=driver_name,
            offense_count=offense_count,
            total_pending=total_out,
        )
        if msg:
            msg_id = str(msg.get("message_id") or "")
    except Exception as e:
        err = str(e)
        log.warning("Offender notify failed for %s: %s", plate, e)

    try:
        sb.table("tv_audit_log").insert({
            "entity_type": "plate",
            "entity_id": plate,
            "action": "offender_notified" if not err else "offender_notify_failed",
            "actor": actor,
            "payload": {
                "offense_count": offense_count,
                "total_outstanding": total_out,
                "message_id": msg_id,
                "error": err,
            },
        }).execute()
    except Exception:
        pass

    return {
        "plate": plate,
        "notified": msg_id is not None,
        "telegram_message_id": msg_id,
        "error": err,
        "offense_count": offense_count,
        "total_outstanding": total_out,
    }


# ============================================================
# Analytics summary (KPIs)
# ============================================================

def analytics_summary() -> dict[str, Any]:
    sb = get_supabase()
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = (
        sb.table("tv_incidents")
        .select("detection_confidence, status")
        .gte("detected_at", since_24h)
        .execute()
    ).data or []

    detections_24h = len(recent)
    if detections_24h:
        confs = [r.get("detection_confidence") or 0 for r in recent]
        scale = 100 if max(confs) <= 1 else 1
        avg_conf = round(sum(confs) / len(confs) * scale, 1)
        rejected = sum(1 for r in recent if (r.get("status") or "") == "REJECTED")
        fp_rate = round(rejected / detections_24h * 100, 1)
    else:
        avg_conf = 0.0
        fp_rate = 0.0

    cams = sb.table("tv_cameras").select("status").execute().data or []
    active = sum(1 for c in cams if (c.get("status") or "") == "active")
    uptime = round(active / len(cams) * 100, 1) if cams else 0.0

    return {
        "detections_24h": detections_24h,
        "avg_confidence": avg_conf,
        "false_positive_pct": fp_rate,
        "cam_uptime_pct": uptime,
    }


# ============================================================
# Phase 6 — Comprehensive analytics rollup
# Used by the redesigned Analytics tab. One trip to Supabase, fan out
# in-Python to KPIs / heatmap / breakdown / hotspots / trend / funnel /
# revenue / recent activity. Optional `days` window (1..365).
# ============================================================

def _bucket_iso(iso: str) -> tuple[int, int, str]:
    """ISO string -> (weekday 0=Mon, hour 0-23, YYYY-MM-DD)."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) if isinstance(iso, str) else None
    except Exception:
        return -1, -1, ""
    if not dt:
        return -1, -1, ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.weekday(), dt.hour, dt.date().isoformat()


def analytics_full(days: int = 30) -> dict[str, Any]:
    """
    Single-shot snapshot powering the Analytics tab.
    All rollups are in-Python — volumes are small enough today that doing
    this in SQL would be premature optimisation. When volumes grow, swap
    each section to a materialised view (cron-refreshed) without touching
    the API contract.
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=int(days))).isoformat()
    since_24h = (now - timedelta(hours=24)).isoformat()
    since_7d = (now - timedelta(days=7)).isoformat()

    # ---- pull base data ----
    incidents = (
        sb.table("tv_incidents")
        .select("inc_id, cam_id, violation_type, severity, status, plate, "
                "detection_confidence, detected_at, frame_metadata")
        .gte("detected_at", since)
        .order("detected_at", desc=True)
        .execute()
    ).data or []
    challans = (
        sb.table("tv_challans")
        .select("challan_id, plate, violation_type, amount, status, "
                "issued_at, paid_at, due_by")
        .gte("issued_at", since)
        .order("issued_at", desc=True)
        .execute()
    ).data or []
    cameras = sb.table("tv_cameras").select("id, name, status, lat, lng").execute().data or []
    cam_name_map = {c["id"]: c.get("name") for c in cameras}

    # ---- KPI tiles ----
    total = len(incidents)
    inc_24h = [r for r in incidents if (r.get("detected_at") or "") >= since_24h]
    inc_7d = [r for r in incidents if (r.get("detected_at") or "") >= since_7d]
    detections_24h = len(inc_24h)

    confs = [r.get("detection_confidence") or 0 for r in incidents]
    if confs:
        scale = 100 if max(confs) <= 1 else 1
        avg_conf = round(sum(confs) / len(confs) * scale, 1)
    else:
        avg_conf = 0.0

    rejected = sum(1 for r in incidents if (r.get("status") or "").upper() == "REJECTED")
    fp_pct = round(rejected / total * 100, 1) if total else 0.0

    active_cams = sum(1 for c in cameras if (c.get("status") or "") == "active")
    cam_uptime_pct = round(active_cams / len(cameras) * 100, 1) if cameras else 0.0

    total_revenue = sum(c.get("amount") or 0 for c in challans if (c.get("status") or "").upper() == "PAID")
    outstanding = sum(c.get("amount") or 0 for c in challans if (c.get("status") or "").upper() == "UNPAID")
    disputed_amt = sum(c.get("amount") or 0 for c in challans if (c.get("status") or "").upper() == "DISPUTED")
    issued_30d = len(challans)
    paid_count = sum(1 for c in challans if (c.get("status") or "").upper() == "PAID")
    collection_rate = round(paid_count / issued_30d * 100, 1) if issued_30d else 0.0

    kpis = {
        "detections_window":   total,
        "detections_24h":      detections_24h,
        "detections_7d":       len(inc_7d),
        "avg_confidence":      avg_conf,
        "false_positive_pct":  fp_pct,
        "cam_uptime_pct":      cam_uptime_pct,
        "total_revenue":       total_revenue,
        "total_outstanding":   outstanding,
        "total_disputed":      disputed_amt,
        "challans_issued":     issued_30d,
        "collection_rate":     collection_rate,
        "window_days":         days,
    }

    # ---- Heatmap: 7 (Mon..Sun) x 24 hours ----
    heatmap = [[0] * 24 for _ in range(7)]
    for r in incidents:
        dow, hr, _ = _bucket_iso(r.get("detected_at") or "")
        if 0 <= dow < 7 and 0 <= hr < 24:
            heatmap[dow][hr] += 1

    # ---- Donut: violation-type breakdown ----
    type_counts: dict[str, int] = {}
    for r in incidents:
        t = (r.get("violation_type") or "unknown").lower()
        type_counts[t] = type_counts.get(t, 0) + 1
    donut = sorted(
        [{
            "type":  t,
            "label": VIOLATION_LABEL.get(t, t.replace("_", " ").upper()),
            "count": n,
            "pct":   round(n / total * 100, 1) if total else 0,
        } for t, n in type_counts.items()],
        key=lambda x: -x["count"],
    )

    # ---- Severity breakdown ----
    sev_counts: dict[str, int] = {}
    for r in incidents:
        sev = (r.get("severity") or "MEDIUM").upper()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
    severity = [
        {"level": s, "count": sev_counts.get(s, 0)}
        for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    ]

    # ---- Hotspot cameras (top 10 by incident count) ----
    cam_counts: dict[str, int] = {}
    for r in incidents:
        cid = r.get("cam_id") or "—"
        cam_counts[cid] = cam_counts.get(cid, 0) + 1
    hotspots = sorted(
        [{
            "cam_id": cid,
            "name":   cam_name_map.get(cid) or cid,
            "count":  n,
        } for cid, n in cam_counts.items()],
        key=lambda x: -x["count"],
    )[:10]

    # ---- Time series (per-day incidents + per-day revenue, last `days`) ----
    by_day: dict[str, dict[str, Any]] = {}
    for i in range(int(days)):
        d = (now - timedelta(days=int(days) - 1 - i)).date().isoformat()
        by_day[d] = {"date": d, "incidents": 0, "approved": 0, "rejected": 0,
                     "issued": 0, "collected": 0}
    for r in incidents:
        _, _, d = _bucket_iso(r.get("detected_at") or "")
        if d in by_day:
            by_day[d]["incidents"] += 1
            status = (r.get("status") or "").upper()
            if status == "APPROVED": by_day[d]["approved"] += 1
            elif status == "REJECTED": by_day[d]["rejected"] += 1
    for c in challans:
        _, _, d = _bucket_iso(c.get("issued_at") or "")
        if d in by_day:
            by_day[d]["issued"] += 1
        _, _, d_paid = _bucket_iso(c.get("paid_at") or "")
        if d_paid in by_day and (c.get("status") or "").upper() == "PAID":
            by_day[d_paid]["collected"] += c.get("amount") or 0
    trend = list(by_day.values())

    # ---- Status funnel ----
    inc_pending = sum(1 for r in incidents if (r.get("status") or "").upper() == "PENDING_REVIEW")
    inc_approved = sum(1 for r in incidents if (r.get("status") or "").upper() == "APPROVED")
    inc_rejected = rejected
    ch_unpaid = sum(1 for c in challans if (c.get("status") or "").upper() == "UNPAID")
    ch_disputed = sum(1 for c in challans if (c.get("status") or "").upper() == "DISPUTED")
    ch_paid = paid_count
    funnel = [
        {"stage": "Detected",        "count": total,            "color": "cyan"},
        {"stage": "Pending Review",  "count": inc_pending,      "color": "gold"},
        {"stage": "Approved",        "count": inc_approved,     "color": "green"},
        {"stage": "Rejected",        "count": inc_rejected,     "color": "red"},
        {"stage": "Challans Issued", "count": issued_30d,       "color": "cyan"},
        {"stage": "Paid",            "count": ch_paid,          "color": "green"},
        {"stage": "Disputed",        "count": ch_disputed,      "color": "gold"},
        {"stage": "Unpaid",          "count": ch_unpaid,        "color": "red"},
    ]

    # ---- Repeat offenders (top 5) — cross-link to Offenders tab ----
    top_off = top_offenders(days=int(days), limit=5)

    # ---- Recent activity (last 12 audit entries) ----
    recent_audit: list[dict[str, Any]] = []
    try:
        recent_audit = (
            sb.table("tv_audit_log")
            .select("entity_type, entity_id, action, actor, created_at:ts")
            .order("ts", desc=True)
            .limit(12)
            .execute()
        ).data or []
    except Exception:
        log.exception("analytics: recent_audit lookup failed")
        recent_audit = []

    return {
        "generated_at": now.isoformat(),
        "window_days": int(days),
        "kpis": kpis,
        "heatmap": {
            "rows": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "cols": list(range(24)),
            "data": heatmap,
            "max": max((max(r) for r in heatmap), default=0),
        },
        "type_breakdown": donut,
        "severity_breakdown": severity,
        "hotspot_cameras": hotspots,
        "trend": trend,
        "funnel": funnel,
        "top_offenders": top_off,
        "recent_audit": recent_audit,
    }


def export_incidents_csv(days: int = 30) -> str:
    """Flat CSV — one row per incident with the columns an officer / auditor
    would want when handing data to a different system."""
    sb = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    incidents = (
        sb.table("tv_incidents")
        .select("inc_id, cam_id, violation_type, severity, plate, "
                "detection_confidence, detected_at, status, approved_at, "
                "rejected_at, approved_by, rejected_by, video_clip_path")
        .gte("detected_at", since)
        .order("detected_at", desc=True)
        .execute()
    ).data or []
    # join challan info per incident_id
    inc_ids = [r.get("inc_id") for r in incidents if r.get("inc_id")]
    chmap: dict[str, dict[str, Any]] = {}
    if incidents:
        ch_rows = (
            sb.table("tv_challans")
            .select("incident_id, challan_id, amount, status, issued_at, "
                    "paid_at, due_by, telegram_message_id")
            .execute()
        ).data or []
        # Tie challan.incident_id (FK to tv_incidents.id) back via lookup — we
        # have inc_id (human) not pk. Re-fetch the pk mapping cheaply.
        pks = (
            sb.table("tv_incidents")
            .select("id, inc_id")
            .in_("inc_id", inc_ids)
            .execute()
        ).data or []
        pk_to_inc = {r["id"]: r["inc_id"] for r in pks}
        for c in ch_rows:
            inc_human = pk_to_inc.get(c.get("incident_id"))
            if inc_human and inc_human not in chmap:
                chmap[inc_human] = c

    import csv as _csv
    import io
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow([
        "inc_id", "cam_id", "violation_type", "severity", "plate",
        "confidence_pct", "detected_at", "status",
        "approved_by", "approved_at", "rejected_by", "rejected_at",
        "challan_id", "challan_amount", "challan_status",
        "challan_issued_at", "challan_paid_at", "challan_due_by",
        "telegram_message_id", "evidence_clip_path",
    ])
    for r in incidents:
        c = chmap.get(r.get("inc_id"), {})
        conf = r.get("detection_confidence") or 0
        conf_pct = int(round(conf * 100)) if conf <= 1 else int(conf)
        w.writerow([
            r.get("inc_id"), r.get("cam_id"), r.get("violation_type"),
            r.get("severity"), r.get("plate") or "",
            conf_pct, r.get("detected_at"), (r.get("status") or "").upper(),
            r.get("approved_by") or "", r.get("approved_at") or "",
            r.get("rejected_by") or "", r.get("rejected_at") or "",
            c.get("challan_id") or "", c.get("amount") or "",
            (c.get("status") or "").upper(),
            c.get("issued_at") or "", c.get("paid_at") or "",
            c.get("due_by") or "", c.get("telegram_message_id") or "",
            r.get("video_clip_path") or "",
        ])
    return buf.getvalue()


def export_analytics_html(days: int = 30) -> str:
    """
    Standalone, print-friendly HTML report for the current analytics
    window. Renders KPIs, tables, and stat blocks — designed to be saved
    as PDF via browser's Print -> Save as PDF, without requiring any
    headless-browser dependency on the server.
    """
    a = analytics_full(days=days)
    kpis = a["kpis"]
    rows_html = "".join(
        f"<tr><td>{t['label']}</td><td>{t['count']}</td><td>{t['pct']}%</td></tr>"
        for t in a["type_breakdown"]
    )
    hot_html = "".join(
        f"<tr><td>{h['cam_id']}</td><td>{h['name']}</td><td>{h['count']}</td></tr>"
        for h in a["hotspot_cameras"]
    )
    funnel_html = "".join(
        f"<tr><td>{f['stage']}</td><td>{f['count']}</td></tr>"
        for f in a["funnel"]
    )
    off_html = "".join(
        f"<tr><td>#{o['rank']}</td><td>{o['plate']}</td><td>{o['driver']}</td>"
        f"<td>{o['offenses']}</td><td>{o['risk']}</td>"
        f"<td>₹{(o.get('total') or 0):,}</td></tr>"
        for o in a["top_offenders"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>CITADEL Traffic Violations — Analytics Report ({days}-day)</title>
<style>
  body {{ font-family: -apple-system,Segoe UI,sans-serif; margin: 24px; color: #111; }}
  h1 {{ font-size: 24px; border-bottom: 4px solid #000; padding-bottom: 8px; }}
  h2 {{ font-size: 16px; margin: 28px 0 8px; letter-spacing: 2px; }}
  .meta {{ font-family: monospace; font-size: 11px; color: #666; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
  .kpi {{ border: 2px solid #000; padding: 12px; }}
  .kpi .label {{ font-size: 10px; letter-spacing: 1px; color: #666; }}
  .kpi .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin-top: 8px; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #f4f4f4; font-size: 11px; letter-spacing: 1px; }}
  @media print {{ body {{ margin: 0; }} .no-print {{ display: none; }} }}
</style>
</head><body>
  <h1>CITADEL Traffic Violations · Analytics Report</h1>
  <div class="meta">Window: last {days} days · Generated {a['generated_at']}</div>
  <h2>KEY METRICS</h2>
  <div class="kpi-grid">
    <div class="kpi"><div class="label">DETECTIONS (24H)</div><div class="value">{kpis['detections_24h']:,}</div></div>
    <div class="kpi"><div class="label">DETECTIONS (7D)</div><div class="value">{kpis['detections_7d']:,}</div></div>
    <div class="kpi"><div class="label">DETECTIONS ({days}D)</div><div class="value">{kpis['detections_window']:,}</div></div>
    <div class="kpi"><div class="label">AVG CONFIDENCE</div><div class="value">{kpis['avg_confidence']}%</div></div>
    <div class="kpi"><div class="label">FALSE POSITIVES</div><div class="value">{kpis['false_positive_pct']}%</div></div>
    <div class="kpi"><div class="label">CAM UPTIME</div><div class="value">{kpis['cam_uptime_pct']}%</div></div>
    <div class="kpi"><div class="label">REVENUE COLLECTED</div><div class="value">₹{kpis['total_revenue']:,}</div></div>
    <div class="kpi"><div class="label">OUTSTANDING</div><div class="value">₹{kpis['total_outstanding']:,}</div></div>
    <div class="kpi"><div class="label">CHALLANS ISSUED</div><div class="value">{kpis['challans_issued']:,}</div></div>
    <div class="kpi"><div class="label">COLLECTION RATE</div><div class="value">{kpis['collection_rate']}%</div></div>
  </div>
  <h2>VIOLATION BREAKDOWN</h2>
  <table><thead><tr><th>Type</th><th>Count</th><th>Share</th></tr></thead><tbody>{rows_html}</tbody></table>
  <h2>HOTSPOT CAMERAS</h2>
  <table><thead><tr><th>Cam</th><th>Name</th><th>Incidents</th></tr></thead><tbody>{hot_html}</tbody></table>
  <h2>STATUS FUNNEL</h2>
  <table><thead><tr><th>Stage</th><th>Count</th></tr></thead><tbody>{funnel_html}</tbody></table>
  <h2>TOP REPEAT OFFENDERS</h2>
  <table><thead><tr><th>Rank</th><th>Plate</th><th>Driver</th><th>Offenses</th><th>Risk</th><th>Pending</th></tr></thead><tbody>{off_html}</tbody></table>
  <p class="meta">CITADEL · Government Module 3 · Auto-generated. Use browser Print → Save as PDF for archival.</p>
</body></html>"""


# ============================================================
# Fines lookup
# ============================================================

def list_fines() -> list[dict[str, Any]]:
    sb = get_supabase()
    return (sb.table("govt_fines_penalties").select("*").order("violation_type").execute().data or [])


def update_fine(violation_type: str, fine_amount: int,
                legal_section: Optional[str] = None,
                description: Optional[str] = None,
                actor: str = "rsd") -> dict[str, Any]:
    """
    Change a traffic-violation fine. Because `_fine_amount_for()` (used by
    challan creation + Telegram) and the Citizen Assistant's live_facts
    both read this same govt_fines_penalties row at request time, the new
    amount is reflected EVERYWHERE on the next action — no restart, no
    rebuild. Upserts so a brand-new violation type can be priced too.
    """
    vt = (violation_type or "").strip().lower().replace(" ", "_")
    if not vt:
        raise ValueError("violation_type is required")
    if fine_amount is None or int(fine_amount) < 0:
        raise ValueError("fine_amount must be a non-negative integer")
    sb = get_supabase()
    existing = (
        sb.table("govt_fines_penalties").select("*")
        .eq("violation_type", vt).limit(1).execute()
    ).data or []
    row = {
        "violation_type": vt,
        "fine_amount": int(fine_amount),
    }
    if legal_section is not None:
        row["legal_section"] = legal_section
    if description is not None:
        row["description"] = description
    old_amount = existing[0].get("fine_amount") if existing else None
    if existing:
        sb.table("govt_fines_penalties").update(row).eq("violation_type", vt).execute()
    else:
        sb.table("govt_fines_penalties").insert(row).execute()
    try:
        sb.table("tv_audit_log").insert({
            "entity_type": "fine", "entity_id": vt, "action": "fine_updated",
            "actor": actor,
            "payload": {"old_amount": old_amount, "new_amount": int(fine_amount),
                        "legal_section": legal_section},
        }).execute()
    except Exception:
        pass
    log.info("Fine updated: %s %s -> %s by %s", vt, old_amount, fine_amount, actor)
    return {
        "violation_type": vt,
        "old_amount": old_amount,
        "fine_amount": int(fine_amount),
        "legal_section": legal_section,
        "reflected_in": ["challan creation", "Telegram challan messages",
                         "Citizen AI Assistant (live)"],
    }


# ============================================================
# Phase 1+ — Camera health summary (used by the strip at top of Live Feed)
# ============================================================

def camera_health() -> dict[str, Any]:
    """
    Roll-up across all cameras: online%, avg FPS, last detection timestamp.
    Drives the strip shown at the top of the Live Feed tab.
    """
    sb = get_supabase()
    cams = sb.table("tv_cameras").select("status, fps, last_seen").execute().data or []

    online = [c for c in cams if (c.get("status") or "") == "active"]
    offline = [c for c in cams if (c.get("status") or "") == "offline"]
    degraded = [c for c in cams if (c.get("status") or "") == "degraded"]

    fps_values = [c.get("fps") for c in online if c.get("fps")]
    avg_fps = round(sum(fps_values) / len(fps_values), 1) if fps_values else 0.0

    last_inc = (
        sb.table("tv_incidents")
        .select("detected_at, plate, cam_id, violation_type")
        .order("detected_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    last_detection = last_inc[0] if last_inc else None

    return {
        "total": len(cams),
        "online": len(online),
        "offline": len(offline),
        "degraded": len(degraded),
        "online_pct": round(len(online) / len(cams) * 100, 1) if cams else 0.0,
        "avg_fps": avg_fps,
        "last_detection": last_detection,
    }


# ============================================================
# Phase 1+ — System status (sidebar bar at top of module)
# Lightweight, env-config check only. NO outbound network calls so it
# doesn't slow page load. A separate /ping endpoint can do real RTT later.
# ============================================================

def system_status() -> dict[str, Any]:
    from app.config import settings  # local import — settings loaded at startup
    return {
        "supabase": {"ok": bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)},
        "groq":     {"ok": bool(settings.GROQ_API_KEY), "model": settings.GROQ_CLASSIFIER_MODEL},
        "ocr":      {"ok": bool(settings.OCR_SPACE_API_KEY)},
        "telegram": {"ok": bool(settings.TELEGRAM_BOT_TOKEN)},
        "env":      settings.APP_ENV,
    }


# ============================================================
# Phase 2+ — Live snapshots from Singapore data.gov.sg traffic-images API
# Public, no auth. 90 real traffic-camera JPGs across Singapore, refreshing
# every 60-90 s. We map each of our cameras to a Singapore camera_id and
# expose a single endpoint the frontend polls every 30 s.
# ============================================================

import httpx

_SG_API = "https://api.data.gov.sg/v1/transport/traffic-images"
_SG_CACHE: dict[str, Any] = {"ts": 0, "data": None}
_SG_CACHE_TTL = 30  # seconds


def _fetch_singapore_snapshots() -> list[dict[str, Any]]:
    """Fetch + cache for 30 s the Singapore traffic-images API."""
    now = time.time() if "time" in globals() else None
    import time as _t
    now = _t.time()
    if _SG_CACHE["data"] is not None and (now - _SG_CACHE["ts"]) < _SG_CACHE_TTL:
        return _SG_CACHE["data"]
    try:
        with httpx.Client(timeout=8.0) as c:
            r = c.get(_SG_API)
            r.raise_for_status()
            body = r.json()
        items = body.get("items") or []
        cams = items[0].get("cameras", []) if items else []
        _SG_CACHE["data"] = cams
        _SG_CACHE["ts"] = now
        return cams
    except Exception as e:
        log.warning("Singapore traffic-images fetch failed: %s", e)
        return _SG_CACHE["data"] or []


# ============================================================
# Phase 3+++ — Continuous-motion loop videos with pre-computed YOLO tracks
# Each tile plays a short traffic-clip on loop; backend serves the mp4
# + a JSON of per-frame bboxes; frontend syncs SVG overlay to video.currentTime.
# Files live under backend/.tv_camera_loops/{loop_id}.mp4 + .tracks.json
# ============================================================

LOOPS_DIR = Path(os.getenv("TV_CAMERA_LOOPS_DIR", ".tv_camera_loops")).resolve()

# Map our cameras to a loop_id + start offset (seconds).
# A single 9.6 s Vegas-traffic clip is rotated across all 24 cameras with
# staggered start offsets so adjacent tiles don't look identical.
_DEFAULT_LOOP_ID = "vegas-4251"
_DEFAULT_LOOP_DURATION = 9.6   # seconds — derived from the mp4 (287f / 30fps)


def loop_assignment_for(cam_id: str, index: int) -> dict[str, Any]:
    """
    Return loop info for a given camera, or None if loops disabled.

    Default behaviour: DISABLED — every tile renders its own distinct Singapore
    LTA camera JPG (90 cams available, we use 24). LTA refreshes each JPG every
    1–5 minutes; the frontend polls /snapshots every 30 s so the tiles tick
    over as new frames are captured. Each tile is a different real camera.

    Set TV_DEMO_LOOPS=1 to restore the old fallback (single shared Vegas mp4
    clip with staggered offsets — useful for offline demos only).
    """
    if os.getenv("TV_DEMO_LOOPS", "0") not in ("1", "true", "True"):
        return None
    if not (LOOPS_DIR / f"{_DEFAULT_LOOP_ID}.mp4").exists():
        return None
    # stagger offsets to give visual variety across the grid
    offset = round((index * 0.42) % _DEFAULT_LOOP_DURATION, 2)
    return {
        "loop_id":         _DEFAULT_LOOP_ID,
        "video_url":       f"/api/traffic-violations/loops/{_DEFAULT_LOOP_ID}/video.mp4",
        "tracks_url":      f"/api/traffic-violations/loops/{_DEFAULT_LOOP_ID}/tracks.json",
        "start_offset":    offset,
        "duration":        _DEFAULT_LOOP_DURATION,
    }


def live_snapshots() -> dict[str, Any]:
    """
    Return a {cam_id: { image_url, captured_at, lat, lng }} map for our cameras.

    Mapping: CAM-XX (our id) -> Singapore camera by index (CAM-01 → 1st Singapore
    cam, CAM-02 → 2nd, etc.). Singapore exposes 90 cameras; we have 24.
    """
    sg = _fetch_singapore_snapshots()
    sb = get_supabase()
    our_cams = (
        sb.table("tv_cameras").select("id, name, status").order("id").execute().data or []
    )
    out: dict[str, dict[str, Any]] = {}
    for i, cam in enumerate(our_cams):
        if i >= len(sg):
            break
        sg_cam = sg[i]
        entry: dict[str, Any] = {
            "image_url": sg_cam.get("image"),
            "captured_at": sg_cam.get("timestamp"),
            "source": "singapore_data_gov_sg",
            "source_cam_id": sg_cam.get("camera_id"),
            "lat": (sg_cam.get("location") or {}).get("latitude"),
            "lng": (sg_cam.get("location") or {}).get("longitude"),
            "image_width": (sg_cam.get("image_metadata") or {}).get("width"),
            "image_height": (sg_cam.get("image_metadata") or {}).get("height"),
        }
        # Phase 3+++: continuous-motion loop video overlay (preferred over JPG)
        loop = loop_assignment_for(cam["id"], i)
        if loop:
            entry["loop"] = loop
        out[cam["id"]] = entry
    return {
        "source": "https://api.data.gov.sg/v1/transport/traffic-images",
        "total": len(out),
        "snapshots": out,
        "cached_for_seconds": _SG_CACHE_TTL,
    }


# ============================================================
# Phase 3+ — YOLO detection overlays on the live snapshot tiles
# Real ultralytics inference on each Singapore JPG.
# Cached 30 s alongside the snapshot cache.
# ============================================================

_DETECT_CACHE: dict[str, Any] = {"ts": 0, "data": None, "snapshot_signature": None}
_DETECT_TTL = 30
# Phase A.1 — serialise compute across the bg thread + HTTP requests so we don't
# burst 2x Groq calls on cache misses.
import threading as _threading_detect
_DETECT_COMPUTE_LOCK = _threading_detect.Lock()

_COCO_LABEL_MAP = {
    0: "person",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    1: "bicycle",
}
_INTERESTING_CLASS_IDS = set(_COCO_LABEL_MAP.keys())

# Snapshot-detector uses a *bigger* YOLO model (yolov8s) than the video pipeline.
# Live tiles want maximum recall on small distant vehicles; videos are processed
# offline and don't need the same accuracy lift.
_YOLO_SNAP = None

def _get_yolo_snap():
    global _YOLO_SNAP
    if _YOLO_SNAP is None:
        from ultralytics import YOLO
        # Phase B.2 — YOLOv11s default (Sep 2024 release). 5-10% mAP gain over
        # v8s at near-identical latency. Drop-in: ultralytics auto-downloads.
        weights = os.getenv("YOLO_WEIGHTS_SNAP", "yolo11s.pt")
        log.info("Loading snapshot YOLO weights: %s", weights)
        _YOLO_SNAP = YOLO(weights)
    return _YOLO_SNAP


# Per-camera IoU-tracking state (OTVision-equivalent for live JPGs).
# Each entry: { 'next_id': int, 'prev_boxes': [{...box, track_id, lifetime}] }
_TRACK_STATE: dict[str, dict[str, Any]] = {}
_TRACK_IOU_THRESHOLD = 0.25


def _snapshot_signature(snaps: dict[str, dict[str, Any]]) -> str:
    """Cheap signature based on image URLs — changes when upstream refreshes."""
    return "|".join(f"{k}:{(v.get('image_url') or '')[-30:]}" for k, v in sorted(snaps.items()))


def _detect_in_jpg_bytes(jpg_bytes: bytes) -> list[dict[str, Any]]:
    """Run YOLOv8s on a single JPG byte-string. Returns normalized bboxes."""
    import cv2
    import numpy as np

    yolo = _get_yolo_snap()
    arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        return []
    h, w = frame.shape[:2]
    res = yolo(frame, verbose=False, conf=0.30, iou=0.5)[0]
    out: list[dict[str, Any]] = []
    for box in res.boxes:
        cls = int(box.cls[0].item())
        if cls not in _INTERESTING_CLASS_IDS:
            continue
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
        conf = float(box.conf[0].item())
        # Normalized 0..1 bbox coords for easy CSS overlay on any tile size
        out.append({
            "cls":   _COCO_LABEL_MAP[cls],
            "conf":  round(conf, 2),
            "x":     round(x1 / w, 4),
            "y":     round(y1 / h, 4),
            "w":     round((x2 - x1) / w, 4),
            "h":     round((y2 - y1) / h, 4),
        })
    return out


def _iou_norm(a: dict, b: dict) -> float:
    """IoU on normalized 0..1 bboxes (x, y, w, h)."""
    ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _assign_track_ids(cam_id: str, new_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    OTVision-equivalent IoU tracker for snapshot bboxes.

    Matches each new box to the highest-IoU prior box of the same class above
    the threshold. Unmatched boxes get a fresh track_id. Each tracked box gets
    a `lifetime` (consecutive snapshots where it has been seen).
    """
    state = _TRACK_STATE.setdefault(cam_id, {"next_id": 1, "prev_boxes": []})
    prev: list[dict[str, Any]] = state["prev_boxes"]

    out: list[dict[str, Any]] = []
    used = set()
    for nb in new_boxes:
        best_idx = -1
        # Read live so officers can re-tune via Settings UI without restart.
        try:
            best_iou = float(TV_LIVE_CONFIG.get("track_iou_threshold", _TRACK_IOU_THRESHOLD))
        except (TypeError, ValueError):
            best_iou = _TRACK_IOU_THRESHOLD
        for i, pb in enumerate(prev):
            if i in used or pb["cls"] != nb["cls"]:
                continue
            score = _iou_norm(nb, pb)
            if score > best_iou:
                best_iou = score
                best_idx = i
        if best_idx >= 0:
            tid = prev[best_idx]["track_id"]
            lifetime = (prev[best_idx].get("lifetime") or 1) + 1
            used.add(best_idx)
        else:
            tid = state["next_id"]
            state["next_id"] += 1
            lifetime = 1
        out.append({**nb, "track_id": tid, "lifetime": lifetime})

    state["prev_boxes"] = out
    return out


def detect_snapshots() -> dict[str, Any]:
    """
    Run YOLO across all 24 mapped Singapore snapshots and return per-camera bboxes.
    Cached for 30 s + invalidated when the snapshot signature changes.

    Phase A.1: after the YOLO pass on each cam, the heuristic gate decides whether
    to spend a Groq Vision call to semantically classify the frame. If Groq reports
    a violation, we synthesise a tv_incidents row in PENDING_REVIEW status and save
    the JPG as evidence. Cooldowns prevent duplicate incidents on the same cam.
    """
    import time as _t
    snaps_body = live_snapshots()
    snaps = snaps_body.get("snapshots") or {}
    sig = _snapshot_signature(snaps)
    now = _t.time()

    if (
        _DETECT_CACHE["data"] is not None
        and _DETECT_CACHE["snapshot_signature"] == sig
        and (now - _DETECT_CACHE["ts"]) < _DETECT_TTL
    ):
        return _DETECT_CACHE["data"]

    # Serialise compute across threads — without this, the bg thread and an HTTP
    # request can both miss the cache and run TWO Groq cycles in parallel.
    with _DETECT_COMPUTE_LOCK:
        # Re-check cache (another thread may have computed while we waited).
        if (
            _DETECT_CACHE["data"] is not None
            and _DETECT_CACHE["snapshot_signature"] == sig
            and (_t.time() - _DETECT_CACHE["ts"]) < _DETECT_TTL
        ):
            return _DETECT_CACHE["data"]
        return _compute_detect_payload(snaps, sig)


def _compute_detect_payload(snaps: dict[str, Any], sig: str) -> dict[str, Any]:
    """Inner: the actual compute. Caller must hold _DETECT_COMPUTE_LOCK."""
    import time as _t
    per_cam: dict[str, list[dict[str, Any]]] = {}
    summary = {"cars": 0, "motorcycles": 0, "buses": 0, "trucks": 0, "persons": 0, "bicycles": 0, "total": 0}
    live_incidents_created: list[str] = []
    live_violation_labels: dict[str, list[dict[str, Any]]] = {}
    # Reset per-cycle Groq budget so we don't carry over from the prior cycle
    _GROQ_CYCLE_COUNTER["calls"] = 0

    try:
        with httpx.Client(timeout=8.0) as client:
            for cam_id, info in snaps.items():
                url = info.get("image_url")
                if not url:
                    per_cam[cam_id] = []
                    continue
                jpg_bytes: Optional[bytes] = None
                try:
                    r = client.get(url)
                    if r.status_code != 200:
                        per_cam[cam_id] = []
                        continue
                    jpg_bytes = r.content
                    raw_boxes = _detect_in_jpg_bytes(jpg_bytes)
                    boxes = _assign_track_ids(cam_id, raw_boxes)
                except Exception as e:
                    log.debug("detect fetch failed for %s: %s", cam_id, e)
                    boxes = []
                per_cam[cam_id] = boxes
                if jpg_bytes:
                    # Phase A.4 — feed the rolling frame buffer + tick pending clip captures.
                    _push_cam_frame(cam_id, jpg_bytes)
                    _tick_clip_captures(cam_id, jpg_bytes)
                for b in boxes:
                    if b["cls"] == "car":         summary["cars"] += 1
                    elif b["cls"] == "motorcycle": summary["motorcycles"] += 1
                    elif b["cls"] == "bus":        summary["buses"] += 1
                    elif b["cls"] == "truck":      summary["trucks"] += 1
                    elif b["cls"] == "person":     summary["persons"] += 1
                    elif b["cls"] == "bicycle":    summary["bicycles"] += 1
                    summary["total"] += 1

                # Phase A.1: live-incident auto-pipeline (Smart Groq Vision gate)
                if jpg_bytes and boxes and _live_pipeline_enabled():
                    try:
                        result = _maybe_create_live_incidents_for_cam(
                            cam_id=cam_id, jpg_bytes=jpg_bytes, boxes=boxes, snapshot_info=info,
                        )
                        if result:
                            live_incidents_created.extend(result.get("incident_ids") or [])
                            if result.get("violation_labels"):
                                live_violation_labels[cam_id] = result["violation_labels"]
                    except Exception as e:
                        log.warning("live-pipeline failed for %s: %s", cam_id, e)
    except Exception as e:
        log.exception("detect_snapshots failed: %s", e)

    payload = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "cached_for_seconds": _DETECT_TTL,
        "summary": summary,
        "detections": per_cam,
        # Phase A.1 surfacing:
        "live_violation_labels": _merge_violation_labels(_LIVE_LABELS_RECENT, live_violation_labels),
        "live_incidents_created_recent": live_incidents_created,
    }
    _DETECT_CACHE["data"] = payload
    _DETECT_CACHE["ts"] = _t.time()
    _DETECT_CACHE["snapshot_signature"] = sig
    return payload


# ============================================================
# Phase A.1 — Live → Auto-Incident pipeline (Smart Groq Vision gate)
# ============================================================
# The heuristic gate runs free per-cycle. Only frames that look "suspicious"
# (motorcycle present, possible pedestrian on road, stationary truck/bus,
#  high vehicle density, sudden track vanish) spend a Groq Vision call.
# Groq returns semantic violations (accident, no_helmet, lane_violation, ...).
# On confirmed violation we insert a tv_incidents row in PENDING_REVIEW and
# save the JPG as evidence. Cooldowns prevent duplicate incidents per cam.

import time as _time
# CLIPS_DIR (.tv_clips) is created once near the upload-pipeline section below;
# we just reference the directory from there at write-time.

# (cam_id, violation_type) -> last_created_at epoch
_LIVE_VIOLATION_COOLDOWN: dict[tuple[str, str], float] = {}
# cam_id -> last_groq_call_at epoch
_LIVE_GROQ_COOLDOWN: dict[str, float] = {}
# cam_id -> [{type, severity, label, at}]  — rolling list shown on UI tile chips
_LIVE_LABELS_RECENT: dict[str, list[dict[str, Any]]] = {}

# ---------- Phase C — Runtime-mutable config ----------
# All tunables live here. Officers can change them live via Settings UI
# (PUT /api/traffic-violations/config). Env vars seed the initial defaults
# so docker / prod can still bake in their preferred values.
_DEFAULT_BUDGET = 2 if os.getenv("TV_VISION_PROVIDER", "ollama").lower() != "groq" else 4

TV_LIVE_CONFIG: dict[str, Any] = {
    "live_pipeline_enabled":   os.getenv("TV_LIVE_PIPELINE", "1") not in ("0", "false", "False"),
    "vision_provider":         os.getenv("TV_VISION_PROVIDER", "ollama"),
    "groq_cooldown_secs":      int(os.getenv("TV_LIVE_GROQ_COOLDOWN", "180")),
    "incident_cooldown_secs":  int(os.getenv("TV_LIVE_INCIDENT_COOLDOWN", "300")),
    "label_ttl_secs":          int(os.getenv("TV_LIVE_LABEL_TTL", "120")),
    "groq_budget_per_cycle":   int(os.getenv("TV_LIVE_GROQ_BUDGET", str(_DEFAULT_BUDGET))),
    "stationary_lifetime_heavy": 3,   # truck/bus persistence
    "stationary_lifetime_moto":  2,   # motorcycle persistence (helmet candidate)
    "density_suspicious":      14,    # vehicle count above which we flag congestion
    "clip_frames_after":       int(os.getenv("TV_LIVE_CLIP_FRAMES_AFTER", "5")),
    "clip_fps":                int(os.getenv("TV_LIVE_CLIP_FPS", "2")),
    "frame_buffer_size":       5,
    "detect_cache_ttl_secs":   30,
    "track_iou_threshold":     0.25,
}

# Allowed keys + their value types (used for PUT validation)
TV_LIVE_CONFIG_SCHEMA: dict[str, type] = {
    "live_pipeline_enabled":    bool,
    "vision_provider":          str,
    "groq_cooldown_secs":       int,
    "incident_cooldown_secs":   int,
    "label_ttl_secs":           int,
    "groq_budget_per_cycle":    int,
    "stationary_lifetime_heavy": int,
    "stationary_lifetime_moto":  int,
    "density_suspicious":       int,
    "clip_frames_after":        int,
    "clip_fps":                 int,
    "frame_buffer_size":        int,
    "detect_cache_ttl_secs":    int,
    "track_iou_threshold":      float,
}

# Global backoff window in seconds when Groq returns 429 (set dynamically)
_GROQ_BACKOFF_UNTIL: float = 0.0
# Reset per-cycle counter (mutated by detect_snapshots)
_GROQ_CYCLE_COUNTER: dict[str, int] = {"calls": 0}


def get_live_config() -> dict[str, Any]:
    return dict(TV_LIVE_CONFIG)


def update_live_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Validate + apply a patch to the live config. Returns the new full dict."""
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    rejected: dict[str, str] = {}
    applied: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in TV_LIVE_CONFIG_SCHEMA:
            rejected[k] = "unknown key"
            continue
        want = TV_LIVE_CONFIG_SCHEMA[k]
        # bool is a subclass of int — special-case before the int path.
        try:
            if want is bool:
                if isinstance(v, bool):
                    coerced = v
                elif isinstance(v, (int, float)):
                    coerced = bool(v)
                elif isinstance(v, str):
                    coerced = v.strip().lower() in ("1", "true", "yes", "on")
                else:
                    raise ValueError("bool expected")
            elif want is int:
                coerced = int(v)
            elif want is float:
                coerced = float(v)
            elif want is str:
                coerced = str(v).strip()
                if k == "vision_provider" and coerced not in ("ollama", "groq", "auto"):
                    rejected[k] = f"invalid vision_provider: {coerced!r}"
                    continue
            else:
                rejected[k] = f"unsupported type {want.__name__}"
                continue
            TV_LIVE_CONFIG[k] = coerced
            applied[k] = coerced
        except Exception as e:
            rejected[k] = f"coercion failed: {e}"
    return {"config": dict(TV_LIVE_CONFIG), "applied": applied, "rejected": rejected}


def _live_pipeline_enabled() -> bool:
    """Master kill-switch — toggle live config.live_pipeline_enabled."""
    return bool(TV_LIVE_CONFIG.get("live_pipeline_enabled", True))


def _should_classify_with_groq(cam_id: str, boxes: list[dict[str, Any]]) -> tuple[bool, str]:
    """
    Cheap heuristic gate. Returns (should_classify, reason).
    Reason is logged for explainability ("why did this cam get a Groq call?").

    Tight by design — urban Singapore cams have constant flow; we only spend a
    Groq call when something *unusual* persists across cycles or violates an
    obvious rule (pedestrian on road, stalled heavy vehicle, sudden crowd).
    """
    cfg = TV_LIVE_CONFIG
    now = _time.time()

    # Global 429 backoff — pause everyone for ~60 s after a rate-limit hit.
    if now < _GROQ_BACKOFF_UNTIL:
        return False, f"backoff_{int(_GROQ_BACKOFF_UNTIL - now)}s"

    # Per-cycle budget — at most N vision calls per detect_snapshots cycle.
    if _GROQ_CYCLE_COUNTER["calls"] >= cfg["groq_budget_per_cycle"]:
        return False, "cycle_budget"

    # Per-cam cooldown — same cam can't burn vision more than once per window.
    last = _LIVE_GROQ_COOLDOWN.get(cam_id, 0)
    if now - last < cfg["groq_cooldown_secs"]:
        return False, "cam_cooldown"
    if not boxes:
        return False, "no_boxes"

    # Stationary motorcycle — must persist across cycles. Stops the "every flow
    # of bikes triggers a helmet check" blowout we hit on the first run.
    stationary_motorcycles = [
        b for b in boxes
        if b["cls"] == "motorcycle"
        and (b.get("lifetime") or 0) >= cfg["stationary_lifetime_moto"]
        and b.get("conf", 0) >= 0.50
    ]
    if stationary_motorcycles:
        return True, f"stationary_moto({len(stationary_motorcycles)})"

    # Person standing in the road (lower 60% of frame, not on shoulder)
    person_on_road = [
        b for b in boxes
        if b["cls"] == "person"
        and b.get("y", 0) > 0.30
        and b.get("w", 0) > 0.04
        and (b.get("lifetime") or 0) >= 2
        and b.get("conf", 0) >= 0.50
    ]
    if person_on_road:
        return True, f"person_on_road({len(person_on_road)})"

    # Stationary truck or bus mid-frame — accident candidate
    stationary_heavy = [
        b for b in boxes
        if b["cls"] in ("truck", "bus")
        and (b.get("lifetime") or 0) >= cfg["stationary_lifetime_heavy"]
        and b.get("y", 0) > 0.20 and b.get("y", 0) < 0.85
    ]
    if stationary_heavy:
        return True, f"stationary_heavy({len(stationary_heavy)})"

    # Sudden very high density — possible congestion / pile-up
    if len(boxes) >= cfg["density_suspicious"]:
        return True, f"density({len(boxes)})"

    return False, "below_threshold"


# Per-class BGR colour table for the evidence overlay (cv2 uses BGR not RGB)
_EVIDENCE_BOX_BGR = {
    "car":        (255, 200,   0),    # cyan-ish
    "truck":      (  0, 200, 255),    # amber
    "bus":        (255,   0, 255),    # magenta
    "motorcycle": (255, 255,   0),    # yellow
    "person":     (  0, 255, 100),    # green
}


def _annotate_evidence_jpg(
    jpg_bytes: bytes,
    boxes: list[dict[str, Any]],
    vtype: str,
    severity: str,
    focus_box: Optional[dict[str, Any]] = None,
    description: str = "",
    plate: Optional[str] = None,
) -> bytes:
    """
    Burn YOLO bboxes into the JPG so officers can see EXACTLY where the
    violation was committed. Returns the annotated image as JPG bytes; falls
    back to the original bytes on any failure.

    The `focus_box` (typically the largest vehicle for plate OCR, or the
    nearest violator) is highlighted in red with a "VIOLATION" tag so the
    suspect is unambiguous.
    """
    if not jpg_bytes:
        return jpg_bytes
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return jpg_bytes
        h, w = img.shape[:2]

        # ------- draw all secondary bboxes (passive context) -------
        for b in boxes or []:
            cls = b.get("cls", "")
            colour = _EVIDENCE_BOX_BGR.get(cls, (180, 180, 180))
            x1 = int(max(0, (b.get("x") or 0) * w))
            y1 = int(max(0, (b.get("y") or 0) * h))
            x2 = int(min(w - 1, ((b.get("x") or 0) + (b.get("w") or 0)) * w))
            y2 = int(min(h - 1, ((b.get("y") or 0) + (b.get("h") or 0)) * h))
            if x2 <= x1 or y2 <= y1:
                continue
            is_focus = bool(focus_box) and b is focus_box
            if is_focus:
                continue  # drawn later on top
            cv2.rectangle(img, (x1, y1), (x2, y2), colour, 2)
            tag = f"{cls.upper()} {int(round((b.get('conf') or 0) * 100))}%"
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(img, (x1, max(0, y1 - th - 6)),
                          (x1 + tw + 6, y1), colour, -1)
            cv2.putText(img, tag, (x1 + 3, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

        # ------- draw the violator focus box -------
        if focus_box:
            x1 = int(max(0, (focus_box.get("x") or 0) * w))
            y1 = int(max(0, (focus_box.get("y") or 0) * h))
            x2 = int(min(w - 1, ((focus_box.get("x") or 0) + (focus_box.get("w") or 0)) * w))
            y2 = int(min(h - 1, ((focus_box.get("y") or 0) + (focus_box.get("h") or 0)) * h))
            if x2 > x1 and y2 > y1:
                # double thick red rectangle + corner marks
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 4)
                corner = max(8, int(min(x2 - x1, y2 - y1) * 0.18))
                cv2.line(img, (x1, y1), (x1 + corner, y1), (0, 255, 255), 4)
                cv2.line(img, (x1, y1), (x1, y1 + corner), (0, 255, 255), 4)
                cv2.line(img, (x2, y1), (x2 - corner, y1), (0, 255, 255), 4)
                cv2.line(img, (x2, y1), (x2, y1 + corner), (0, 255, 255), 4)
                cv2.line(img, (x1, y2), (x1 + corner, y2), (0, 255, 255), 4)
                cv2.line(img, (x1, y2), (x1, y2 - corner), (0, 255, 255), 4)
                cv2.line(img, (x2, y2), (x2 - corner, y2), (0, 255, 255), 4)
                cv2.line(img, (x2, y2), (x2, y2 - corner), (0, 255, 255), 4)
                label = f"[!] {VIOLATION_LABEL.get(vtype, vtype.upper())}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
                cv2.rectangle(img, (x1, max(0, y1 - th - 12)),
                              (x1 + tw + 14, y1), (0, 0, 255), -1)
                cv2.putText(img, label, (x1 + 6, max(20, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

        # ------- top-strip banner: severity + type + plate + timestamp -------
        sev_col = {
            "CRITICAL": (0, 0, 255),
            "HIGH":     (0, 80, 255),
            "MEDIUM":   (0, 200, 255),
            "LOW":      (0, 255, 200),
        }.get((severity or "").upper(), (0, 200, 255))
        banner_h = 38
        cv2.rectangle(img, (0, 0), (w, banner_h), (0, 0, 0), -1)
        cv2.rectangle(img, (0, 0), (max(8, int(w * 0.012)), banner_h), sev_col, -1)
        header = f"CITADEL | {VIOLATION_LABEL.get(vtype, vtype.upper())} | {severity.upper()}"
        if plate:
            header += f" | PLATE {plate}"
        cv2.putText(img, header, (16, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
        ts_text = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        (tw, _), _ = cv2.getTextSize(ts_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(img, ts_text, (w - tw - 12, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)

        # ------- bottom caption (Groq description) -------
        if description:
            cap = description[:96] + ("..." if len(description) > 96 else "")
            (tw, th), _ = cv2.getTextSize(cap, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            y0 = h - th - 14
            cv2.rectangle(img, (0, y0 - 4), (w, h), (0, 0, 0), -1)
            cv2.putText(img, cap, (12, y0 + th + 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        return buf.tobytes() if ok else jpg_bytes
    except Exception as e:
        log.warning("evidence annotation failed: %s", e)
        return jpg_bytes


def _save_live_evidence_jpg(
    jpg_bytes: bytes,
    inc_id: str,
    *,
    boxes: Optional[list[dict[str, Any]]] = None,
    vtype: str = "",
    severity: str = "",
    focus_box: Optional[dict[str, Any]] = None,
    description: str = "",
    plate: Optional[str] = None,
) -> Optional[str]:
    """
    Save the JPG to .tv_clips/{inc_id}.jpg with bbox + violator overlay so the
    evidence shows EXACTLY where the violation was. Returns the absolute path.

    Two files are written when annotation succeeds:
      - {inc_id}.jpg          (annotated, default for UI + Telegram)
      - {inc_id}.raw.jpg      (the original unmarked frame, for audit)
    """
    try:
        annotated = _annotate_evidence_jpg(
            jpg_bytes, boxes or [], vtype, severity, focus_box,
            description=description, plate=plate,
        )
        out = CLIPS_DIR / f"{inc_id}.jpg"
        out.write_bytes(annotated)
        # Save the raw frame too so we can re-render the overlay if needed
        try:
            raw = CLIPS_DIR / f"{inc_id}.raw.jpg"
            raw.write_bytes(jpg_bytes)
        except Exception:
            pass
        return str(out)
    except Exception as e:
        log.warning("evidence save failed for %s: %s", inc_id, e)
        return None


# Phase A.4 — rolling per-cam frame buffer + pending capture jobs.
# When an incident is created we snap the prior N frames from the buffer,
# then collect the next N frames over subsequent cycles and stitch all
# into .tv_clips/{inc_id}.mp4 at 2 fps (≈10 s of "before + after" context
# compressed from real time so officers see what led up to the violation).
_CAM_FRAME_BUFFER: dict[str, list[bytes]] = {}
_PENDING_CLIP_CAPTURES: dict[str, dict[str, Any]] = {}


def _push_cam_frame(cam_id: str, jpg_bytes: bytes) -> None:
    buf = _CAM_FRAME_BUFFER.setdefault(cam_id, [])
    buf.append(jpg_bytes)
    cap = TV_LIVE_CONFIG.get("frame_buffer_size", 5)
    while len(buf) > cap:
        buf.pop(0)


def _queue_clip_capture(inc_id: str, cam_id: str) -> None:
    """Capture starts NOW — seed with whatever's in the rolling buffer."""
    cap = TV_LIVE_CONFIG.get("frame_buffer_size", 5)
    pre = list(_CAM_FRAME_BUFFER.get(cam_id, []))
    _PENDING_CLIP_CAPTURES[inc_id] = {
        "cam_id": cam_id,
        "frames": pre[-cap:],
        "remaining": TV_LIVE_CONFIG.get("clip_frames_after", 5),
        "started_at": _time.time(),
    }


def _tick_clip_captures(cam_id: str, jpg_bytes: bytes) -> None:
    """For every pending capture on this cam, append the fresh frame.
    Finalise once remaining hits 0."""
    for inc_id in list(_PENDING_CLIP_CAPTURES.keys()):
        p = _PENDING_CLIP_CAPTURES[inc_id]
        if p["cam_id"] != cam_id:
            continue
        # Avoid appending the same incident-anchor frame twice (the queueing
        # step seeds the buffer; this tick fires AFTER the anchor cycle).
        if p["remaining"] <= 0:
            _PENDING_CLIP_CAPTURES.pop(inc_id, None)
            continue
        p["frames"].append(jpg_bytes)
        p["remaining"] -= 1
        if p["remaining"] <= 0:
            try:
                _finalise_live_clip(inc_id, p["frames"])
            finally:
                _PENDING_CLIP_CAPTURES.pop(inc_id, None)


def _finalise_live_clip(inc_id: str, frame_jpgs: list[bytes]) -> Optional[str]:
    """Stitch a list of JPG bytes into .tv_clips/{inc_id}.mp4. Best-effort."""
    if not frame_jpgs:
        return None
    try:
        import cv2
        import numpy as np
        frames: list[Any] = []
        h, w = 0, 0
        for jb in frame_jpgs:
            arr = np.frombuffer(jb, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                continue
            if not frames:
                h, w = img.shape[:2]
            elif (img.shape[0], img.shape[1]) != (h, w):
                img = cv2.resize(img, (w, h))
            frames.append(img)
        if not frames or w == 0 or h == 0:
            return None
        out_path = CLIPS_DIR / f"{inc_id}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps = TV_LIVE_CONFIG.get("clip_fps", 2)
        writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
        if not writer.isOpened():
            log.warning("VideoWriter failed to open for %s", inc_id)
            return None
        for f in frames:
            writer.write(f)
        writer.release()
        # Update tv_incidents.video_clip_path so the audit shows a clip
        try:
            sb = get_supabase()
            sb.table("tv_incidents").update({
                "video_clip_path": str(out_path),
                "duration_seconds": len(frames) / max(1, fps),
            }).eq("inc_id", inc_id).execute()
        except Exception as e:
            log.debug("update tv_incidents.video_clip_path failed for %s: %s", inc_id, e)
        log.info("Live evidence clip saved: %s (%d frames)", out_path, len(frames))
        return str(out_path)
    except Exception as e:
        log.warning("clip stitch failed for %s: %s", inc_id, e)
        return None


# Phase A.3 — plate OCR on the largest vehicle bbox in the live snapshot.
# Uses OCR.Space via the existing plate_ocr.py. Cached per-cam track_id so we
# don't re-OCR the same vehicle across cycles.
_LIVE_PLATE_CACHE: dict[tuple[str, int], tuple[str, float, float]] = {}
_LIVE_PLATE_CACHE_TTL = 600  # 10 minutes per (cam, track_id)


def _largest_vehicle_box(boxes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Find the largest vehicle (car/truck/bus/motorcycle) bbox by area."""
    cands = [b for b in boxes if b.get("cls") in ("car", "truck", "bus", "motorcycle")]
    if not cands:
        return None
    return max(cands, key=lambda b: (b.get("w") or 0) * (b.get("h") or 0))


def _extract_plate_for_live(jpg_bytes: bytes, cam_id: str, boxes: list[dict[str, Any]]) -> tuple[Optional[str], float]:
    """
    Attempt to OCR the license plate from the largest vehicle bbox in the frame.
    Returns (plate_text, confidence). Cached per (cam, track_id).
    """
    box = _largest_vehicle_box(boxes)
    if not box:
        return None, 0.0
    track_id = box.get("track_id")
    if track_id is not None:
        cache_key = (cam_id, int(track_id))
        cached = _LIVE_PLATE_CACHE.get(cache_key)
        now = _time.time()
        if cached and (now - cached[2]) < _LIVE_PLATE_CACHE_TTL:
            return cached[0], cached[1]
    try:
        import cv2
        import numpy as np
        from app.modules.traffic_violations import plate_ocr

        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return None, 0.0
        h, w = frame.shape[:2]
        # Convert normalized bbox (0..1) back to pixel coords for plate_ocr
        x1 = int(max(0, box["x"] * w))
        y1 = int(max(0, box["y"] * h))
        x2 = int(min(w, (box["x"] + box["w"]) * w))
        y2 = int(min(h, (box["y"] + box["h"]) * h))
        plate, conf = plate_ocr.read_plate_from_bbox(frame, (x1, y1, x2, y2))
        if track_id is not None:
            _LIVE_PLATE_CACHE[(cam_id, int(track_id))] = (plate, conf, _time.time())
        return plate, conf
    except Exception as e:
        log.debug("plate OCR failed for %s: %s", cam_id, e)
        return None, 0.0


def _severity_to_label(sev: str) -> str:
    s = (sev or "").strip().lower()
    return {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(s, "MEDIUM")


def _merge_violation_labels(rolling: dict[str, list[dict[str, Any]]],
                            fresh: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Maintain a rolling per-cam list of violation labels (TTL-pruned) for the UI tile chips."""
    now = _time.time()
    out: dict[str, list[dict[str, Any]]] = {}
    # Prune stale entries from rolling first
    for cam, items in (rolling or {}).items():
        kept = [it for it in items if (now - (it.get("ts") or 0)) < TV_LIVE_CONFIG.get("label_ttl_secs", 120)]
        if kept:
            out[cam] = kept
    # Merge fresh entries on top
    for cam, items in (fresh or {}).items():
        if not items:
            continue
        existing = out.setdefault(cam, [])
        for it in items:
            it = dict(it)
            it["ts"] = now
            existing.insert(0, it)
        out[cam] = existing[:5]  # keep last 5 per cam
    # Persist back
    rolling.clear()
    rolling.update(out)
    return out


def _maybe_create_live_incidents_for_cam(
    cam_id: str,
    jpg_bytes: bytes,
    boxes: list[dict[str, Any]],
    snapshot_info: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    Heuristic gate -> Groq Vision -> per-violation cooldown -> DB insert.
    Returns {incident_ids: [...], violation_labels: [{type, severity, label, reason}]}.
    """
    global _GROQ_BACKOFF_UNTIL

    should, reason = _should_classify_with_groq(cam_id, boxes)
    if not should:
        return None

    _LIVE_GROQ_COOLDOWN[cam_id] = _time.time()
    _GROQ_CYCLE_COUNTER["calls"] = _GROQ_CYCLE_COUNTER.get("calls", 0) + 1

    # Lazy import — keeps service.py importable without the optional groq dep
    from app.modules.traffic_violations import groq_vision

    try:
        result = groq_vision.classify_frame(jpg_bytes)
    except Exception as e:
        log.warning("groq_vision.classify_frame failed for %s: %s", cam_id, e)
        return None

    # Provider-specific error detection. Groq quota errors trigger a global
    # backoff. Local Ollama errors are per-frame transient — don't back off.
    scene_marker = (result or {}).get("scene") or ""
    if "(http error: 429" in scene_marker or "(http error: 4" in scene_marker:
        _GROQ_BACKOFF_UNTIL = _time.time() + 60
        log.warning("Vision (Groq) 429/auth for %s — backing off cloud calls for 60s", cam_id)
        return None
    if "(ollama" in scene_marker or "(error:" in scene_marker:
        log.info("Vision (Ollama) transient error for %s: %s", cam_id, scene_marker)
        return None

    violations = (result or {}).get("violations") or []
    if not violations:
        return None

    sb = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()
    incident_ids: list[str] = []
    violation_labels: list[dict[str, Any]] = []

    for v in violations:
        vtype = (v.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not vtype or vtype not in VIOLATION_LABEL:
            continue
        severity = _severity_to_label(v.get("severity") or "medium")
        # Cooldown per (cam_id, violation_type) — don't spam dupes
        ck = (cam_id, vtype)
        last_at = _LIVE_VIOLATION_COOLDOWN.get(ck, 0)
        if _time.time() - last_at < TV_LIVE_CONFIG["incident_cooldown_secs"]:
            violation_labels.append({
                "type": vtype, "severity": severity,
                "label": VIOLATION_LABEL.get(vtype, vtype.upper()),
                "reason": reason, "cooled": True,
            })
            continue

        inc_id = _next_human_inc_id()
        description = (v.get("description") or "")[:240]

        # Phase A.3 — extract plate from the largest vehicle bbox before insert.
        plate_text, plate_conf = _extract_plate_for_live(jpg_bytes, cam_id, boxes)

        # Phase 6.2 — burn YOLO bboxes + violator marker onto the evidence JPG
        # so officers can SEE which vehicle / person committed the violation.
        # Pick the focus box by violation semantics, not by raw area.
        def _focus_for(vt: str, _boxes: list[dict[str, Any]]):
            def _largest(cls_pred):
                cands = [b for b in _boxes if cls_pred(b.get("cls"))]
                return max(cands, key=lambda b: (b.get("w") or 0) * (b.get("h") or 0)) if cands else None
            if vt in ("no_helmet",):
                # rider on a motorcycle without helmet
                return _largest(lambda c: c == "motorcycle") or _largest(lambda c: c == "person")
            if vt in ("no_seatbelt",):
                # car/truck driver — pick the dominant 4-wheeler
                return _largest(lambda c: c in ("car", "truck", "bus"))
            if vt in ("speeding", "rash_driving"):
                return _largest(lambda c: c in ("car", "truck", "bus", "motorcycle"))
            if vt in ("illegal_parking",):
                return _largest(lambda c: c in ("car", "truck", "bus"))
            if vt in ("red_light", "wrong_lane", "lane_violation"):
                return _largest(lambda c: c in ("car", "truck", "bus", "motorcycle"))
            if vt in ("accident", "overturned", "debris"):
                return _largest(lambda c: c in ("car", "truck", "bus", "motorcycle"))
            if vt in ("overload",):
                return _largest(lambda c: c in ("truck", "bus"))
            # default — biggest vehicle
            return _largest(lambda c: c in ("car", "truck", "bus", "motorcycle"))
        focus = _focus_for(vtype, boxes)
        evidence_path = _save_live_evidence_jpg(
            jpg_bytes, inc_id,
            boxes=boxes, vtype=vtype, severity=severity,
            focus_box=focus, description=description, plate=plate_text,
        )

        row = {
            "inc_id": inc_id,
            "cam_id": cam_id,
            "upload_filename": None,
            "video_clip_path": None,
            "full_video_path": None,
            "violation_type": vtype,
            "severity": severity,
            "plate": plate_text,
            "plate_confidence": plate_conf if plate_text else None,
            "detection_confidence": 0.85,
            "detected_at": now_iso,
            "status": "PENDING_REVIEW",
            "frame_metadata": {
                "source":        "live_snapshot",
                "groq_reason":   reason,
                "groq_scene":    (result.get("scene") or "")[:240],
                "description":   description,
                "evidence_jpg":  evidence_path,
                "image_url":     snapshot_info.get("image_url"),
                "source_cam_id": snapshot_info.get("source_cam_id"),
                "lat":           snapshot_info.get("lat"),
                "lng":           snapshot_info.get("lng"),
                "plate_visible": bool(v.get("plate_visible")),
                "box_count":     len(boxes),
            },
            "duration_seconds": 0.0,
        }
        try:
            sb.table("tv_incidents").insert(row).execute()
            incident_ids.append(inc_id)
            _LIVE_VIOLATION_COOLDOWN[ck] = _time.time()
            # Phase A.4 — schedule a slideshow-clip capture for this incident.
            _queue_clip_capture(inc_id, cam_id)
            violation_labels.append({
                "type": vtype, "severity": severity,
                "label": VIOLATION_LABEL.get(vtype, vtype.upper()),
                "reason": reason, "inc_id": inc_id,
            })
            # Best-effort audit
            try:
                sb.table("tv_audit_log").insert({
                    "entity_type": "incident",
                    "entity_id": inc_id,
                    "action": "detected_live",
                    "actor": "live_pipeline",
                    "payload": {
                        "cam_id":       cam_id,
                        "violation":    vtype,
                        "severity":     severity,
                        "groq_reason":  reason,
                        "groq_scene":   result.get("scene"),
                    },
                }).execute()
            except Exception:
                pass
        except Exception as e:
            log.warning("live incident insert failed for %s on %s: %s", vtype, cam_id, e)

    if not incident_ids and not violation_labels:
        return None
    return {"incident_ids": incident_ids, "violation_labels": violation_labels}


# ============================================================
# Phase 3++ — Background pre-warm: keep detection cache always fresh
# Runs a daemon thread that loops every 30 s, so /snapshots/detect HTTP
# requests always return cached data (0 ms cold start).
# ============================================================

import threading

_BG_DETECT_THREAD: Optional[threading.Thread] = None
_BG_DETECT_STOP = threading.Event()


def _bg_detect_loop():
    log.info("Traffic Violations: background snapshot-detection loop started")
    while not _BG_DETECT_STOP.is_set():
        try:
            detect_snapshots()  # populates _DETECT_CACHE
        except Exception as e:
            log.warning("bg detect cycle failed: %s", e)
        # sleep with periodic stop-event check so shutdown is responsive
        _BG_DETECT_STOP.wait(timeout=30)


def start_background_detection() -> None:
    """Idempotent: start the pre-warm loop. Call from FastAPI lifespan startup."""
    global _BG_DETECT_THREAD
    if _BG_DETECT_THREAD and _BG_DETECT_THREAD.is_alive():
        return
    _BG_DETECT_STOP.clear()
    _BG_DETECT_THREAD = threading.Thread(
        target=_bg_detect_loop,
        name="tv-bg-detect",
        daemon=True,
    )
    _BG_DETECT_THREAD.start()


def stop_background_detection() -> None:
    """Signal the loop to stop. Call from FastAPI lifespan shutdown."""
    _BG_DETECT_STOP.set()


# ============================================================
# Phase 1+ — Plate history (lookup all incidents+challans for a single plate)
# ============================================================

def plate_history(plate: str) -> dict[str, Any]:
    sb = get_supabase()
    p = (plate or "").strip().upper()
    if not p:
        return {"plate": "", "found": False}

    drivers = (sb.table("tv_drivers").select("*").eq("plate", p).execute().data or [])
    driver = drivers[0] if drivers else None

    incidents = (
        sb.table("tv_incidents")
        .select("*")
        .eq("plate", p)
        .order("detected_at", desc=True)
        .execute()
    ).data or []
    challans = (
        sb.table("tv_challans")
        .select("*")
        .eq("plate", p)
        .order("issued_at", desc=True)
        .execute()
    ).data or []

    total_pending = sum(
        (c.get("amount") or 0)
        for c in challans
        if (c.get("status") or "").upper() != "PAID"
    )

    risk = "HIGH" if len(incidents) >= 10 else "MEDIUM" if len(incidents) >= 5 else "LOW"

    return {
        "plate": p,
        "found": bool(driver) or bool(incidents) or bool(challans),
        "driver_name": (driver or {}).get("driver_name"),
        "telegram_chat_id": (driver or {}).get("telegram_chat_id"),
        "incidents": [_shape_incident(i) for i in incidents],
        "challans": [_shape_challan(c) for c in challans],
        "total_incidents": len(incidents),
        "total_challans": len(challans),
        "total_pending": total_pending,
        "risk": risk,
    }


# ============================================================
# Phase 1+ — Bulk incident actions (approve/reject many at once)
# Phase 3 will wire the Telegram challan creation on approve. For now we just
# update statuses + log to tv_audit_log so the workflow shape is locked in.
# ============================================================

# ============================================================
# Phase 1+ — SLA queue (challans approaching due_by + overdue)
# ============================================================

def challan_sla(window_days: int = 7) -> dict[str, Any]:
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    upcoming_cutoff = (now + timedelta(days=window_days)).isoformat()
    now_iso = now.isoformat()

    rows = (
        sb.table("tv_challans")
        .select("*")
        .neq("status", "PAID")
        .lte("due_by", upcoming_cutoff)
        .order("due_by")
        .execute()
    ).data or []

    overdue, approaching = [], []
    for c in rows:
        shaped = _shape_challan(c)
        due = c.get("due_by") or ""
        shaped["due_by_iso"] = due
        if due < now_iso:
            shaped["days_overdue"] = max(0, (now - datetime.fromisoformat(due.replace("Z", "+00:00"))).days)
            overdue.append(shaped)
        else:
            shaped["days_until_due"] = max(0, (datetime.fromisoformat(due.replace("Z", "+00:00")) - now).days)
            approaching.append(shaped)

    total_at_risk = sum(c.get("amt", 0) for c in overdue + approaching)

    return {
        "window_days": window_days,
        "overdue_count": len(overdue),
        "approaching_count": len(approaching),
        "total_at_risk": total_at_risk,
        "overdue": overdue,
        "approaching": approaching,
    }


# ============================================================
# Phase 1+ — Revenue forecast (next-30d projection)
# ============================================================

def revenue_forecast(days: int = 30) -> dict[str, Any]:
    sb = get_supabase()
    # base: last 30d issuance + collection
    since_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = (
        sb.table("tv_challans")
        .select("amount, status")
        .gte("issued_at", since_30d)
        .execute()
    ).data or []
    issued_30d = len(recent)
    paid_30d = [r for r in recent if (r.get("status") or "").upper() == "PAID"]
    paid_amount = sum(r.get("amount") or 0 for r in paid_30d)
    issued_amount = sum(r.get("amount") or 0 for r in recent)
    collection_rate = (sum(1 for _ in paid_30d) / issued_30d) if issued_30d else 0.0

    # outstanding (unpaid+disputed) — counted at face value, weighted by collection rate
    pending = (
        sb.table("tv_challans")
        .select("amount, status")
        .neq("status", "PAID")
        .execute()
    ).data or []
    pending_amount = sum(r.get("amount") or 0 for r in pending)

    # next-30d projection: extrapolate issuance rate × collection rate
    daily_rate = issued_amount / 30 if issued_amount else 0
    projected_new = daily_rate * days
    projected_collection_from_new = projected_new * collection_rate
    # Plus recovery from current pending (assume ~half the unpaid get paid in window)
    projected_collection_from_pending = pending_amount * collection_rate * 0.5

    return {
        "days": days,
        "last_30d_issued_amount": issued_amount,
        "last_30d_paid_amount": paid_amount,
        "collection_rate": round(collection_rate * 100, 1),
        "pending_amount": pending_amount,
        "projected_new_amount": int(projected_new),
        "projected_collection_new": int(projected_collection_from_new),
        "projected_collection_pending": int(projected_collection_from_pending),
        "projected_total_collection": int(projected_collection_from_new + projected_collection_from_pending),
    }


# ============================================================
# Phase 1+ — Court Evidence Pack (per-incident bundle metadata)
# Phase 2 produces the actual zip with clips/frames. For now we return the
# manifest that the eventual zip will contain — court-grade audit trail.
# ============================================================

def court_pack_manifest(inc_id: str) -> dict[str, Any]:
    sb = get_supabase()
    inc = (sb.table("tv_incidents").select("*").eq("inc_id", inc_id).execute()).data or []
    if not inc:
        return {"found": False, "inc_id": inc_id}
    incident = inc[0]

    audit = (
        sb.table("tv_audit_log")
        .select("*")
        .eq("entity_type", "incident")
        .eq("entity_id", inc_id)
        .order("ts", desc=False)
        .execute()
    ).data or []

    # Cross-reference: any challans issued for this incident
    challans = (
        sb.table("tv_challans")
        .select("*")
        .eq("incident_id", incident.get("id"))
        .execute()
    ).data or []

    return {
        "found": True,
        "inc_id": inc_id,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "incident": _shape_incident(incident),
        "evidence": {
            "video_clip": incident.get("video_clip_path"),
            "full_video": incident.get("full_video_path"),
            "frame_metadata": incident.get("frame_metadata"),
        },
        "challans": [_shape_challan(c) for c in challans],
        "audit_trail": [
            {
                "ts": a.get("ts"),
                "action": a.get("action"),
                "actor": a.get("actor"),
                "payload": a.get("payload"),
            }
            for a in audit
        ],
        "trail_length": len(audit),
        "ready_for_export": bool(incident.get("video_clip_path")),
    }


# ============================================================
# Phase 2 — Upload pipeline orchestration
# In-memory job tracker (single-process backend; Phase 6 will move to DB if
# we move to multi-worker deployment).
# ============================================================

import threading
import time
import uuid
from pathlib import Path

_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}

UPLOADS_DIR = Path(os.getenv("TV_UPLOADS_DIR", ".tv_uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR = Path(os.getenv("TV_CLIPS_DIR", ".tv_clips"))
CLIPS_DIR.mkdir(parents=True, exist_ok=True)


def create_job(filename: str, file_bytes: bytes, cam_id: Optional[str], types: str) -> str:
    """Save the upload to disk, register a job. Returns job_id."""
    job_id = uuid.uuid4().hex[:12]
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")[:80] or "upload.mp4"
    local_path = UPLOADS_DIR / f"{job_id}_{safe_name}"
    local_path.write_bytes(file_bytes)
    types_set = {t.strip().lower() for t in (types or "").split(",") if t.strip()}
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "filename": filename,
            "size_bytes": len(file_bytes),
            "cam_id": cam_id,
            "types_filter": list(types_set),
            "status": "queued",
            "frames_processed": 0,
            "total_frames": 0,
            "detection_count": 0,
            "incident_ids": [],
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
            "_local_path": str(local_path),
            "_types_set": types_set,
        }
    return job_id


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return None
        # public view — strip internal underscored keys
        return {k: v for k, v in j.items() if not k.startswith("_")}


def _update_job(job_id: str, **fields):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return
        j.update(fields)


def _next_human_inc_id() -> str:
    """Atomic increment via the `tv_next_id` Postgres function we shipped."""
    sb = get_supabase()
    try:
        r = sb.rpc("tv_next_id", {"p_scope": "incident", "p_prefix": "INC"}).execute()
        return r.data if isinstance(r.data, str) else f"INC-{int(time.time())}"
    except Exception as e:
        log.warning("tv_next_id RPC failed (%s) — falling back to timestamp id", e)
        return f"INC-{int(time.time())}"


def process_upload(job_id: str) -> None:
    """
    Background task: run pipeline on the uploaded video, extract clips,
    insert tv_incidents rows. Updates job state throughout.
    """
    # Lazy import — pipeline imports heavy ML libs we don't want at module load.
    from app.modules.traffic_violations import pipeline, clip_extractor, storage

    sb = get_supabase()
    job = None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = "processing"
        job["started_at"] = datetime.now(timezone.utc).isoformat()

    local_path = job["_local_path"]
    types_set = job["_types_set"]
    cam_id = job.get("cam_id")

    try:
        def _progress(done: int, total: int):
            _update_job(job_id, frames_processed=done, total_frames=total)

        result = pipeline.detect_in_video(
            video_path=local_path,
            cam_id=cam_id,
            types_filter=types_set or None,
            frame_skip=6,
            progress_cb=_progress,
        )

        fps = result["fps"] or 25.0
        detections = result["detections"]
        incident_ids: list[str] = []

        for det in detections:
            inc_id = _next_human_inc_id()
            center_sec = (det.get("best_frame_idx") or 0) / fps

            # Extract 3s clip → upload to Supabase Storage
            clip_local = str(CLIPS_DIR / f"{inc_id}.mp4")
            extracted = clip_extractor.extract_clip(
                src_video=local_path,
                center_seconds=center_sec,
                out_path=clip_local,
                duration=3.0,
            )
            clip_url = None
            if extracted:
                clip_url = storage.upload_local_file(extracted, dest_path=f"clips/{inc_id}.mp4")

            row = {
                "inc_id": inc_id,
                "cam_id": cam_id,
                "upload_filename": job.get("filename"),
                "video_clip_path": clip_url,
                "full_video_path": None,
                "violation_type": det["violation_type"],
                "severity": det["severity"],
                "plate": det.get("plate") or None,
                "plate_confidence": det.get("plate_confidence") or None,
                "detection_confidence": det["detection_confidence"],
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "status": "PENDING_REVIEW",
                "frame_metadata": {
                    "track_id": det.get("track_id"),
                    "best_frame_idx": det.get("best_frame_idx"),
                    "best_bbox": det.get("best_bbox"),
                    "first_seen": det.get("first_seen"),
                    "last_seen": det.get("last_seen"),
                    "source_filename": job.get("filename"),
                },
                "duration_seconds": 3.0,
            }
            try:
                ins = sb.table("tv_incidents").insert(row).execute()
                incident_ids.append(inc_id)
                # Best-effort audit
                try:
                    sb.table("tv_audit_log").insert({
                        "entity_type": "incident",
                        "entity_id": inc_id,
                        "action": "detected",
                        "actor": "pipeline",
                        "payload": {
                            "job_id": job_id,
                            "track_id": det.get("track_id"),
                            "detection_confidence": det["detection_confidence"],
                        },
                    }).execute()
                except Exception:
                    pass
            except Exception as e:
                log.warning("incident insert failed for %s: %s", inc_id, e)

        _update_job(
            job_id,
            status="complete",
            detection_count=len(incident_ids),
            incident_ids=incident_ids,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        log.exception("process_upload failed for job %s", job_id)
        _update_job(
            job_id,
            status="error",
            error=str(e),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )


# ============================================================
# Phase 3 — Approve / Reject incidents (with Telegram challan delivery)
# ============================================================

def _next_human_challan_id() -> str:
    sb = get_supabase()
    try:
        r = sb.rpc("tv_next_id", {"p_scope": "challan", "p_prefix": "CH"}).execute()
        return r.data if isinstance(r.data, str) else f"CH-{int(time.time())}"
    except Exception as e:
        log.warning("tv_next_id RPC failed (%s) — timestamp fallback", e)
        return f"CH-{int(time.time())}"


def _fine_amount_for(violation_type: str) -> int:
    sb = get_supabase()
    try:
        r = (
            sb.table("govt_fines_penalties")
            .select("fine_amount, legal_section")
            .eq("violation_type", violation_type)
            .limit(1)
            .execute()
        ).data or []
        if r:
            return int(r[0].get("fine_amount") or 0)
    except Exception as e:
        log.warning("fine lookup failed for %s: %s", violation_type, e)
    return 1000  # safe default


def _legal_section_for(violation_type: str) -> Optional[str]:
    sb = get_supabase()
    try:
        r = (
            sb.table("govt_fines_penalties")
            .select("legal_section")
            .eq("violation_type", violation_type)
            .limit(1)
            .execute()
        ).data or []
        if r:
            return r[0].get("legal_section")
    except Exception:
        pass
    return None


def _driver_for(plate: str) -> dict[str, Any]:
    sb = get_supabase()
    try:
        r = (
            sb.table("tv_drivers")
            .select("plate, driver_name, telegram_chat_id")
            .eq("plate", plate)
            .limit(1)
            .execute()
        ).data or []
        if r:
            return r[0]
    except Exception:
        pass
    return {}


def approve_incident(inc_id: str, actor: str = "rsd") -> dict[str, Any]:
    """
    Approve a pending incident:
      1) Mark tv_incidents.status = APPROVED + approved_at/approved_by
      2) Insert tv_challans row (with computed amount + 30-day due-by)
      3) Send Telegram challan to the driver (pay yes/no buttons)
      4) Persist telegram_message_id on the challan row
      5) Audit trail: 'approved' on incident, 'challan_issued' on challan,
         'telegram_sent' (or 'telegram_failed') on challan.
    Idempotent: re-approving an already-approved incident is a no-op.
    """
    from app.modules.traffic_violations import telegram as tg

    sb = get_supabase()
    inc_rows = (
        sb.table("tv_incidents").select("*").eq("inc_id", inc_id).limit(1).execute()
    ).data or []
    if not inc_rows:
        raise ValueError(f"Incident {inc_id} not found")
    inc = inc_rows[0]
    if (inc.get("status") or "").upper() == "APPROVED":
        # idempotent re-approve — return existing challan if any
        existing = (
            sb.table("tv_challans")
            .select("*")
            .eq("incident_id", inc.get("id"))
            .limit(1)
            .execute()
        ).data or []
        return {
            "incident": _shape_incident(inc),
            "challan": (_shape_challan(existing[0]) if existing else None),
            "telegram_message_id": (existing[0].get("telegram_message_id") if existing else None),
            "status": "already_approved",
        }

    now = datetime.now(timezone.utc)
    sb.table("tv_incidents").update({
        "status": "APPROVED",
        "approved_at": now.isoformat(),
        "approved_by": actor,
    }).eq("inc_id", inc_id).execute()

    violation_type = inc.get("violation_type") or "speeding"
    amount = _fine_amount_for(violation_type)
    legal_section = _legal_section_for(violation_type)
    challan_id = _next_human_challan_id()
    due_by = (now + timedelta(days=30)).isoformat()
    # tv_challans.plate is NOT NULL — Groq-detected accidents may have no plate
    # visible. Fall back to UNKNOWN-{inc_id} so the officer can edit it later.
    plate = inc.get("plate") or f"UNKNOWN-{inc_id}"
    driver = _driver_for(plate)

    challan_row = {
        "challan_id": challan_id,
        "incident_id": inc.get("id"),
        "plate": plate,
        "driver_name": driver.get("driver_name"),
        "driver_chat_id": driver.get("telegram_chat_id"),
        "offense": VIOLATION_LABEL.get(violation_type, violation_type.upper()),
        "violation_type": violation_type,
        "amount": amount,
        "status": "UNPAID",
        "issued_at": now.isoformat(),
        "due_by": due_by,
    }
    inserted = sb.table("tv_challans").insert(challan_row).execute().data
    challan_pk = inserted[0]["id"] if inserted else None

    # audit: approval + challan issuance
    for entry in [
        {"entity_type": "incident", "entity_id": inc_id, "action": "approved",
         "actor": actor, "payload": {"violation_type": violation_type, "amount": amount, "challan_id": challan_id}},
        {"entity_type": "challan", "entity_id": challan_id, "action": "challan_issued",
         "actor": actor, "payload": {"plate": inc.get("plate"), "amount": amount, "incident_id": inc_id}},
    ]:
        try:
            sb.table("tv_audit_log").insert(entry).execute()
        except Exception:
            pass

    # Telegram delivery
    telegram_message_id = None
    telegram_error = None
    # Prefer the annotated evidence JPG (bbox + violator marker) as the photo.
    evidence_jpg_path = None
    try:
        candidate = CLIPS_DIR / f"{inc_id}.jpg"
        if candidate.exists() and candidate.stat().st_size > 0:
            evidence_jpg_path = str(candidate)
    except Exception:
        evidence_jpg_path = None
    # Evidence URL fall-back for the "View full evidence clip" link (slideshow mp4)
    evidence_url = inc.get("video_clip_path")
    # Best human-readable location: prefer the camera name, fall back to lat/lng
    inc_meta = inc.get("frame_metadata") or {}
    cam_name = None
    try:
        cam_row = (
            sb.table("tv_cameras").select("name").eq("id", inc.get("cam_id")).limit(1).execute()
        ).data or []
        if cam_row:
            cam_name = cam_row[0].get("name")
    except Exception:
        pass
    loc_str = cam_name
    if not loc_str and isinstance(inc_meta, dict) and inc_meta.get("lat") and inc_meta.get("lng"):
        loc_str = f"{inc_meta['lat']:.4f}, {inc_meta['lng']:.4f}"
    try:
        msg = tg.send_challan(
            chat_id=driver.get("telegram_chat_id"),
            challan_id=challan_id,
            plate=plate,
            offense_label=VIOLATION_LABEL.get(violation_type, violation_type.upper()),
            amount=amount,
            due_by=due_by[:10],
            legal_section=legal_section,
            evidence_url=evidence_url,
            photo_path=evidence_jpg_path,
            severity=(inc.get("severity") or "medium").upper(),
            issued_at=now.isoformat(),
            cam_id=inc.get("cam_id"),
            location=loc_str,
            description=(inc_meta.get("description") if isinstance(inc_meta, dict) else None),
        )
        if msg:
            telegram_message_id = str(msg.get("message_id") or "")
            if challan_pk and telegram_message_id:
                sb.table("tv_challans").update(
                    {"telegram_message_id": telegram_message_id}
                ).eq("id", challan_pk).execute()
            try:
                sb.table("tv_audit_log").insert({
                    "entity_type": "challan", "entity_id": challan_id, "action": "telegram_sent",
                    "actor": actor,
                    "payload": {"message_id": telegram_message_id, "chat_id": driver.get("telegram_chat_id") or "default"},
                }).execute()
            except Exception:
                pass
    except Exception as e:
        telegram_error = str(e)
        log.warning("Telegram send failed for %s: %s", challan_id, e)
        try:
            sb.table("tv_audit_log").insert({
                "entity_type": "challan", "entity_id": challan_id, "action": "telegram_failed",
                "actor": actor, "payload": {"error": telegram_error},
            }).execute()
        except Exception:
            pass

    return {
        "incident": _shape_incident({**inc, "status": "APPROVED", "approved_at": now.isoformat(), "approved_by": actor}),
        "challan": _shape_challan(challan_row),
        "telegram_message_id": telegram_message_id,
        "telegram_error": telegram_error,
        "status": "approved",
    }


def reject_incident(inc_id: str, actor: str = "rsd", reason: str = "") -> dict[str, Any]:
    """Mark incident as REJECTED + audit. No Telegram message sent."""
    sb = get_supabase()
    inc_rows = (
        sb.table("tv_incidents").select("*").eq("inc_id", inc_id).limit(1).execute()
    ).data or []
    if not inc_rows:
        raise ValueError(f"Incident {inc_id} not found")
    inc = inc_rows[0]
    if (inc.get("status") or "").upper() == "REJECTED":
        return {"incident": _shape_incident(inc), "status": "already_rejected"}

    now = datetime.now(timezone.utc).isoformat()
    update: dict[str, Any] = {"status": "REJECTED", "rejected_at": now, "rejected_by": actor}
    if reason:
        update["reject_reason"] = reason
    sb.table("tv_incidents").update(update).eq("inc_id", inc_id).execute()

    try:
        sb.table("tv_audit_log").insert({
            "entity_type": "incident", "entity_id": inc_id, "action": "rejected",
            "actor": actor, "payload": {"reason": reason or None},
        }).execute()
    except Exception:
        pass

    return {
        "incident": _shape_incident({**inc, "status": "REJECTED", "rejected_at": now, "rejected_by": actor, "reject_reason": reason}),
        "status": "rejected",
    }


# ============================================================
# Phase 4 — Telegram pay yes/no callback handler
# Wired via webhook (POST /api/traffic-violations/telegram/webhook).
# ============================================================

def mark_challan_status(
    challan_id: str,
    new_status: str,
    reason: str = "",
    actor: str = "rsd",
) -> dict[str, Any]:
    """
    Manually flip a challan to PAID / DISPUTED / UNPAID.
    Used by the Challans tab buttons (Phase 4) when no Telegram webhook is wired.
    """
    sb = get_supabase()
    rows = (
        sb.table("tv_challans").select("*").eq("challan_id", challan_id).limit(1).execute()
    ).data or []
    if not rows:
        raise ValueError(f"Challan {challan_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    update: dict[str, Any] = {"status": new_status}
    if new_status == "PAID":
        update["paid_at"] = now
    elif new_status == "DISPUTED":
        update["disputed_at"] = now
        if reason:
            update["dispute_reason"] = reason
    sb.table("tv_challans").update(update).eq("challan_id", challan_id).execute()

    try:
        sb.table("tv_audit_log").insert({
            "entity_type": "challan", "entity_id": challan_id,
            "action": new_status.lower(),
            "actor": actor,
            "payload": {"via": "manual_ui", "reason": reason or None},
        }).execute()
    except Exception:
        pass

    return {"challan_id": challan_id, "new_status": new_status, "via": "manual_ui"}


def handle_telegram_callback(callback_query: dict[str, Any]) -> dict[str, Any]:
    """
    Process a Telegram inline-keyboard click on a challan message.
    callback_data = "pay:CH-7823:yes" | "pay:CH-7823:no"
    """
    from app.modules.traffic_violations import telegram as tg

    sb = get_supabase()
    cb_id = callback_query.get("id")
    data = (callback_query.get("data") or "").strip()
    parsed = tg.parse_pay_callback(data)
    if not parsed:
        tg.answer_callback(cb_id, "Invalid action")
        return {"ok": False, "error": "invalid_callback_data"}

    challan_id, will_pay = parsed
    actor = callback_query.get("from", {}).get("username") or f"tg:{callback_query.get('from', {}).get('id')}"

    new_status = "PAID" if will_pay else "DISPUTED"
    ts_col = "paid_at" if will_pay else "disputed_at"

    update: dict[str, Any] = {"status": new_status, ts_col: datetime.now(timezone.utc).isoformat()}
    if not will_pay:
        update["dispute_reason"] = "Driver disputed via Telegram"

    res = sb.table("tv_challans").update(update).eq("challan_id", challan_id).execute()
    updated = bool(res.data)

    try:
        sb.table("tv_audit_log").insert({
            "entity_type": "challan", "entity_id": challan_id,
            "action": "paid" if will_pay else "disputed",
            "actor": actor, "payload": {"via": "telegram_inline_button"},
        }).execute()
    except Exception:
        pass

    ack_text = "✅ Payment recorded. Thank you." if will_pay else "⚠️ Dispute logged. Officer will review."
    tg.answer_callback(cb_id, ack_text)
    return {"ok": True, "challan_id": challan_id, "new_status": new_status, "updated": updated}


def bulk_action_incidents(
    ids: list[str],
    action: str,
    actor: str = "system",
    reason: str = "",
) -> dict[str, Any]:
    """
    Phase 3 update: bulk approve routes each id through approve_incident()
    (creates real challans + sends Telegram). Reject takes the lightweight path.
    """
    act = (action or "").upper()
    if act not in ("APPROVE", "REJECT"):
        raise ValueError(f"Invalid action: {action!r} (expected approve|reject)")
    if not ids:
        return {"action": act, "updated": 0, "ids": [], "challan_ids": []}

    updated_ids: list[str] = []
    challan_ids: list[str] = []
    telegram_failures: list[dict[str, Any]] = []

    if act == "APPROVE":
        for inc_id in ids:
            try:
                result = approve_incident(inc_id, actor=actor)
                updated_ids.append(inc_id)
                ch = result.get("challan") or {}
                if ch.get("id"):
                    challan_ids.append(ch["id"])
                if result.get("telegram_error"):
                    telegram_failures.append({"inc_id": inc_id, "error": result["telegram_error"]})
            except Exception as e:
                log.warning("approve in bulk failed for %s: %s", inc_id, e)
        return {
            "action": "APPROVED",
            "updated": len(updated_ids),
            "ids": updated_ids,
            "challan_ids": challan_ids,
            "telegram_failures": telegram_failures,
        }

    # REJECT — lightweight, no Telegram
    for inc_id in ids:
        try:
            reject_incident(inc_id, actor=actor, reason=reason)
            updated_ids.append(inc_id)
        except Exception as e:
            log.warning("reject in bulk failed for %s: %s", inc_id, e)
    return {
        "action": "REJECTED",
        "updated": len(updated_ids),
        "ids": updated_ids,
        "challan_ids": [],
    }
