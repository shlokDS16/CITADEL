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

from fastapi import APIRouter, HTTPException

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
