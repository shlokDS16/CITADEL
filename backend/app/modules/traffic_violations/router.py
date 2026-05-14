"""
Traffic Violations — HTTP endpoints.
URL prefix: /api (mounted in app/main.py)

  GET    /api/v1/traffic-violations/health

  Live Feed tab
  GET    /api/traffic-violations/cameras           ?gateway=...&status=...
  GET    /api/traffic-violations/header-stats      counts for the subtitle

  Incidents tab
  GET    /api/traffic-violations/incidents         ?type=...&severity=...&status=...&limit=...

  Challans tab
  GET    /api/traffic-violations/challans          ?status=...&limit=...
  GET    /api/traffic-violations/challans/kpis     4 KPI cards (issued_30d, total_collected, collection_rate, disputed_pct)

  Repeat Offenders tab
  GET    /api/traffic-violations/offenders/top     ?days=90&limit=5

  Analytics tab
  GET    /api/traffic-violations/analytics/summary 4 KPI cards (detections_24h, avg_conf, fp_pct, uptime_pct)

  Fines lookup
  GET    /api/traffic-violations/fines             govt_fines_penalties contents
"""
from __future__ import annotations

import logging
from typing import Optional

from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.modules.traffic_violations import schemas, service

log = logging.getLogger("citadel.traffic_violations.router")
router = APIRouter()


# ============================================================
# Health
# ============================================================
@router.get("/v1/traffic-violations/health", tags=["traffic-violations"])
async def health() -> dict:
    return {"status": "ok", "module": "traffic_violations"}


# ============================================================
# Live Feed
# ============================================================
@router.get("/traffic-violations/cameras", response_model=schemas.CameraList, tags=["traffic-violations"])
async def list_cameras(
    gateway: Optional[str] = None,
    status: Optional[str] = None,
):
    try:
        rows = service.list_cameras(gateway=gateway, status=status)
        return {"total": len(rows), "cameras": rows}
    except Exception as e:
        log.exception("list_cameras failed")
        raise HTTPException(status_code=500, detail=f"Camera list failed: {e}")


@router.get("/traffic-violations/header-stats", response_model=schemas.HeaderStats, tags=["traffic-violations"])
async def header_stats():
    try:
        return service.header_stats()
    except Exception as e:
        log.exception("header_stats failed")
        raise HTTPException(status_code=500, detail=f"Header stats failed: {e}")


