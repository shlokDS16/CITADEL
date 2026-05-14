"""
Resume Screening service layer — all business logic.

Routers stay thin. Service orchestrates: validate → call extractor/parser/scorer →
write to DB → write audit/pipeline_history → optional Telegram → format response.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from app.config import settings
from app.database import get_supabase
from app.modules.document_intelligence import extractor as docx_pdf_extractor
from app.modules.document_intelligence import ocr as ocr_mod
from app.modules.resume import parser as rp
from app.modules.resume import redactor as rd
from app.modules.resume import scorer as sc
from app.modules.resume import telegram_bot as tg
from app.utils import audit, job_id, storage

log = logging.getLogger("citadel.resume.service")

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "image/jpeg", "image/png",
    "text/plain",
}

CASCADE_PIPELINE_STAGES = ["SHORTLISTED", "INTERVIEW", "OFFER", "RECRUITED"]
TS_FIELD_FOR = {
    "PROCESSING": None,
    "SHORTLISTED": "shortlisted_at",
    "REJECTED": "rejected_at",
    "INTERVIEW": "interview_at",
    "OFFER": "offer_at",
    "RECRUITED": "hired_at",
}


# ============================================================
# JOBS
# ============================================================
def list_jobs(status: Optional[str] = None, dept: Optional[str] = None,
              urgency: Optional[str] = None, q: Optional[str] = None) -> list[dict]:
    supa = get_supabase()
    query = supa.table("jobs").select("*").order("posted_at", desc=True)
    if status:   query = query.eq("status", status)
    if dept:     query = query.eq("department", dept)
    if urgency:  query = query.eq("urgency", urgency.upper())
    if q:        query = query.or_(f"title.ilike.%{q}%,department.ilike.%{q}%,raw_jd_text.ilike.%{q}%")
    rows = query.execute().data or []
    # enrich with candidate counts
    for j in rows:
        _enrich_job_counts(j)
    return rows


def get_job(job_id_or_code: str) -> Optional[dict]:
    supa = get_supabase()
    if str(job_id_or_code).startswith("JOB-"):
        rec = supa.table("jobs").select("*").eq("code", job_id_or_code).limit(1).execute().data
    else:
        rec = supa.table("jobs").select("*").eq("id", job_id_or_code).limit(1).execute().data
    if not rec: return None
    j = rec[0]
    _enrich_job_counts(j)
    return j


def create_job(req: dict) -> dict:
    supa = get_supabase()
    code = job_id.generate_job_code()

    # If raw_jd_text supplied but no parsed_jd, parse with Groq
    parsed_jd = req.get("parsed_jd")
    if not parsed_jd and req.get("raw_jd_text"):
        parsed_jd = rp.parse_jd_text(req["raw_jd_text"])
    parsed_jd = parsed_jd or rp._empty_jd()

    title = req.get("title") or parsed_jd.get("title") or "Untitled Role"
    dept = req.get("department") or parsed_jd.get("department") or "Unassigned"
    urgency = (req.get("urgency") or parsed_jd.get("urgency") or "NORMAL").upper()
    openings = int(req.get("openings") or parsed_jd.get("openings") or 1)

    row = {
        "code": code, "title": title, "department": dept,
        "urgency": urgency, "openings": openings,
        "raw_jd_text": req.get("raw_jd_text"),
        "parsed_jd": parsed_jd,
        "auto_shortlist_threshold": float(req.get("auto_shortlist_threshold") or settings.RESUME_AUTO_SHORTLIST_DEFAULT),
        "posted_by": req.get("posted_by") or "RSD",
    }
    res = supa.table("jobs").insert(row).execute()
    return _enrich_job_counts(res.data[0])


def update_job(job_id_or_code: str, patch: dict) -> Optional[dict]:
    supa = get_supabase()
    rec = get_job(job_id_or_code)
    if not rec: return None
    upd = {k: v for k, v in patch.items() if v is not None}
    if "scoring_weights" in upd and not isinstance(upd["scoring_weights"], dict):
        upd["scoring_weights"] = upd["scoring_weights"].model_dump()
    if "bias_flags" in upd and not isinstance(upd["bias_flags"], dict):
        upd["bias_flags"] = upd["bias_flags"].model_dump()
    supa.table("jobs").update(upd).eq("id", rec["id"]).execute()
    return get_job(rec["id"])


def delete_job(job_id_or_code: str) -> bool:
    supa = get_supabase()
    rec = get_job(job_id_or_code)
    if not rec: return False
    # Cascade-cleanup CV files
    cands = supa.table("candidates").select("id, cv_storage_path").eq("job_id", rec["id"]).execute().data or []
    for c in cands:
        if c.get("cv_storage_path"):
            try:
                storage.delete_object(settings.SUPABASE_BUCKET_RESUMES, c["cv_storage_path"])
            except Exception:
                pass
    supa.table("jobs").delete().eq("id", rec["id"]).execute()
    return True


def _enrich_job_counts(job: dict) -> dict:
    """Add applicant counts to a job row.

    `shortlisted` = HR semantic: "passed AI screening + still in pipeline".
                    Includes anyone currently in SHORTLISTED, INTERVIEW, OFFER, or RECRUITED.
    `currently_shortlisted` = exact: just status='SHORTLISTED' (used by the pipeline-tab mini-stats).
    """
    supa = get_supabase()
    rows = supa.table("candidates").select("status").eq("job_id", job["id"]).execute().data or []
    counts = Counter(r["status"] for r in rows)
    advanced = (counts.get("SHORTLISTED", 0) + counts.get("INTERVIEW", 0)
                + counts.get("OFFER", 0) + counts.get("RECRUITED", 0))
    job["applicants"] = sum(counts.values())
    job["shortlisted"] = advanced                                  # passed-screening count
    job["currently_shortlisted"] = counts.get("SHORTLISTED", 0)    # exact-stage count
    job["processing"] = counts.get("PROCESSING", 0)
    job["interviewing"] = counts.get("INTERVIEW", 0)
    job["offered"] = counts.get("OFFER", 0)
    job["recruited"] = counts.get("RECRUITED", 0)
    job["rejected"] = counts.get("REJECTED", 0)
    posted = job.get("posted_at")
    if posted:
        try:
            posted_dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
            job["days_open"] = max(0, (datetime.now(timezone.utc) - posted_dt).days)
        except Exception:
            job["days_open"] = 0
    else:
        job["days_open"] = 0
    return job


# ============================================================
# CANDIDATES — upload + processing
# ============================================================
def upload_candidates(
    job_id_or_code: str,
    files: list[tuple[bytes, str, str]],   # (content, filename, mime)
    source: str = "Direct",
    uploaded_by: str = "RSD",
) -> dict:
    job = get_job(job_id_or_code)
    if not job:
        raise LookupError(f"Job not found: {job_id_or_code}")

    supa = get_supabase()
    batch_id = str(uuid4())
    created = []

    for content, filename, mime in files:
        if mime not in ALLOWED_MIME:
            log.warning("Skipping unsupported mime %s for %s", mime, filename)
            continue
        cv_path, _ = storage.upload_original(content, filename) if False else _upload_resume(content, filename)
        code = job_id.generate_cand_code()
        row = {
            "code": code, "job_id": job["id"],
            "status": "PROCESSING",
            "source": source,
            "cv_filename": filename,
            "cv_storage_path": cv_path,
            "cv_mime": mime,
            "cv_size_bytes": len(content),
        }
        ins = supa.table("candidates").insert(row).execute()
        cand = ins.data[0]
        audit.write_audit(cand["id"], audit.ACTION_UPLOADED,
                          {"filename": filename, "batch_id": batch_id, "job_id": job["id"]},
                          performed_by=uploaded_by)
        created.append({"id": cand["id"], "code": code, "filename": filename})
    return {"batch_id": batch_id, "job_id": job["id"], "total": len(created), "candidates": created}


def _upload_resume(content: bytes, filename: str) -> tuple[str, str]:
    """Upload to the `resumes` bucket (separate from documents bucket)."""
    from datetime import datetime as _dt
    import mimetypes
    today = _dt.utcnow().strftime("%Y/%m/%d")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    path = f"{today}/{uuid4().hex}.{ext}"
    mime, _ = mimetypes.guess_type(filename)
    mime = mime or "application/octet-stream"
    get_supabase().storage.from_(settings.SUPABASE_BUCKET_RESUMES).upload(
        path=path, file=content, file_options={"content-type": mime, "upsert": "false"},
    )
    return path, mime


def process_candidate(candidate_id: str) -> None:
    """Background: download → extract text → parse → score → status → audit."""
    supa = get_supabase()
    try:
        cand = supa.table("candidates").select("*").eq("id", candidate_id).single().execute().data
    except Exception:
        log.error("process_candidate: candidate %s not found", candidate_id); return
    job = supa.table("jobs").select("*").eq("id", cand["job_id"]).single().execute().data
    if not job:
        log.error("process_candidate: job %s not found", cand["job_id"]); return

    # ---- 1. Download + extract text ----
    try:
        blob = storage.download_bytes(settings.SUPABASE_BUCKET_RESUMES, cand["cv_storage_path"])
    except Exception as e:
        _fail_candidate(candidate_id, f"download_failed: {e}"); return

    text = _extract_text(blob, cand["cv_mime"])
    if not text or len(text) < 30:
        _fail_candidate(candidate_id, "no_text_extracted"); return

    # ---- 2. Parse with Groq ----
    parsed_resume = rp.parse_resume_text(text)
    audit.write_audit(candidate_id, "parsed", {"chars": len(text)})

    # ---- 3. Bias-redact text used by scorer ----
    bias_flags = job.get("bias_flags") or {}
    redacted = rd.redact_text(text, parsed_resume, bias_flags)

    # ---- 4. Score ----
    weights = job.get("scoring_weights") or {}
    score = sc.score_candidate(parsed_resume, job.get("parsed_jd") or {}, weights, bias_flags)
    skill_profile = sc.derive_skill_profile(parsed_resume, score["breakdown"])

    # ---- 5. Auto route to SHORTLISTED or REJECTED ----
    threshold = float(job.get("auto_shortlist_threshold") or settings.RESUME_AUTO_SHORTLIST_DEFAULT)
    new_status = "SHORTLISTED" if score["final_score"] >= threshold else "REJECTED"
    ts_field = TS_FIELD_FOR[new_status]
    now_iso = datetime.now(timezone.utc).isoformat()

    update = {
        "name":  parsed_resume.get("name"),
        "email": parsed_resume.get("email"),
        "phone": parsed_resume.get("phone"),
        "location": _join_loc(parsed_resume.get("location") or {}),
        "total_experience_years": parsed_resume.get("total_experience_years"),
        "highest_education": parsed_resume.get("highest_education"),
        "parsed_resume": parsed_resume,
        "redacted_text": redacted,
        "final_score": score["final_score"],
        "score_breakdown": {**score["breakdown"], "skill_profile": skill_profile},
        "ai_insights": score["ai_insights"],
        "bias_panel": score["bias_panel"],
        "scoring_config_snapshot": {
            "weights": weights, "bias_flags": bias_flags,
            "auto_shortlist_threshold": threshold,
            "culture_reasoning": score.get("culture_reasoning"),
        },
        "status": new_status,
        "screened_at": now_iso,
    }
    if ts_field: update[ts_field] = now_iso
    supa.table("candidates").update(update).eq("id", candidate_id).execute()
    _write_pipeline(candidate_id, "PROCESSING", new_status, "system",
                    {"final_score": score["final_score"]})
    audit.write_audit(candidate_id, "scored",
                      {"final_score": score["final_score"], "auto_status": new_status})


def _extract_text(blob: bytes, mime: str) -> str:
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or mime == "application/msword":
        return docx_pdf_extractor.extract_docx(blob).text
    if mime == "application/pdf":
        r = docx_pdf_extractor.extract_pdf_digital(blob)
        if r.source == "pdf-digital" and r.text and len(r.text) >= 30:
            return r.text
        return ocr_mod.ocr_pdf(blob, language="en").text
    if mime in {"image/jpeg", "image/png"}:
        return ocr_mod.ocr_image(blob, language="en").text
    if mime == "text/plain":
        return blob.decode("utf-8", errors="ignore")
    return ""


def _join_loc(loc: dict) -> Optional[str]:
    parts = [loc.get("city"), loc.get("state"), loc.get("country")]
    return ", ".join([p for p in parts if p]) or None


def _fail_candidate(candidate_id: str, reason: str) -> None:
    """Mark a candidate REJECTED due to a pipeline failure (parse/extract/storage error)."""
    log.error("Failing candidate %s: %s", candidate_id, reason)
    now_iso = datetime.now(timezone.utc).isoformat()
    get_supabase().table("candidates").update({
        "status": "REJECTED",
        "rejection_reason": "other",
        "rejection_note": f"AUTO: {reason}",
        "screened_at": now_iso,           # so funnel still counts the attempt
        "rejected_at": now_iso,
    }).eq("id", candidate_id).execute()
    _write_pipeline(candidate_id, "PROCESSING", "REJECTED", "system", {"reason": reason})


def _write_pipeline(candidate_id: str, from_status: str, to_status: str,
                    actor: str = "system", details: dict | None = None) -> None:
    try:
        get_supabase().table("pipeline_history").insert({
            "candidate_id": candidate_id, "from_status": from_status,
            "to_status": to_status, "actor": actor, "details": details or {},
        }).execute()
    except Exception as e:
        log.warning("pipeline_history insert failed: %s", e)


# ============================================================
# CANDIDATES — list / detail / actions
# ============================================================
def list_candidates(job_id_or_code: Optional[str] = None,
                    status: Optional[str] = None,
                    min_score: Optional[float] = None,
                    q: Optional[str] = None,
                    page: int = 1, per_page: int = 50) -> dict:
    supa = get_supabase()
    query = supa.table("candidates").select("*", count="exact").order("final_score", desc=True)
    if job_id_or_code:
        job = get_job(job_id_or_code)
        if not job: return {"items": [], "total": 0}
        query = query.eq("job_id", job["id"])
    if status:    query = query.eq("status", status.upper())
    if min_score is not None:
        query = query.gte("final_score", min_score)
    if q:
        query = query.or_(f"name.ilike.%{q}%,email.ilike.%{q}%,location.ilike.%{q}%")

    page = max(1, page); per_page = min(200, max(1, per_page))
    start = (page - 1) * per_page
    end = start + per_page - 1
    res = query.range(start, end).execute()
    items = []
    for r in res.data or []:
        items.append(_to_candidate_summary(r))
    return {"items": items, "total": res.count or len(items), "page": page, "per_page": per_page}


def get_candidate(candidate_id_or_code: str) -> Optional[dict]:
    supa = get_supabase()
    if str(candidate_id_or_code).startswith("CAND-"):
        rec = supa.table("candidates").select("*").eq("code", candidate_id_or_code).limit(1).execute().data
    else:
        rec = supa.table("candidates").select("*").eq("id", candidate_id_or_code).limit(1).execute().data
    if not rec: return None
    cand = rec[0]
    history = supa.table("pipeline_history").select("*").eq("candidate_id", cand["id"]).order("created_at").execute().data or []
    audit_rows = supa.table("audit_log").select("*").eq("document_id", cand["id"]).order("created_at").execute().data or []

    cand["pipeline_history"] = history
    cand["audit_log"] = audit_rows
    cand["skill_profile"] = (cand.get("score_breakdown") or {}).get("skill_profile") or {}
    # Strip skill_profile from breakdown so the radar doesn't double-show
    if cand.get("score_breakdown") and "skill_profile" in cand["score_breakdown"]:
        cand["score_breakdown"] = {k: v for k, v in cand["score_breakdown"].items() if k != "skill_profile"}
    # Pre-signed CV URL (5min)
    if cand.get("cv_storage_path"):
        try:
            cand["cv_storage_url"] = storage.signed_url(settings.SUPABASE_BUCKET_RESUMES, cand["cv_storage_path"])
        except Exception:
            cand["cv_storage_url"] = None
    return cand


def _to_candidate_summary(r: dict) -> dict:
    parsed = r.get("parsed_resume") or {}
    skills = (parsed.get("skills") or {}).get("technical") or []
    return {
        "id":   r["id"], "code": r["code"], "job_id": r["job_id"],
        "name": r.get("name"), "email": r.get("email"),
        "location": r.get("location"),
        "total_experience_years": r.get("total_experience_years"),
        "final_score": r.get("final_score"),
        "status": r["status"],
        "source": r.get("source") or "Direct",
        "top_skills": list(skills[:6]),
        "applied_at": r["applied_at"],
    }


# ============================================================
# Pipeline / Actions
# ============================================================
def move_stage(candidate_id_or_code: str, new_status: str,
               note: Optional[str] = None, actor: str = "RSD") -> dict:
    cand = get_candidate(candidate_id_or_code)
    if not cand:
        return {"success": False, "message": "candidate not found"}
    new_status = new_status.upper()
    if new_status not in TS_FIELD_FOR:
        return {"success": False, "message": "invalid status"}
    update: dict[str, Any] = {"status": new_status}
    ts = TS_FIELD_FOR[new_status]
    now_iso = datetime.now(timezone.utc).isoformat()
    if ts: update[ts] = now_iso
    if new_status != "REJECTED":
        update["rejection_reason"] = None
        update["rejection_note"] = None

    get_supabase().table("candidates").update(update).eq("id", cand["id"]).execute()
    _write_pipeline(cand["id"], cand["status"], new_status, actor, {"note": note})
    audit.write_audit(cand["id"], "stage_moved",
                      {"from": cand["status"], "to": new_status, "note": note},
                      performed_by=actor)

    # Optional Telegram broadcast for advance into Interview/Offer/Recruited
    if new_status in CASCADE_PIPELINE_STAGES:
        job = get_job(cand["job_id"])
        msg = tg.format_advance_message(cand.get("name") or "(redacted)",
                                        (job or {}).get("title") or "the role",
                                        new_status)
        tg.send_to_all(msg)

    return {"success": True, "doc_id": cand["code"], "new_status": new_status}


def reject_candidate(candidate_id_or_code: str, reason: str = "other",
                     note: Optional[str] = None, send_telegram: bool = False,
                     use_ai_cheerup: bool = False, custom_hint: Optional[str] = None,
                     actor: str = "RSD") -> dict:
    cand = get_candidate(candidate_id_or_code)
    if not cand:
        return {"success": False, "message": "candidate not found"}
    job = get_job(cand["job_id"])

    msg = note
    if use_ai_cheerup:
        msg = tg.generate_cheerup(cand.get("name") or "Candidate",
                                  (job or {}).get("title") or "this role",
                                  custom_hint or "")

    now_iso = datetime.now(timezone.utc).isoformat()
    get_supabase().table("candidates").update({
        "status": "REJECTED",
        "rejection_reason": reason,
        "rejection_note": msg,
        "rejected_at": now_iso,
    }).eq("id", cand["id"]).execute()
    _write_pipeline(cand["id"], cand["status"], "REJECTED", actor,
                    {"reason": reason, "note": msg})
    audit.write_audit(cand["id"], "rejected", {"reason": reason}, performed_by=actor)

    tg_result = None
    if send_telegram and msg:
        full = (
            f"<b>Candidate update — {cand.get('code')}</b>\n"
            f"<b>Role:</b> {(job or {}).get('title') or '—'}\n\n"
            f"{msg}"
        )
        tg_result = tg.send_to_all(full)

    return {"success": True, "doc_id": cand["code"], "new_status": "REJECTED",
            "message": msg, "telegram": tg_result}


def schedule_interview(candidate_id_or_code: str, when: datetime,
                       prep: Optional[str] = None, send_telegram: bool = True,
                       actor: str = "RSD") -> dict:
    cand = get_candidate(candidate_id_or_code)
    if not cand:
        return {"success": False, "message": "candidate not found"}
    job = get_job(cand["job_id"])

    when_iso = when.isoformat() if isinstance(when, datetime) else str(when)
    update = {
        "status": "INTERVIEW",
        "scheduled_interview_at": when_iso,
        "interview_at": datetime.now(timezone.utc).isoformat(),
    }
    get_supabase().table("candidates").update(update).eq("id", cand["id"]).execute()
    _write_pipeline(cand["id"], cand["status"], "INTERVIEW", actor,
                    {"scheduled_for": when_iso, "prep": prep})
    audit.write_audit(cand["id"], "interview_scheduled",
                      {"when": when_iso, "prep": prep}, performed_by=actor)

    tg_result = None
    if send_telegram:
        msg = tg.format_interview_message(cand.get("name") or "(redacted)",
                                          (job or {}).get("title") or "the role",
                                          when_iso, prep or "")
        tg_result = tg.send_to_all(msg)
    return {"success": True, "doc_id": cand["code"], "scheduled_for": when_iso,
            "telegram": tg_result}


def add_note(candidate_id_or_code: str, text: str, author: str = "RSD") -> dict:
    cand = get_candidate(candidate_id_or_code)
    if not cand:
        return {"success": False, "message": "candidate not found"}
    notes = cand.get("notes") or []
    notes.append({"ts": datetime.now(timezone.utc).isoformat(), "author": author, "text": text})
    get_supabase().table("candidates").update({"notes": notes}).eq("id", cand["id"]).execute()
    audit.write_audit(cand["id"], "note_added", {"author": author}, performed_by=author)
    return {"success": True, "doc_id": cand["code"], "notes_count": len(notes)}


# ============================================================
# Re-score on settings change
# ============================================================
def rescore_job(job_id_or_code: str) -> dict:
    """Re-run scorer for every candidate on this job using the current job config."""
    job = get_job(job_id_or_code)
    if not job:
        return {"success": False, "message": "job not found"}
    supa = get_supabase()
    cands = supa.table("candidates").select("id, code, parsed_resume, redacted_text, status")\
        .eq("job_id", job["id"]).execute().data or []
    weights = job.get("scoring_weights") or {}
    bias_flags = job.get("bias_flags") or {}
    threshold = float(job.get("auto_shortlist_threshold") or settings.RESUME_AUTO_SHORTLIST_DEFAULT)
    parsed_jd = job.get("parsed_jd") or {}
    n = 0
    for c in cands:
        pr = c.get("parsed_resume") or {}
        if not pr: continue
        result = sc.score_candidate(pr, parsed_jd, weights, bias_flags)
        sp = sc.derive_skill_profile(pr, result["breakdown"])
        # Auto-reroute only if currently SHORTLISTED or REJECTED (don't churn manual moves)
        new_status = c["status"]
        if c["status"] in {"SHORTLISTED", "REJECTED"}:
            new_status = "SHORTLISTED" if result["final_score"] >= threshold else "REJECTED"
        upd = {
            "final_score": result["final_score"],
            "score_breakdown": {**result["breakdown"], "skill_profile": sp},
            "ai_insights": result["ai_insights"],
            "bias_panel": result["bias_panel"],
            "scoring_config_snapshot": {
                "weights": weights, "bias_flags": bias_flags,
                "auto_shortlist_threshold": threshold,
                "culture_reasoning": result.get("culture_reasoning"),
            },
            "status": new_status,
        }
        if new_status != c["status"]:
            ts = TS_FIELD_FOR.get(new_status)
            if ts: upd[ts] = datetime.now(timezone.utc).isoformat()
        supa.table("candidates").update(upd).eq("id", c["id"]).execute()
        if new_status != c["status"]:
            _write_pipeline(c["id"], c["status"], new_status, "system", {"reason": "rescore"})
        n += 1
    audit.write_audit(job["id"], "rescore_batch", {"updated": n}, performed_by="RSD")
    return {"success": True, "rescored": n}


# ============================================================
# ANALYTICS
# ============================================================
PERIOD_DAYS = {"7d": 7, "14d": 14, "30d": 30, "90d": 90}


def _period_bounds(period: str) -> tuple[datetime, datetime, datetime]:
    days = PERIOD_DAYS.get(period, 30)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev = start - timedelta(days=days)
    return start, now, prev


def analytics_kpis(period: str = "30d") -> dict:
    start, end, prev = _period_bounds(period)
    supa = get_supabase()
    cands = supa.table("candidates").select("status, applied_at, hired_at, offer_at, screened_at, scheduled_interview_at")\
        .gte("applied_at", start.isoformat()).execute().data or []

    active = sum(1 for c in cands if c["status"] in ("SHORTLISTED", "INTERVIEW", "OFFER"))
    hired = sum(1 for c in cands if c["status"] == "RECRUITED")
    offered = sum(1 for c in cands if c.get("offer_at"))

    # Time to hire
    hire_deltas = []
    for c in cands:
        if c.get("hired_at") and c.get("applied_at"):
            try:
                a = datetime.fromisoformat(str(c["applied_at"]).replace("Z", "+00:00"))
                h = datetime.fromisoformat(str(c["hired_at"]).replace("Z", "+00:00"))
                hire_deltas.append((h - a).days)
            except Exception:
                pass
    avg_t2h = round(sum(hire_deltas) / len(hire_deltas), 1) if hire_deltas else 0

    accept_pct = round(hired * 100 / offered, 1) if offered else 0

    return {
        "time_to_hire": {"value": avg_t2h, "unit": "days"},
        "offer_accept": {"value": accept_pct, "unit": "%"},
        "cost_per_hire": {"value": settings.COST_PER_HIRE_RUPEES, "unit": "INR"},
        "active_screens": {"value": active, "unit": "candidates"},
    }


def analytics_funnel(period: str = "30d") -> dict:
    start, end, _ = _period_bounds(period)
    supa = get_supabase()
    cands = supa.table("candidates").select("status, applied_at, screened_at, shortlisted_at, interview_at, offer_at, hired_at")\
        .gte("applied_at", start.isoformat()).execute().data or []
    counts = {
        "Applied":     len(cands),
        "AI Screened": sum(1 for c in cands if c.get("screened_at")),
        "Shortlisted": sum(1 for c in cands if c.get("shortlisted_at")),
        "Interviewed": sum(1 for c in cands if c.get("interview_at")),
        "Offered":     sum(1 for c in cands if c.get("offer_at")),
        "Recruited":   sum(1 for c in cands if c.get("hired_at")),
    }
    stages = []
    last = None
    for label, value in counts.items():
        drop = 0
        if last is not None and last:
            drop = int(round((last - value) / last * 100)) if last > value else 0
        stages.append({"label": label, "value": value, "dropRate": drop})
        last = value
    return {"period": period, "stages": stages, "total_applied": counts["Applied"]}


def analytics_sources(period: str = "30d") -> dict:
    start, _, _ = _period_bounds(period)
    rows = get_supabase().table("candidates").select("source").gte("applied_at", start.isoformat()).execute().data or []
    counts = Counter((r.get("source") or "Direct") for r in rows)
    total = sum(counts.values())
    palette = {"Referral": "var(--green)", "LinkedIn": "var(--cyan)", "Naukri": "var(--gold)", "Direct": "var(--red)"}
    return {
        "total": total,
        "segments": [
            {"label": k, "value": v, "color": palette.get(k, "var(--cyan)"),
             "percent": round(v * 100 / total, 1) if total else 0}
            for k, v in counts.most_common()
        ],
    }


def analytics_source_quality(period: str = "30d") -> dict:
    """Per-source quality breakdown — conversion rates + avg score + time-to-hire.
    Surfaced inside the SOURCE EFFECTIVENESS widget so HR can see which channels
    deliver the strongest candidates, not just the most volume."""
    start, _, _ = _period_bounds(period)
    rows = (
        get_supabase().table("candidates")
        .select("source, status, final_score, applied_at, hired_at")
        .gte("applied_at", start.isoformat())
        .execute().data or []
    )

    by_source: dict[str, dict] = {}
    for r in rows:
        src = r.get("source") or "Direct"
        s = by_source.setdefault(src, {
            "name": src,
            "applications": 0, "shortlisted": 0, "interviewed": 0,
            "offered": 0, "recruited": 0, "rejected": 0,
            "_scores": [], "_t2h_days": [],
        })
        s["applications"] += 1
        st = r.get("status")
        # `screened` is internal — count anything that's not PROCESSING/REJECTED
        if st in ("SHORTLISTED", "INTERVIEW", "OFFER", "RECRUITED"):
            s["shortlisted"] += 1
        if st in ("INTERVIEW", "OFFER", "RECRUITED"):
            s["interviewed"] += 1
        if st in ("OFFER", "RECRUITED"):
            s["offered"] += 1
        if st == "RECRUITED":
            s["recruited"] += 1
        if st == "REJECTED":
            s["rejected"] += 1
        if r.get("final_score") is not None:
            s["_scores"].append(float(r["final_score"]))
        if r.get("hired_at") and r.get("applied_at"):
            try:
                a = datetime.fromisoformat(str(r["applied_at"]).replace("Z", "+00:00"))
                h = datetime.fromisoformat(str(r["hired_at"]).replace("Z", "+00:00"))
                s["_t2h_days"].append((h - a).days)
            except Exception:
                pass

    # Compute derived fields and clean up internals
    sources_out = []
    for s in by_source.values():
        apps = max(s["applications"], 1)
        avg_score = round(sum(s["_scores"]) / len(s["_scores"]), 1) if s["_scores"] else 0
        avg_t2h = round(sum(s["_t2h_days"]) / len(s["_t2h_days"]), 1) if s["_t2h_days"] else None
        sources_out.append({
            "name": s["name"],
            "applications": s["applications"],
            "shortlisted": s["shortlisted"],
            "shortlist_rate": round(s["shortlisted"] * 100 / apps, 1),
            "interviewed": s["interviewed"],
            "offered": s["offered"],
            "recruited": s["recruited"],
            "rejected": s["rejected"],
            "hire_rate": round(s["recruited"] * 100 / apps, 1),
            "avg_score": avg_score,
            "avg_time_to_hire_days": avg_t2h,
        })
    sources_out.sort(key=lambda x: x["applications"], reverse=True)

    quality_leader = max(sources_out, key=lambda x: x["avg_score"])["name"] if sources_out else None
    converter = max(sources_out, key=lambda x: x["shortlist_rate"])["name"] if sources_out else None
    fastest = None
    fastest_t2h = None
    for s in sources_out:
        if s["avg_time_to_hire_days"] is not None:
            if fastest is None or s["avg_time_to_hire_days"] < fastest_t2h:
                fastest = s["name"]; fastest_t2h = s["avg_time_to_hire_days"]

    return {
        "sources": sources_out,
        "quality_leader": quality_leader,
        "best_converter": converter,
        "fastest_source": fastest,
        "total_applications": sum(s["applications"] for s in sources_out),
    }


def analytics_diversity(period: str = "30d") -> dict:
    start, _, _ = _period_bounds(period)
    rows = get_supabase().table("candidates").select("status, bias_panel, total_experience_years")\
        .gte("applied_at", start.isoformat()).execute().data or []

    def _pct(d):
        t = sum(d.values())
        return {k: round(v * 100 / t, 1) if t else 0 for k, v in d.items()}

    def _gender(rows_):
        c = Counter()
        for r in rows_:
            bp = r.get("bias_panel") or {}
            c[(bp.get("predicted_gender") or "unknown")] += 1
        return c

    applied = _gender(rows)
    hired = _gender([r for r in rows if r["status"] == "RECRUITED"])

    bands = Counter()
    for r in rows:
        y = float(r.get("total_experience_years") or 0)
        band = "<2y" if y < 2 else "2-5y" if y < 5 else "5-10y" if y < 10 else "10y+"
        bands[band] += 1

    return {
        "gender_applied": _pct(applied),
        "gender_hired":   _pct(hired),
        "experience_bands": _pct(bands),
        "totals": {
            "applied": sum(applied.values()),
            "hired": sum(hired.values()),
        },
    }


def analytics_apps_per_week(weeks: int = 8) -> dict:
    end = datetime.now(timezone.utc)
    start = end - timedelta(weeks=weeks)
    rows = get_supabase().table("candidates").select("applied_at").gte("applied_at", start.isoformat()).execute().data or []
    buckets = [0] * weeks
    for r in rows:
        try:
            dt = datetime.fromisoformat(str(r["applied_at"]).replace("Z", "+00:00"))
            wks_ago = (end - dt).days // 7
            if 0 <= wks_ago < weeks:
                buckets[weeks - 1 - wks_ago] += 1
        except Exception:
            continue
    return {"weeks": weeks, "data": buckets}


def analytics_top_skills(period: str = "30d", limit: int = 10) -> dict:
    start, _, _ = _period_bounds(period)
    rows = get_supabase().table("candidates").select("parsed_resume")\
        .gte("applied_at", start.isoformat()).execute().data or []
    c = Counter()
    for r in rows:
        sk = ((r.get("parsed_resume") or {}).get("skills") or {})
        for s in (sk.get("technical") or []):
            c[s] += 1
    return {"skills": [{"skill": k, "count": v} for k, v in c.most_common(limit)]}


def analytics_jobs_overview(limit: int = 5) -> dict:
    """Top jobs by applicant count + their avg score."""
    supa = get_supabase()
    jobs = supa.table("jobs").select("id, code, title, department").execute().data or []
    out = []
    for j in jobs:
        cands = supa.table("candidates").select("final_score, status")\
            .eq("job_id", j["id"]).execute().data or []
        scores = [c["final_score"] for c in cands if c.get("final_score") is not None]
        out.append({
            "code": j["code"], "title": j["title"], "department": j["department"],
            "applicants": len(cands),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "shortlisted": sum(1 for c in cands if c["status"] == "SHORTLISTED"),
            "recruited": sum(1 for c in cands if c["status"] == "RECRUITED"),
        })
    out.sort(key=lambda x: x["applicants"], reverse=True)
    return {"jobs": out[:limit]}
