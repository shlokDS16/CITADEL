"""
Resume Screening — HTTP endpoints.
URL prefix: /api  (mounted in main.py)

  GET    /api/v1/resume/health
  POST   /api/resume/jd/parse                      ← upload JD file or text → structured JSON
  GET    /api/resume/jobs
  POST   /api/resume/jobs
  GET    /api/resume/jobs/{job}
  PATCH  /api/resume/jobs/{job}
  DELETE /api/resume/jobs/{job}
  POST   /api/resume/jobs/{job}/rescore
  PUT    /api/resume/jobs/{job}/settings
  POST   /api/resume/jobs/{job}/candidates/upload  ← single + bulk
  GET    /api/resume/candidates
  GET    /api/resume/candidates/{cand}
  POST   /api/resume/candidates/{cand}/move-stage
  POST   /api/resume/candidates/{cand}/reject
  POST   /api/resume/candidates/{cand}/schedule-interview
  POST   /api/resume/candidates/{cand}/note
  POST   /api/resume/candidates/compare
  GET    /api/resume/analytics/{kpis|funnel|sources|diversity|apps-per-week|top-skills|jobs-overview}
  GET    /api/resume/telegram/status
  POST   /api/resume/telegram/discover
  POST   /api/resume/telegram/test                 ← debug: send "Hello from CITADEL" to all chats
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile

from app.modules.resume import comparator, parser as rp, schemas, service
from app.modules.resume import telegram_bot as tg
from app.modules.document_intelligence import extractor as docx_pdf_extractor
from app.modules.document_intelligence import ocr as ocr_mod

log = logging.getLogger("citadel.resume.router")
router = APIRouter()


# ============================================================
# Health
# ============================================================
@router.get("/v1/resume/health", tags=["resume"])
async def health() -> dict:
    return {"status": "ok", "module": "resume_screening"}


# ============================================================
# Job Description parsing
# ============================================================
@router.post("/resume/jd/parse", tags=["jobs"], summary="Parse JD from text or uploaded file → structured JSON")
async def parse_jd(
    text: Annotated[Optional[str], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
):
    raw_text = (text or "").strip()
    if file:
        content = await file.read()
        mime = file.content_type or "application/octet-stream"
        if mime == "application/pdf":
            r = docx_pdf_extractor.extract_pdf_digital(content)
            raw_text = r.text if r.text and len(r.text) >= 30 else ocr_mod.ocr_pdf(content).text
        elif mime in {"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/msword"}:
            raw_text = docx_pdf_extractor.extract_docx(content).text
        elif mime in {"image/jpeg", "image/png"}:
            raw_text = ocr_mod.ocr_image(content).text
        elif mime == "text/plain":
            raw_text = content.decode("utf-8", errors="ignore")
        else:
            raise HTTPException(400, f"Unsupported JD file type: {mime}")
    if not raw_text or len(raw_text) < 20:
        raise HTTPException(400, "JD text too short — provide either `text` field or a non-empty file")
    parsed = rp.parse_jd_text(raw_text)
    return {"raw_text": raw_text, "parsed_jd": parsed}


# ============================================================
# Jobs CRUD
# ============================================================
@router.get("/resume/jobs", tags=["jobs"])
async def list_jobs(status: Optional[str] = None, dept: Optional[str] = None,
                    urgency: Optional[str] = None, q: Optional[str] = None):
    return {"jobs": service.list_jobs(status=status, dept=dept, urgency=urgency, q=q)}


@router.get("/resume/jobs/{job}", tags=["jobs"])
async def get_job(job: str):
    j = service.get_job(job)
    if not j: raise HTTPException(404, "job not found")
    return j


@router.post("/resume/jobs", tags=["jobs"], summary="Create a new job (with optional JD parsing)")
async def create_job(payload: schemas.JobCreateRequest):
    try:
        return service.create_job(payload.model_dump())
    except Exception as e:
        log.exception("create_job failed")
        raise HTTPException(500, str(e))


@router.patch("/resume/jobs/{job}", tags=["jobs"])
async def update_job(job: str, payload: schemas.JobUpdateRequest, background_tasks: BackgroundTasks):
    body = {k: v for k, v in payload.model_dump().items() if v is not None}
    res = service.update_job(job, body)
    if not res: raise HTTPException(404, "job not found")
    # If scoring config changed, re-score in background
    if any(k in body for k in ("scoring_weights", "bias_flags", "auto_shortlist_threshold", "parsed_jd")):
        background_tasks.add_task(service.rescore_job, res["id"])
    return res


@router.delete("/resume/jobs/{job}", tags=["jobs"])
async def delete_job(job: str):
    if not service.delete_job(job):
        raise HTTPException(404, "job not found")
    return {"deleted": True}


@router.put("/resume/jobs/{job}/settings", tags=["jobs"])
async def update_settings(job: str, payload: schemas.SettingsUpdateRequest, background_tasks: BackgroundTasks):
    body = {k: v for k, v in payload.model_dump().items() if v is not None}
    res = service.update_job(job, body)
    if not res: raise HTTPException(404, "job not found")
    background_tasks.add_task(service.rescore_job, res["id"])
    return res


@router.post("/resume/jobs/{job}/rescore", tags=["jobs"])
async def rescore(job: str, background_tasks: BackgroundTasks):
    j = service.get_job(job)
    if not j: raise HTTPException(404, "job not found")
    background_tasks.add_task(service.rescore_job, j["id"])
    return {"queued": True, "job": j["code"]}


# ============================================================
# Candidates — upload
# ============================================================
@router.post("/resume/jobs/{job}/candidates/upload", tags=["candidates"])
async def upload_candidates(
    job: str,
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
    source: Annotated[str, Form()] = "Direct",
    uploaded_by: Annotated[str, Form()] = "RSD",
):
    if not files:
        raise HTTPException(400, "No files supplied")
    payloads: list[tuple[bytes, str, str]] = []
    for f in files:
        content = await f.read()
        payloads.append((content, f.filename, f.content_type or "application/octet-stream"))
    try:
        result = service.upload_candidates(job, payloads, source=source, uploaded_by=uploaded_by)
    except LookupError as e:
        raise HTTPException(404, str(e))
    for c in result["candidates"]:
        background_tasks.add_task(service.process_candidate, c["id"])
    return result


# ============================================================
# Candidates — list / detail / actions
# ============================================================
@router.get("/resume/candidates", tags=["candidates"])
async def list_candidates(
    job: Optional[str] = None,
    status: Optional[str] = None,
    min_score: Optional[float] = None,
    q: Optional[str] = None,
    page: int = 1, per_page: int = 50,
):
    return service.list_candidates(job_id_or_code=job, status=status, min_score=min_score,
                                   q=q, page=page, per_page=per_page)


@router.get("/resume/candidates/{cand}", tags=["candidates"])
async def get_candidate(cand: str):
    c = service.get_candidate(cand)
    if not c: raise HTTPException(404, "candidate not found")
    return c


@router.post("/resume/candidates/{cand}/move-stage", tags=["candidates"])
async def move_stage(cand: str, payload: schemas.MoveStageRequest):
    res = service.move_stage(cand, payload.new_status, note=payload.note)
    if not res.get("success"): raise HTTPException(400, res.get("message", "move failed"))
    return res


@router.post("/resume/candidates/{cand}/reject", tags=["candidates"])
async def reject(cand: str, payload: schemas.RejectRequest):
    return service.reject_candidate(
        cand, reason=payload.reason, note=payload.note,
        send_telegram=payload.send_telegram,
        use_ai_cheerup=payload.use_ai_cheerup,
        custom_hint=payload.custom_hint,
    )


@router.post("/resume/candidates/{cand}/schedule-interview", tags=["candidates"])
async def schedule(cand: str, payload: schemas.ScheduleInterviewRequest):
    return service.schedule_interview(
        cand, when=payload.when, prep=payload.prep,
        send_telegram=payload.send_telegram,
    )


@router.post("/resume/candidates/{cand}/note", tags=["candidates"])
async def note(cand: str, payload: schemas.AddNoteRequest):
    return service.add_note(cand, payload.text, author=payload.author or "RSD")


@router.post("/resume/candidates/compare", tags=["candidates"])
async def compare_candidates(payload: schemas.CompareRequest):
    cands: list[dict[str, Any]] = []
    for code in payload.candidate_ids:
        c = service.get_candidate(code)
        if c: cands.append(c)
    if len(cands) < 2:
        raise HTTPException(400, "At least 2 valid candidates required")
    return comparator.compare(cands)


# ============================================================
# Analytics
# ============================================================
@router.get("/resume/analytics/kpis",            tags=["analytics"])
async def a_kpis(period: str = "30d"): return service.analytics_kpis(period)

@router.get("/resume/analytics/funnel",          tags=["analytics"])
async def a_funnel(period: str = "30d"): return service.analytics_funnel(period)

@router.get("/resume/analytics/sources",         tags=["analytics"])
async def a_sources(period: str = "30d"): return service.analytics_sources(period)

@router.get("/resume/analytics/source-quality",  tags=["analytics"])
async def a_source_quality(period: str = "30d"): return service.analytics_source_quality(period)

@router.get("/resume/analytics/diversity",       tags=["analytics"])
async def a_diversity(period: str = "30d"): return service.analytics_diversity(period)

@router.get("/resume/analytics/apps-per-week",   tags=["analytics"])
async def a_apps(weeks: int = 8): return service.analytics_apps_per_week(weeks)

@router.get("/resume/analytics/top-skills",      tags=["analytics"])
async def a_skills(period: str = "30d", limit: int = 10): return service.analytics_top_skills(period, limit)

@router.get("/resume/analytics/jobs-overview",   tags=["analytics"])
async def a_jobs(limit: int = 5): return service.analytics_jobs_overview(limit)


# ============================================================
# Telegram
# ============================================================
@router.get("/resume/telegram/status", tags=["telegram"])
async def telegram_status():
    me = tg.get_me()
    return {
        "bot_ok": me.get("ok", False),
        "bot_username": me.get("username"),
        "bot_first_name": me.get("first_name"),
        "bot_error": me.get("error"),
        "chats": tg.list_chats(),
    }


@router.post("/resume/telegram/discover", tags=["telegram"])
async def telegram_discover():
    return tg.discover_chats()


@router.post("/resume/telegram/test", tags=["telegram"])
async def telegram_test():
    return tg.send_to_all("<b>CITADEL Resume Screening</b>\nThis is a test message — the bot is connected and ready.")