# ============================================================
# Incidents
# ============================================================
@router.get("/traffic-violations/incidents", response_model=schemas.IncidentList, tags=["traffic-violations"])
async def list_incidents(
    type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    try:
        rows = service.list_incidents(type_=type, severity=severity, status=status, limit=limit)
        return {"total": len(rows), "incidents": rows}
    except Exception as e:
        log.exception("list_incidents failed")
        raise HTTPException(status_code=500, detail=f"Incidents list failed: {e}")


# ============================================================
# Challans
# ============================================================
@router.get("/traffic-violations/challans", response_model=schemas.ChallanList, tags=["traffic-violations"])
async def list_challans(
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    try:
        rows = service.list_challans(status=status, limit=limit)
        return {"total": len(rows), "challans": rows}
    except Exception as e:
        log.exception("list_challans failed")
        raise HTTPException(status_code=500, detail=f"Challans list failed: {e}")


@router.get("/traffic-violations/challans/kpis", response_model=schemas.ChallanKPIs, tags=["traffic-violations"])
async def challan_kpis():
    try:
        return service.challan_kpis()
    except Exception as e:
        log.exception("challan_kpis failed")
        raise HTTPException(status_code=500, detail=f"Challan KPIs failed: {e}")


# ============================================================
# Repeat Offenders
# ============================================================
@router.get("/traffic-violations/offenders/top", response_model=schemas.OffenderList, tags=["traffic-violations"])
async def top_offenders(
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(5, ge=1, le=20),
):
    try:
        rows = service.top_offenders(days=days, limit=limit)
        return {"total": len(rows), "offenders": rows}
    except Exception as e:
        log.exception("top_offenders failed")
        raise HTTPException(status_code=500, detail=f"Top offenders failed: {e}")


@router.get(
    "/traffic-violations/offenders/{plate}/timeline",
    response_model=schemas.OffenderTimeline,
    tags=["traffic-violations"],
)
async def offender_timeline(plate: str):
    try:
        return service.offender_timeline(plate)
    except Exception as e:
        log.exception("offender_timeline failed")
        raise HTTPException(status_code=500, detail=f"Timeline failed: {e}")


@router.post(
    "/traffic-violations/offenders/{plate}/notify",
    response_model=schemas.NotifyResult,
    tags=["traffic-violations"],
)
async def notify_offender(plate: str, body: Optional[schemas.NotifyRequest] = None):
    try:
        actor = (body.actor if body else "rsd") or "rsd"
        return service.notify_offender(plate, actor=actor)
    except Exception as e:
        log.exception("notify_offender failed")
        raise HTTPException(status_code=500, detail=f"Notify failed: {e}")


# ============================================================
# Analytics
# ============================================================
@router.get("/traffic-violations/analytics/summary", response_model=schemas.AnalyticsSummary, tags=["traffic-violations"])
async def analytics_summary():
    try:
        return service.analytics_summary()
    except Exception as e:
        log.exception("analytics_summary failed")
        raise HTTPException(status_code=500, detail=f"Analytics summary failed: {e}")


# ============================================================
# Fines (lookup)
# ============================================================
@router.get("/traffic-violations/fines", response_model=list[schemas.FineRow], tags=["traffic-violations"])
async def list_fines():
    try:
        return service.list_fines()
    except Exception as e:
        log.exception("list_fines failed")
        raise HTTPException(status_code=500, detail=f"Fines lookup failed: {e}")


# ============================================================
# Phase 1+ — Camera Health Strip (Live Feed top)
# ============================================================
@router.get("/traffic-violations/camera-health", response_model=schemas.CameraHealth, tags=["traffic-violations"])
async def camera_health():
    try:
        return service.camera_health()
    except Exception as e:
        log.exception("camera_health failed")
        raise HTTPException(status_code=500, detail=f"Camera health failed: {e}")


# ============================================================
# Phase 1+ — System Status Bar (module-level)
# ============================================================
@router.get("/traffic-violations/system-status", response_model=schemas.SystemStatus, tags=["traffic-violations"])
async def system_status():
    try:
        return service.system_status()
    except Exception as e:
        log.exception("system_status failed")
        raise HTTPException(status_code=500, detail=f"System status failed: {e}")


# ============================================================
# Phase 2+ — Live traffic snapshots from Singapore data.gov.sg
# ============================================================
@router.get("/traffic-violations/snapshots", response_model=schemas.SnapshotMap, tags=["traffic-violations"])
async def live_snapshots():
    try:
        return service.live_snapshots()
    except Exception as e:
        log.exception("live_snapshots failed")
        raise HTTPException(status_code=500, detail=f"Snapshots failed: {e}")


# ============================================================
# Phase 3+ — YOLO detections on the snapshots (overlay bboxes)
# ============================================================
@router.get("/traffic-violations/snapshots/detect", response_model=schemas.DetectionMap, tags=["traffic-violations"])
async def snapshots_detect():
    try:
        return service.detect_snapshots()
    except Exception as e:
        log.exception("snapshots_detect failed")
        raise HTTPException(status_code=500, detail=f"Snapshot detection failed: {e}")


# ============================================================
# Phase 3+++ — Loop video + per-frame YOLO tracks (continuous motion)
# Files live under backend/.tv_camera_loops/{loop_id}.mp4 + .tracks.json
# ============================================================

def _loop_file(loop_id: str, kind: str) -> Path:
    """Resolve to the actual file; raise 404 if missing."""
    # sanitize: alphanumeric + dash/underscore only
    safe = "".join(c for c in loop_id if c.isalnum() or c in "-_")
    if safe != loop_id:
        raise HTTPException(status_code=400, detail="Invalid loop_id")
    ext = "mp4" if kind == "video" else "tracks.json"
    p = service.LOOPS_DIR / f"{safe}.{ext}"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Loop {loop_id}.{ext} not found")
    return p


@router.get("/traffic-violations/loops/{loop_id}/video.mp4", tags=["traffic-violations"])
async def loop_video(loop_id: str):
    p = _loop_file(loop_id, "video")
    return FileResponse(str(p), media_type="video/mp4")


@router.get("/traffic-violations/loops/{loop_id}/tracks.json", tags=["traffic-violations"])
async def loop_tracks(loop_id: str):
    p = _loop_file(loop_id, "tracks")
    return FileResponse(str(p), media_type="application/json")


# ============================================================
# Phase 3++++++ — Serve incident clips directly from local cache
# (Supabase Storage uploads can flake on h264 codec issues; the local
#  `.tv_clips/{inc_id}.mp4` is the authoritative copy.)
# ============================================================
@router.get("/traffic-violations/incidents/{inc_id}/clip.mp4", tags=["traffic-violations"])
async def incident_clip(inc_id: str):
    # sanitise inc_id (alphanumeric + dash only)
    safe = "".join(c for c in inc_id if c.isalnum() or c == "-")
    if safe != inc_id:
        raise HTTPException(status_code=400, detail="Invalid inc_id")
    p = service.CLIPS_DIR / f"{safe}.mp4"
    if not p.exists():
        # fall back to the Supabase Storage URL if any
        from app.database import get_supabase
        row = (
            get_supabase().table("tv_incidents")
            .select("video_clip_path").eq("inc_id", safe).limit(1).execute()
        ).data or []
        if row and row[0].get("video_clip_path"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=row[0]["video_clip_path"], status_code=307)
        raise HTTPException(status_code=404, detail=f"Clip for {inc_id} not found")
    return FileResponse(str(p), media_type="video/mp4")


# Phase A.1 — Live-pipeline incidents save a JPG snapshot (not video).
# Frontend calls this first; if it 404s, it falls back to /clip.mp4.
@router.get("/traffic-violations/incidents/{inc_id}/evidence.jpg", tags=["traffic-violations"])
async def incident_evidence_jpg(inc_id: str):
    safe = "".join(c for c in inc_id if c.isalnum() or c == "-")
    if safe != inc_id:
        raise HTTPException(status_code=400, detail="Invalid inc_id")
    p = service.CLIPS_DIR / f"{safe}.jpg"
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Evidence image for {inc_id} not found")
    return FileResponse(str(p), media_type="image/jpeg")


# ============================================================
# Phase 4 — Manual mark-paid / mark-disputed (no Telegram webhook needed)
# ============================================================
@router.post("/traffic-violations/challans/{challan_id}/mark-status", tags=["traffic-violations"])
async def mark_challan_status(challan_id: str, body: dict):
    new_status = (body.get("status") or "").upper()
    reason = body.get("reason") or ""
    actor = body.get("actor") or "rsd"
    if new_status not in ("PAID", "DISPUTED", "UNPAID"):
        raise HTTPException(status_code=400, detail="status must be PAID | DISPUTED | UNPAID")
    try:
        return service.mark_challan_status(challan_id, new_status, reason=reason, actor=actor)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        log.exception("mark_challan_status failed")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Phase 1+ — Plate lookup (Incidents tab search)
# ============================================================
@router.get("/traffic-violations/plates/{plate}", response_model=schemas.PlateHistory, tags=["traffic-violations"])
async def plate_history(plate: str):
    try:
        return service.plate_history(plate)
    except Exception as e:
        log.exception("plate_history failed")
        raise HTTPException(status_code=500, detail=f"Plate history failed: {e}")


# ============================================================
# Phase 1+ — Bulk action on incidents
# ============================================================
@router.post("/traffic-violations/incidents/bulk-action", response_model=schemas.BulkActionResponse, tags=["traffic-violations"])
async def bulk_action(req: schemas.BulkActionRequest):
    try:
        return service.bulk_action_incidents(
            ids=req.ids, action=req.action, actor=req.actor or "rsd", reason=req.reason or ""
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        log.exception("bulk_action failed")
        raise HTTPException(status_code=500, detail=f"Bulk action failed: {e}")


# ============================================================
# Phase 1+ — Challan SLA queue
# ============================================================
@router.get("/traffic-violations/challans/sla", response_model=schemas.SLAReport, tags=["traffic-violations"])
async def challan_sla(window_days: int = Query(7, ge=1, le=60)):
    try:
        return service.challan_sla(window_days=window_days)
    except Exception as e:
        log.exception("challan_sla failed")
        raise HTTPException(status_code=500, detail=f"SLA queue failed: {e}")


# ============================================================
# Phase 1+ — Revenue forecast
# ============================================================
@router.get("/traffic-violations/analytics/revenue-forecast", response_model=schemas.RevenueForecast, tags=["traffic-violations"])
async def revenue_forecast(days: int = Query(30, ge=1, le=180)):
    try:
        return service.revenue_forecast(days=days)
    except Exception as e:
        log.exception("revenue_forecast failed")
        raise HTTPException(status_code=500, detail=f"Revenue forecast failed: {e}")


# ============================================================
# Phase 1+ — Court evidence pack manifest
# (Returns the JSON manifest. Phase 2 will add a zip-download companion.)
# ============================================================
@router.get("/traffic-violations/incidents/{inc_id}/court-pack", response_model=schemas.CourtPackManifest, tags=["traffic-violations"])
async def court_pack(inc_id: str):
    try:
        return service.court_pack_manifest(inc_id)
    except Exception as e:
        log.exception("court_pack failed")
        raise HTTPException(status_code=500, detail=f"Court pack failed: {e}")


# ============================================================
# Phase 2 — Upload video → background pipeline → tv_incidents
# ============================================================
@router.post("/traffic-violations/upload", response_model=schemas.UploadJobAck, tags=["traffic-violations"])
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    cam_id: Optional[str] = Form(None),
    types: str = Form("no_helmet,speeding,illegal_parking"),
):
    """
    Accept an uploaded video, kick off the YOLO+DeepSORT pipeline as a
    background task. Returns a job_id the client polls for progress.
    """
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        # 50 MB hard cap (Supabase Storage bucket limit)
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

        job_id = service.create_job(
            filename=file.filename or "upload.mp4",
            file_bytes=content,
            cam_id=cam_id,
            types=types,
        )
        background_tasks.add_task(service.process_upload, job_id)
        return {
            "job_id": job_id,
            "status": "queued",
            "filename": file.filename,
            "size_bytes": len(content),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("upload_video failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


@router.get("/traffic-violations/jobs/{job_id}", response_model=schemas.UploadJobStatus, tags=["traffic-violations"])
async def get_job_status(job_id: str):
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# ============================================================
# Phase 3 — Approve / Reject single incident + Telegram webhook
# ============================================================
@router.post("/traffic-violations/incidents/{inc_id}/approve", response_model=schemas.ApproveResult, tags=["traffic-violations"])
async def approve_incident(inc_id: str, req: Optional[schemas.ApproveRequest] = None):
    try:
        actor = (req.actor if req else None) or "rsd"
        return service.approve_incident(inc_id, actor=actor)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        log.exception("approve_incident failed")
        raise HTTPException(status_code=500, detail=f"Approve failed: {e}")


@router.post("/traffic-violations/incidents/{inc_id}/reject", response_model=schemas.ApproveResult, tags=["traffic-violations"])
async def reject_incident(inc_id: str, req: Optional[schemas.RejectRequest] = None):
    try:
        actor = (req.actor if req else None) or "rsd"
        reason = (req.reason if req else None) or ""
        return service.reject_incident(inc_id, actor=actor, reason=reason)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        log.exception("reject_incident failed")
        raise HTTPException(status_code=500, detail=f"Reject failed: {e}")


# Phase 4 — Telegram inbound webhook for pay yes/no buttons.
# Point Telegram at this URL via `setWebhook` (needs a public HTTPS host —
# use ngrok / cloudflared during dev). Body is the standard Telegram Update.
@router.post("/traffic-violations/telegram/webhook", tags=["traffic-violations"])
async def telegram_webhook(update: dict):
    try:
        if "callback_query" in update:
            return service.handle_telegram_callback(update["callback_query"])
        # Unsupported update type → just ack
        return {"ok": True, "ignored": True}
    except Exception as e:
        log.exception("telegram_webhook failed")
        # always 200 to Telegram so it doesn't retry forever
        return {"ok": False, "error": str(e)}
