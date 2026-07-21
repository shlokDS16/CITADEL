"""
API-wide auth policy middleware (Phase 3.3).

One explicit, auditable table instead of 200 per-endpoint decorators.
Order of evaluation:

  1. OPTIONS passes (CORS preflights carry no auth headers by design).
  2. PUBLIC paths pass: auth endpoints, health probes, API docs, the
     Telegram inbound webhook (Telegram's servers cannot log in), and
     media fetched by <img>/<video> tags (browsers cannot attach
     Authorization headers to those). Fake-news report.html keeps its
     pre-existing ?uid= tenant-scoping.
  3. Everything else under /api requires a valid Bearer token; GOV
     surfaces additionally require a gov role, CITIZEN surfaces the
     citizen role. Unknown /api paths default to authenticated —
     deny-unknown, not allow-unknown.

Verified claims are attached as request.state.user for handlers.

KNOWN GAP (documented, deliberate): traffic evidence media and fake-news
reports remain public-with-obscure-id because header auth cannot reach
them. The enterprise fix is short-lived signed URLs like the receipts
bucket uses — queued behind Phase 3.
"""
from __future__ import annotations

import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core import security

log = logging.getLogger("citadel.core.policy")

_PUBLIC_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/docs",
    "/api/v1/openapi.json",
    "/api/v1/redoc",
)
_PUBLIC_EXACT = (
    "/api/v1/health",
    "/api/traffic-violations/telegram/webhook",
)
_PUBLIC_PATTERNS = (
    re.compile(r"^/api/v1/[a-z-]+/health$"),                                  # module health probes
    re.compile(r"^/api/traffic-violations/loops/[^/]+/(video\.mp4|tracks\.json)$"),
    re.compile(r"^/api/traffic-violations/incidents/[^/]+/(clip\.mp4|evidence\.jpg)$"),
    re.compile(r"^/api/v1/fake-news/analyses/[^/]+/report\.(html|pdf)$"),
)

_GOV_PREFIXES = (
    "/api/documents", "/api/templates", "/api/dashboard",   # document intelligence
    "/api/resume",                                          # resume screening
    "/api/traffic-violations",                              # traffic
    "/api/anomaly",                                         # anomaly monitoring
)
_CITIZEN_PREFIXES = (
    "/api/v1/tickets",
    "/api/v1/expenses",
    "/api/citizen",                                         # assistant chat/upload
    "/api/v1/fake-news",
)


def _is_public(path: str) -> bool:
    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return True
    if path in _PUBLIC_EXACT:
        return True
    return any(rx.match(path) for rx in _PUBLIC_PATTERNS)


def _deny(status: int, detail: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


class AuthPolicyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api") or _is_public(path):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return _deny(401, "authentication required")
        claims = security.decode_access_token(auth.split(" ", 1)[1].strip())
        if claims is None:
            return _deny(401, "invalid or expired token")

        role = str(claims.get("role", ""))
        if any(path.startswith(p) for p in _GOV_PREFIXES):
            if role not in security.GOV_ROLES:
                return _deny(403, "government role required")
        elif any(path.startswith(p) for p in _CITIZEN_PREFIXES):
            if role != "citizen":
                return _deny(403, "citizen account required")
        # unknown /api path: any valid token passes (deny-unknown handled
        # by requiring the token above)

        request.state.user = claims
        return await call_next(request)
