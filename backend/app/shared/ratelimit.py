"""
In-process request rate limiting (CITADEL shared).

Why not slowapi: this deployment is a single uvicorn process, slowapi is
not installed (and pulls the `limits` dep), and it does not emit CITADEL's
``X-RateLimit-*`` header names or ``Retry-After`` out of the box — we'd
write custom callbacks anyway. A small dependency-free sliding-window
limiter is the exact-fit, zero-install-risk choice and matches
``.claude/rules/security-baseline.md`` (60/min per user, 10/min ML-heavy)
and ``api-conventions.md`` (429 + Retry-After + X-RateLimit-* headers)
precisely.

Identity precedence: ``X-User-Id`` header (the pseudonymous citizen /
officer id this no-JWT model already uses) → first ``X-Forwarded-For``
hop → socket peer IP. The window is a monotonic sliding window per
``(identity, bucket)``. State is per-process and in-memory — adequate for
the single-worker deployment; a multi-worker prod swap would back this
with Redis behind the same ``rate_limit()`` surface.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Response

_LOCK = threading.Lock()
_HITS: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _identity(request: Request) -> str:
    uid = (request.headers.get("x-user-id") or "").strip()
    if uid:
        return f"u:{uid}"
    return f"ip:{_client_ip(request)}"


def _reset() -> None:
    """Clear all counters — test-only hook (keeps tests independent)."""
    with _LOCK:
        _HITS.clear()


class RateLimiter:
    """FastAPI dependency: allow ``limit`` requests per ``window`` seconds
    for ``bucket``, keyed by caller identity.

    Sets ``X-RateLimit-*`` on the response on success; raises ``429`` with
    ``Retry-After`` + ``X-RateLimit-*`` on breach. Endpoints sharing a
    bucket share the budget (so a per-user ML-cost ceiling holds across
    every heavy endpoint, not per-route).
    """

    def __init__(self, bucket: str, limit: int, window: int = 60) -> None:
        self.bucket = bucket
        self.limit = limit
        self.window = window

    def __call__(self, request: Request, response: Response) -> None:
        key = f"{self.bucket}|{_identity(request)}"
        now = time.monotonic()
        cutoff = now - self.window
        with _LOCK:
            dq = _HITS[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.limit:
                retry = max(1, int(self.window - (now - dq[0])) + 1)
                raise HTTPException(
                    status_code=429,
                    detail=(f"rate limit exceeded for '{self.bucket}' "
                            f"({self.limit}/{self.window}s); retry in {retry}s"),
                    headers={
                        "Retry-After": str(retry),
                        "X-RateLimit-Limit": str(self.limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry),
                    },
                )
            dq.append(now)
            remaining = self.limit - len(dq)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(self.window)


def rate_limit(bucket: str, limit: int, window: int = 60) -> RateLimiter:
    """Build a rate-limit dependency. Wrap in ``Depends(...)`` and attach
    via a route's ``dependencies=[...]``."""
    return RateLimiter(bucket, limit, window)
