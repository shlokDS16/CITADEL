"""
In-process request rate limiting (CITADEL shared).

Why not slowapi: this deployment is a single uvicorn process, slowapi is
not installed (and pulls the `limits` dep), and it does not emit CITADEL's
``X-RateLimit-*`` header names or ``Retry-After`` out of the box — we'd
write custom callbacks anyway. A small dependency-free sliding-window
limiter is the exact-fit, zero-install-risk choice and matches
``.claude/rules/security-baseline.md`` (per-user *and* per-IP limits,
ML-heavy lower) and ``api-conventions.md`` (429 + Retry-After +
X-RateLimit-* headers).

Two dimensions per request so the limit is a real control, not advisory:

  * a per-identity bucket keyed on ``X-User-Id`` — a fairness / UX key the
    caller can freely rotate in this no-JWT citizen model; and
  * a per-IP backstop the caller *cannot* reset by rotating that header
    (default ceiling = 5x the identity limit, so a handful of users can
    share a NAT while header-rotation abuse still hits a wall).

The IP is the real socket peer. ``X-Forwarded-For`` is honored ONLY when
the socket peer is a configured trusted proxy
(``settings.RL_TRUSTED_PROXIES``); on a direct deployment XFF is
attacker-controlled and is ignored — otherwise the per-IP backstop would
itself be spoofable.

State is per-process and in-memory, with opportunistic eviction of
fully-drained keys so distinct-identity floods can't grow the map without
bound. Single-worker only: running >1 uvicorn/gunicorn worker without a
shared store makes the effective limit Nx the configured value — a
multi-worker prod swap backs this with Redis behind the same
``rate_limit()`` surface.

Header convention: ``X-RateLimit-Reset`` is the window length (seconds)
on a success and the seconds-until-retry on a 429. Routes that return
their own ``Response``/``HTMLResponse`` (report.html / report.pdf) still
enforce the limit and carry the headers on a 429, but FastAPI does not
merge dependency-set headers into a handler-built Response, so their
*successful* 200s do not surface ``X-RateLimit-*`` (accepted — the limit
still holds).
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request, Response

from app.config import settings

_LOCK = threading.Lock()
_HITS: dict[str, deque[float]] = defaultdict(deque)
_WIN: dict[str, int] = {}              # key → window (for generic GC trim)
_GC_EVERY = 256
_calls_since_gc = 0


def _ip_in_trusted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in settings.rl_trusted_proxy_nets)


def _client_ip(request: Request) -> str:
    """Real socket peer — unless the peer is a configured trusted proxy,
    in which case the right-most *untrusted* X-Forwarded-For hop (the
    address that trusted proxy actually saw). XFF is ignored entirely on a
    direct deployment so it cannot be used to spoof the per-IP backstop."""
    peer = request.client.host if request.client else "unknown"
    if not _ip_in_trusted(peer):
        return peer
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return peer
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        if not _ip_in_trusted(hop):
            return hop
    return peer


def _reset() -> None:
    """Clear all counters — test-only hook (keeps tests independent)."""
    global _calls_since_gc
    with _LOCK:
        _HITS.clear()
        _WIN.clear()
        _calls_since_gc = 0


def _gc_locked(now: float) -> None:
    """Evict keys whose window has fully drained. Caller holds _LOCK."""
    dead: list[str] = []
    for k, dq in _HITS.items():
        w = _WIN.get(k, 0)
        while dq and dq[0] < now - w:
            dq.popleft()
        if not dq:
            dead.append(k)
    for k in dead:
        _HITS.pop(k, None)
        _WIN.pop(k, None)


class RateLimiter:
    """FastAPI dependency: allow ``limit`` requests / ``window`` s for
    ``bucket`` per identity, with a per-IP backstop at ``ip_limit``
    (default 5x ``limit``). Sets ``X-RateLimit-*`` on success; raises 429
    with ``Retry-After`` + ``X-RateLimit-*`` when *either* dimension is
    full. Endpoints sharing a bucket share the budget."""

    def __init__(self, bucket: str, limit: int, window: int = 60, *,
                 ip_limit: int | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.bucket = bucket
        self.limit = limit
        self.window = window
        self.ip_limit = ip_limit if ip_limit is not None else limit * 5
        self._clock = clock

    def __call__(self, request: Request, response: Response) -> None:
        global _calls_since_gc
        ip = _client_ip(request)
        uid = (request.headers.get("x-user-id") or "").strip()
        now = self._clock()
        if uid:
            dims = [(f"{self.bucket}|u:{uid}", self.limit),
                    (f"{self.bucket}|ip:{ip}", self.ip_limit)]
        else:
            dims = [(f"{self.bucket}|ip:{ip}", self.limit)]

        with _LOCK:
            evald: list[tuple[str, int, deque[float]]] = []
            for key, lim in dims:
                dq = _HITS[key]
                _WIN[key] = self.window
                cutoff = now - self.window
                while dq and dq[0] < cutoff:
                    dq.popleft()
                evald.append((key, lim, dq))

            for key, lim, dq in evald:
                if len(dq) >= lim:
                    retry = max(1, int(self.window - (now - dq[0])) + 1)
                    raise HTTPException(
                        status_code=429,
                        detail=(f"rate limit exceeded for '{self.bucket}' "
                                f"({lim}/{self.window}s); retry in {retry}s"),
                        headers={
                            "Retry-After": str(retry),
                            "X-RateLimit-Limit": str(lim),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(retry),
                        },
                    )

            for _key, _lim, dq in evald:
                dq.append(now)
            # report the most-constrained dimension
            limit_h, remaining_h = min(
                ((lim, lim - len(dq)) for _k, lim, dq in evald),
                key=lambda t: t[1],
            )

            _calls_since_gc += 1
            if _calls_since_gc >= _GC_EVERY:
                _calls_since_gc = 0
                _gc_locked(now)

        response.headers["X-RateLimit-Limit"] = str(limit_h)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining_h))
        response.headers["X-RateLimit-Reset"] = str(self.window)


def rate_limit(bucket: str, limit: int, window: int = 60, *,
               ip_limit: int | None = None,
               clock: Callable[[], float] = time.monotonic) -> RateLimiter:
    """Build a rate-limit dependency. Wrap in ``Depends(...)`` and attach
    via a route's ``dependencies=[...]``."""
    return RateLimiter(bucket, limit, window, ip_limit=ip_limit, clock=clock)
