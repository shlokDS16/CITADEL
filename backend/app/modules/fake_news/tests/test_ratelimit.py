"""Shared sliding-window rate limiter (app/shared/ratelimit.py).

Covers the post-review hardening: per-IP backstop, X-Forwarded-For trust
gate, idle-key eviction, and an injected clock (no global monkeypatch)."""
from __future__ import annotations

import httpx
from fastapi import Depends, FastAPI

from app.shared import ratelimit
from app.shared.ratelimit import rate_limit


def _app(bucket: str, limit: int, window: int = 60, *,
         ip_limit: int | None = None, clock=None) -> FastAPI:
    a = FastAPI()
    dep = rate_limit(bucket, limit, window, ip_limit=ip_limit,
                     clock=clock or __import__("time").monotonic)

    @a.get("/x", dependencies=[Depends(dep)])
    async def x():
        return {"ok": True}

    return a


async def _get(app: FastAPI, **headers):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://t") as c:
        return await c.get("/x", headers=headers)


async def test_allows_to_limit_then_429():
    app = _app("b1", 3)
    codes = [(await _get(app, **{"x-user-id": "u"})).status_code
             for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


async def test_success_carries_ratelimit_headers():
    app = _app("b2", 5)
    r = await _get(app, **{"x-user-id": "u"})
    assert r.headers["x-ratelimit-limit"] == "5"
    assert r.headers["x-ratelimit-remaining"] == "4"
    assert r.headers["x-ratelimit-reset"] == "60"


async def test_429_carries_retry_after_and_zero_remaining():
    app = _app("b3", 1)
    await _get(app, **{"x-user-id": "u"})
    r = await _get(app, **{"x-user-id": "u"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert r.headers["x-ratelimit-remaining"] == "0"


async def test_identity_isolation():
    app = _app("b4", 1)            # ip_limit defaults to 5x → bob not capped
    await _get(app, **{"x-user-id": "alice"})
    again = await _get(app, **{"x-user-id": "alice"})
    other = await _get(app, **{"x-user-id": "bob"})
    assert again.status_code == 429
    assert other.status_code == 200


async def test_ip_fallback_without_user_id():
    app = _app("b5", 1)
    r1 = await _get(app)
    r2 = await _get(app)
    assert r1.status_code == 200
    assert r2.status_code == 429


async def test_ip_backstop_caps_identity_rotation():
    # Per-user budget is huge, but the per-IP backstop must stop an
    # attacker rotating X-User-Id to mint fresh budgets.
    app = _app("bp", 100, ip_limit=2)
    c1 = await _get(app, **{"x-user-id": "a"})
    c2 = await _get(app, **{"x-user-id": "b"})
    c3 = await _get(app, **{"x-user-id": "c"})
    assert (c1.status_code, c2.status_code, c3.status_code) == (200, 200, 429)


async def test_xff_ignored_without_trusted_proxy():
    # No trusted proxy configured → spoofed X-Forwarded-For must NOT yield
    # a fresh per-IP bucket; both requests map to the socket peer.
    app = _app("bx", 1)
    r1 = await _get(app, **{"x-forwarded-for": "1.1.1.1"})
    r2 = await _get(app, **{"x-forwarded-for": "2.2.2.2"})
    assert r1.status_code == 200
    assert r2.status_code == 429


async def test_window_expiry_with_injected_clock():
    clock = {"v": 1000.0}
    app = _app("b6", 1, window=60, clock=lambda: clock["v"])
    assert (await _get(app, **{"x-user-id": "u"})).status_code == 200
    assert (await _get(app, **{"x-user-id": "u"})).status_code == 429
    clock["v"] += 61
    assert (await _get(app, **{"x-user-id": "u"})).status_code == 200


async def test_idle_keys_evicted():
    clock = {"v": 1000.0}
    app = _app("ev", 1, window=10, clock=lambda: clock["v"])
    await _get(app, **{"x-user-id": "u"})
    assert any(k.startswith("ev|") for k in ratelimit._HITS)
    clock["v"] += 11                       # window fully drained
    with ratelimit._LOCK:
        ratelimit._gc_locked(clock["v"])
    assert not any(k.startswith("ev|") for k in ratelimit._HITS)
