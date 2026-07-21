"""
Auth endpoints — /api/v1/auth/*.

Login is tightly rate-limited (5/min per identity, per-IP backstop) on
top of the DB-side lockout, per security-baseline.md.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from app.core.deps import get_current_user, require_citizen
from app.shared.ratelimit import rate_limit
from app.modules.auth import schemas, service

log = logging.getLogger("citadel.auth.router")
router = APIRouter()

_TAG = "auth"
_RL_LOGIN = Depends(rate_limit("auth:login", 5, 60))
_RL_STD = Depends(rate_limit("auth:std", 30, 60))


def _raise(e: service.AuthError) -> None:
    raise HTTPException(status_code=e.status, detail=str(e))


@router.post(
    "/v1/auth/login",
    response_model=schemas.TokenOut,
    tags=[_TAG],
    summary="Username/password login — returns access + rotating refresh token",
    dependencies=[_RL_LOGIN],
)
async def login(
    payload: schemas.LoginIn,
    user_agent: Optional[str] = Header(default=None, alias="User-Agent"),
) -> schemas.TokenOut:
    try:
        result = await run_in_threadpool(
            service.login, payload.username, payload.password, payload.portal, user_agent
        )
        return schemas.TokenOut(**result)
    except service.AuthError as e:
        _raise(e)
    except Exception as e:  # noqa: BLE001
        log.exception("login failed unexpectedly")
        raise HTTPException(status_code=500, detail="login unavailable")


@router.post(
    "/v1/auth/refresh",
    response_model=schemas.TokenOut,
    tags=[_TAG],
    summary="Rotate the refresh token, mint a fresh access token",
    dependencies=[_RL_STD],
)
async def refresh(
    payload: schemas.RefreshIn,
    user_agent: Optional[str] = Header(default=None, alias="User-Agent"),
) -> schemas.TokenOut:
    try:
        result = await run_in_threadpool(service.refresh, payload.refresh_token, user_agent)
        return schemas.TokenOut(**result)
    except service.AuthError as e:
        _raise(e)


@router.post(
    "/v1/auth/logout",
    status_code=204,
    tags=[_TAG],
    summary="Revoke the presented refresh token",
    dependencies=[_RL_STD],
)
async def logout(payload: schemas.LogoutIn) -> None:
    await run_in_threadpool(service.logout, payload.refresh_token, None)


@router.get(
    "/v1/auth/me",
    response_model=schemas.UserOut,
    tags=[_TAG],
    summary="Who am I (verifies the bearer token)",
)
async def me(user: dict[str, Any] = Depends(get_current_user)) -> schemas.UserOut:
    return schemas.UserOut(
        id=user["sub"], username=user.get("username") or "",
        display_name=None, role=user["role"], last_login_at=None,
    )


@router.post(
    "/v1/auth/register",
    response_model=schemas.UserOut,
    status_code=201,
    tags=[_TAG],
    summary="Citizen self-registration (gov accounts are admin-created)",
    dependencies=[_RL_LOGIN],
)
async def register(payload: schemas.RegisterIn) -> schemas.UserOut:
    try:
        row = await run_in_threadpool(
            service.register, payload.username, payload.password,
            payload.display_name, payload.email,
        )
        return schemas.UserOut(**row)
    except service.AuthError as e:
        _raise(e)


@router.post(
    "/v1/auth/claim",
    response_model=schemas.ClaimOut,
    tags=[_TAG],
    summary="Adopt pre-auth browser data into the logged-in citizen account",
    dependencies=[_RL_STD],
)
async def claim(
    payload: schemas.ClaimIn,
    user: dict[str, Any] = Depends(require_citizen),
) -> schemas.ClaimOut:
    try:
        migrated = await run_in_threadpool(
            service.claim_anonymous, user["sub"], payload.anonymous_uid
        )
        return schemas.ClaimOut(migrated=migrated)
    except ValueError:
        raise HTTPException(status_code=400, detail="anonymous_uid must be a uuid")
    except service.AuthError as e:
        _raise(e)
