"""
Overview endpoint — GET /api/v1/overview.

Authenticated (any role); the shape is chosen by the caller's role in the
verified token, so a gov user gets the gov KPIs and a citizen the citizen
KPIs. Cheap enough to call on every dashboard mount.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.core import security
from app.modules.overview import service

log = logging.getLogger("citadel.overview.router")
router = APIRouter()


@router.get(
    "/v1/overview",
    tags=["overview"],
    summary="Landing-dashboard KPIs — real cross-module counts, role-shaped",
)
async def overview(request: Request) -> dict:
    claims = getattr(request.state, "user", None)
    if not claims or not claims.get("sub"):
        raise HTTPException(
            status_code=401, detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = str(claims.get("role", ""))
    fn = service.gov_overview if role in security.GOV_ROLES else service.citizen_overview
    try:
        return await run_in_threadpool(fn)
    except Exception as e:  # noqa: BLE001
        log.exception("overview failed")
        raise HTTPException(status_code=500, detail=str(e))
