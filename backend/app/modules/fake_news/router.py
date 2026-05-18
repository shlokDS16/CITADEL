"""
Fake News Detector — HTTP endpoints.

Mounted in app/main.py with prefix="/api"; spec-06 base path is
/api/v1/fake-news (versioned per api-conventions.md). Routers stay thin:
parse → call service → return. ML/blocking work runs in a threadpool
(added from Phase 1 onward).

Phase 0: health only.
"""
from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from starlette.concurrency import run_in_threadpool

from app.config import settings

from app.modules.fake_news import schemas, service

log = logging.getLogger("citadel.fake_news.router")
router = APIRouter()

_TAG = "fake-news"


@router.get(
    "/v1/fake-news/health",
    response_model=schemas.HealthResponse,
    tags=[_TAG],
    summary="Liveness/readiness — ML runtime, model config, Supabase tables, keys",
)
async def health() -> schemas.HealthResponse:
    try:
        return service.health()
    except Exception as e:  # noqa: BLE001
        log.exception("fake-news health failed")
        raise HTTPException(status_code=500, detail=f"health failed: {e}")


@router.post(
    "/v1/fake-news/analyze",
    response_model=schemas.AnalysisOut,
    tags=[_TAG],
    summary="Analyze text / URL (Phase 1: Layer-1 heuristics waterfall)",
)
async def analyze(
    body: schemas.AnalyzeIn,
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> schemas.AnalysisOut:
    """Run the misinformation analysis waterfall on text or a URL.

    Blocking work (URL fetch, RDAP, hashing, later ML) runs in a threadpool
    so the event loop stays free — same pattern as citizen_assistant.
    """
    try:
        return await run_in_threadpool(
            service.analyze,
            body,
            x_user_id,
            (x_user_role or "citizen"),
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("fake-news analyze failed")
        raise HTTPException(status_code=500, detail=f"analyze failed: {e}")


@router.post(
    "/v1/fake-news/analyze/media",
    response_model=schemas.AnalysisOut,
    tags=[_TAG],
    summary="Deepfake / AI-image (and video) forensics on an uploaded file",
)
async def analyze_media(
    file: UploadFile = File(...),
    query: str = Form(""),
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> schemas.AnalysisOut:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit")
    try:
        return await run_in_threadpool(
            service.analyze_media_content, content, file.filename or "media",
            query, x_user_id, (x_user_role or "citizen"))
    except Exception as e:  # noqa: BLE001
        log.exception("analyze_media failed")
        raise HTTPException(status_code=500, detail=f"media analysis failed: {e}")


@router.post(
    "/v1/fake-news/warmup",
    tags=[_TAG],
    summary="Eagerly load + calibrate the L2 models (prod readiness)",
)
async def warmup() -> dict:
    """Pre-load every L2 model so the first real request isn't slow."""
    try:
        from app.modules.fake_news import pipeline as ml

        status = await run_in_threadpool(ml.warmup)
        return {"status": "ok", "models": status}
    except Exception as e:  # noqa: BLE001
        log.exception("fake-news warmup failed")
        raise HTTPException(status_code=500, detail=f"warmup failed: {e}")


@router.get("/v1/fake-news/sources", tags=[_TAG],
            summary="List the source-credibility KB (allowlist/blocklist)")
async def list_sources() -> dict:
    from app.modules.fake_news import credibility

    rows = await run_in_threadpool(credibility.all_rows, 500)
    return {"data": rows, "meta": {"total": len(rows)}}


@router.get("/v1/fake-news/sources/{domain}", tags=[_TAG],
            summary="Credibility for one domain (KB row + age heuristic)")
async def get_source(domain: str) -> dict:
    from app.modules.fake_news import credibility

    info = await run_in_threadpool(credibility.score_for, domain, None)
    return {"data": info}


@router.put("/v1/fake-news/sources/{domain}", tags=[_TAG],
            summary="Officer edit of a credibility row (runtime-editable)")
async def put_source(
    domain: str,
    body: schemas.SourceUpdate,
    x_user_id: str | None = Header(default=None),
) -> dict:
    from app.modules.fake_news import credibility

    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to update")
    try:
        row = await run_in_threadpool(credibility.upsert, domain, fields, x_user_id)
        if row is None:
            raise HTTPException(status_code=503,
                                detail="credibility store unavailable")
        return {"data": row}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("put_source failed")
        raise HTTPException(status_code=500, detail=f"update failed: {e}")


@router.get("/v1/fake-news/related-fact-checks", tags=[_TAG],
            summary="Search fact-check feeds + Google Fact Check for a query")
async def related_fact_checks(q: str) -> dict:
    from app.modules.fake_news import fact_check

    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="q is required")
    rows = await run_in_threadpool(fact_check.search, q.strip())
    return {"data": rows, "meta": {"total": len(rows)}}


# ---- history / persistence (Phase 4) ----
@router.get("/v1/fake-news/analyses/{analysis_id}", tags=[_TAG],
            summary="Full stored analysis (with claim rows)")
async def get_analysis(analysis_id: str) -> dict:
    from app.modules.fake_news import repo

    row = await run_in_threadpool(repo.get_analysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return {"data": row}


@router.get("/v1/fake-news/history", tags=[_TAG], summary="Past checks (paged)")
async def history(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    q: str | None = None, verdict: str | None = None,
    x_user_id: str | None = Header(default=None),
) -> dict:
    from app.modules.fake_news import repo

    res = await run_in_threadpool(repo.history, x_user_id, page, page_size, q, verdict)
    return {"data": res["items"],
            "meta": {"total": res["total"], "page": res["page"],
                     "page_size": res["page_size"]}}


@router.get("/v1/fake-news/history/stats", tags=[_TAG],
            summary="History KPIs (checks run / fake / real / reported)")
async def history_stats(x_user_id: str | None = Header(default=None)) -> dict:
    from app.modules.fake_news import repo

    return {"data": await run_in_threadpool(repo.history_stats, x_user_id)}


@router.delete("/v1/fake-news/history/{analysis_id}", tags=[_TAG],
               summary="Soft-delete an analysis from the requester's history")
async def delete_history(
    analysis_id: str, x_user_id: str | None = Header(default=None),
) -> dict:
    from app.modules.fake_news import repo

    ok = await run_in_threadpool(repo.soft_delete, analysis_id, x_user_id)
    if not ok:
        raise HTTPException(status_code=503, detail="history store unavailable")
    return {"data": {"deleted": analysis_id}}


# ---- HITL review queue + feedback (Phase 4) ----
@router.get("/v1/fake-news/review-queue", tags=[_TAG],
            summary="Low-confidence analyses awaiting human review")
async def review_queue(status: str = "pending") -> dict:
    from app.modules.fake_news import repo

    rows = await run_in_threadpool(repo.list_review_queue, status, 100)
    return {"data": rows, "meta": {"total": len(rows)}}


@router.post("/v1/fake-news/review/{queue_id}/decide", tags=[_TAG],
             summary="Resolve a review item (ground-truth for retraining)")
async def review_decide(
    queue_id: str, body: schemas.ReviewDecision,
    x_user_id: str | None = Header(default=None),
) -> dict:
    from app.modules.fake_news import repo

    res = await run_in_threadpool(
        repo.decide_review, queue_id, body.human_verdict, body.notes, x_user_id)
    if res is None:
        raise HTTPException(status_code=404,
                            detail="review item not found / store unavailable")
    return {"data": res}


@router.post("/v1/fake-news/feedback", tags=[_TAG],
             summary="Direct ground-truth feedback on an analysis")
async def feedback(
    body: schemas.FeedbackIn, x_user_id: str | None = Header(default=None),
) -> dict:
    from app.modules.fake_news import repo

    ok = await run_in_threadpool(
        repo.add_feedback, body.analysis_id, body.human_verdict,
        x_user_id, body.notes)
    if not ok:
        raise HTTPException(status_code=503, detail="feedback store unavailable")
    return {"data": {"recorded": True}}


@router.post("/v1/fake-news/meta/refit", tags=[_TAG],
             summary="Refit the logistic meta-classifier from feedback")
async def meta_refit() -> dict:
    from app.modules.fake_news import repo

    return {"data": await run_in_threadpool(repo.refit_meta)}


@router.get("/v1/fake-news/meta/status", tags=[_TAG],
            summary="Latest meta-classifier training status")
async def meta_status() -> dict:
    from app.modules.fake_news import repo

    return {"data": await run_in_threadpool(repo.meta_status)}


# ---- CIB / propagation (Phase 6, ingest-fed) ----
@router.post("/v1/fake-news/propagation/analyze", tags=[_TAG],
             summary="Analyze an uploaded share-graph for coordinated "
                     "inauthentic behaviour")
async def propagation_analyze(
    file: UploadFile = File(...),
    x_user_id: str | None = Header(default=None),
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty file")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file too large")

    def _work() -> dict:
        from app.modules.fake_news import propagation, repo

        res = propagation.run(raw, file.filename or "")
        if not res.get("ok"):
            return {"_error": res.get("error", "could not analyze graph")}
        res["run_id"] = repo.save_propagation_run(
            x_user_id, file.filename or "upload", res)
        return res

    out = await run_in_threadpool(_work)
    if "_error" in out:
        raise HTTPException(status_code=422, detail=out["_error"])
    return {"data": out}


@router.get("/v1/fake-news/propagation/runs", tags=[_TAG],
            summary="Recent propagation/CIB analysis runs")
async def propagation_runs() -> dict:
    from app.modules.fake_news import repo

    rows = await run_in_threadpool(repo.list_propagation_runs, 50)
    return {"data": rows, "meta": {"total": len(rows)}}
