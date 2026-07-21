"""
Admin endpoints — /api/v1/admin/*. gov_admin only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.database import get_supabase

log = logging.getLogger("citadel.admin.router")
router = APIRouter()
_TAG = "admin"

_ROLES = ("gov_admin", "gov_officer", "gov_analyst", "citizen")


def _admin(request: Request) -> dict[str, Any]:
    claims = getattr(request.state, "user", None)
    if not claims or not claims.get("sub"):
        raise HTTPException(status_code=401, detail="authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    if claims.get("role") != "gov_admin":
        raise HTTPException(status_code=403, detail="administrator access required")
    return claims


def _audit(actor: str, action: str, target: Optional[str], details: dict[str, Any]) -> None:
    try:
        get_supabase().table("audit_log").insert({
            "action": action, "performed_by": actor,
            "details": {**details, "target": target},
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("admin audit write failed: %s", e)


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
class AdminUserOut(BaseModel):
    id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: bool = True
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class UserPatchIn(BaseModel):
    role: Optional[str] = Field(default=None)
    is_active: Optional[bool] = None


@router.get("/v1/admin/users", response_model=list[AdminUserOut], tags=[_TAG],
            summary="List accounts")
async def list_users(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=64),
    role: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AdminUserOut]:
    _admin(request)

    def _run() -> list[dict[str, Any]]:
        query = get_supabase().table("users").select(
            "id, username, display_name, email, role, is_active, last_login_at, created_at"
        )
        if role:
            query = query.eq("role", role)
        if q:
            query = query.ilike("username", f"%{q}%")
        return (query.order("created_at", desc=True).limit(limit).execute()).data or []

    rows = await run_in_threadpool(_run)
    return [AdminUserOut(**r) for r in rows]


@router.patch("/v1/admin/users/{user_id}", response_model=AdminUserOut, tags=[_TAG],
              summary="Change a user's role or activation")
async def patch_user(user_id: str, payload: UserPatchIn, request: Request) -> AdminUserOut:
    admin = _admin(request)
    if payload.role is None and payload.is_active is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    if payload.role is not None and payload.role not in _ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {', '.join(_ROLES)}")
    # an admin cannot lock themselves out
    if user_id == admin["sub"]:
        if payload.is_active is False:
            raise HTTPException(status_code=409, detail="you cannot deactivate your own account")
        if payload.role is not None and payload.role != "gov_admin":
            raise HTTPException(status_code=409, detail="you cannot remove your own admin role")

    def _run() -> Optional[dict[str, Any]]:
        sb = get_supabase()
        patch: dict[str, Any] = {}
        if payload.role is not None:
            patch["role"] = payload.role
        if payload.is_active is not None:
            patch["is_active"] = payload.is_active
        res = sb.table("users").update(patch).eq("id", user_id).execute()
        rows = res.data or []
        if not rows:
            return None
        # deactivating a user kills their refresh chain immediately
        if payload.is_active is False:
            try:
                sb.table("refresh_tokens").update(
                    {"revoked_at": datetime.now(timezone.utc).isoformat()}
                ).eq("user_id", user_id).is_("revoked_at", "null").execute()
            except Exception:  # noqa: BLE001
                pass
        return rows[0]

    row = await run_in_threadpool(_run)
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    _audit(admin["sub"], "admin_user_update", user_id,
           {"role": payload.role, "is_active": payload.is_active})
    return AdminUserOut(**row)


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------
class AuditRowOut(BaseModel):
    id: str
    action: str
    performed_by: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


@router.get("/v1/admin/audit", response_model=list[AuditRowOut], tags=[_TAG],
            summary="Recent audit-log entries (append-only)")
async def audit_log(
    request: Request,
    action: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AuditRowOut]:
    _admin(request)

    def _run() -> list[dict[str, Any]]:
        q = get_supabase().table("audit_log").select("id, action, performed_by, details, created_at")
        if action:
            q = q.eq("action", action)
        return (q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()).data or []

    rows = await run_in_threadpool(_run)
    return [AuditRowOut(id=str(r.get("id")), action=r.get("action") or "",
                        performed_by=r.get("performed_by"),
                        details=r.get("details") or {}, created_at=r.get("created_at"))
            for r in rows]


# --------------------------------------------------------------------------
# Platform stats
# --------------------------------------------------------------------------
@router.get("/v1/admin/stats", tags=[_TAG], summary="Platform-wide counts")
async def stats(request: Request) -> dict[str, Any]:
    _admin(request)

    def _count(table: str, **eq: Any) -> Optional[int]:
        try:
            q = get_supabase().table(table).select("*", count="exact").limit(1)
            for k, v in eq.items():
                q = q.eq(k, v)
            return (q.execute()).count
        except Exception:  # noqa: BLE001
            return None

    def _run() -> dict[str, Any]:
        by_role = {}
        for r in _ROLES:
            by_role[r] = _count("users", role=r)
        return {
            "users_total": _count("users"),
            "users_by_role": by_role,
            "users_inactive": _count("users", is_active=False),
            "tickets": _count("tickets"),
            "expenses": _count("expenses"),
            "fake_news_analyses": _count("analyses"),
            "tv_incidents": _count("tv_incidents"),
            "tv_challans": _count("tv_challans"),
            "telegram_connected": _count("telegram_settings"),
            "audit_rows": _count("audit_log"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    return await run_in_threadpool(_run)
