"""
Module-scoped test fixtures for the Fake News Detector.

Hermetic by construction: the app under test mounts ONLY the fake_news
router on a bare FastAPI() (no app.main lifespan → no background threads,
no torch, no Groq, no Supabase). Tests that exercise routes monkeypatch
the heavy collaborators (service / repo / pipeline) at the boundary.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.modules.fake_news import router as fn_router
from app.shared.ratelimit import _reset as _rl_reset


@pytest.fixture()
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(fn_router, prefix="/api")
    return a


@pytest_asyncio.fixture()
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Process-global limiter state would leak across tests — clear it
    on both sides of every test so order can't matter."""
    _rl_reset()
    yield
    _rl_reset()
