"""
Reusable auth dependencies. Server-side enforcement — the client's
x-user-role header convention is dead once these are applied (Phase 3.3).

401 = no/invalid/expired token. 403 = authenticated, wrong role.
Health probes and inbound webhooks (Telegram) stay public by simply not
taking these dependencies.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException

from app.core import security

log = logging.getLogger("citadel.core.deps")


def get_current_user(
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Verified JWT claims for the caller. 401 without a valid token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = security.decode_access_token(authorization.split(" ", 1)[1].strip())
    if claims is None:
        raise HTTPException(
            status_code=401,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def require_roles(*roles: str):
    """Dependency factory: require_roles('gov_admin','gov_officer')."""

    def guard(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"requires role: {', '.join(roles)}",
            )
        return user

    return guard


require_gov = require_roles(*security.GOV_ROLES)
require_citizen = require_roles("citizen")


def any_authenticated(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user
