"""Shared sliding-window rate limiter (app/shared/ratelimit.py)."""
from __future__ import annotations

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.shared import ratelimit
from app.shared.ratelimit import rate_limit


def _app(bucket: str, limit: int, window: int = 60) -> FastAPI:
    a = FastAPI()

    @a.get("/x", dependencies=[Depends(rate_limit(bucket, limit, window))])
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
    app = _app("b4", 1)
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


async def test_window_expiry(monkeypatch):
    clock = {"v": 1000.0}
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock["v"])
    app = _app("b6", 1, window=60)
    assert (await _get(app, **{"x-user-id": "u"})).status_code == 200
    assert (await _get(app, **{"x-user-id": "u"})).status_code == 429
    clock["v"] += 61
    assert (await _get(app, **{"x-user-id": "u"})).status_code == 200
