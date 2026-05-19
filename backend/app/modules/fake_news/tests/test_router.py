"""HTTP layer: happy path + 4xx (validation / spoof) + rate-limit 429.

Heavy collaborators are monkeypatched so NO Groq token, NO model
download, NO Supabase call happens (testing.md: mock the boundary)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.config import settings
from app.modules.fake_news import schemas, service
from app.modules.fake_news.router import _max_body

ELF = b"\x7fELF\x02\x01" + b"\x00" * 16


def _fake_health() -> schemas.HealthResponse:
    return schemas.HealthResponse(
        status="ok", version="0.1.0", python="3.14",
        ml=schemas.MLRuntime(), models_dir="/x", models_dir_ok=True,
        models_configured={}, tables_ok=True, groq_configured=True,
        google_factcheck_configured=True)


def _fake_analysis(*_a, **_k) -> schemas.AnalysisOut:
    return schemas.AnalysisOut(
        id="t1", submitted_at=datetime.now(timezone.utc), mode="TEXT",
        verdict="UNCERTAIN", confidence=0.42)


async def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(service, "health", _fake_health)
    r = await client.get("/api/v1/fake-news/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["module"] == "fake_news"


async def test_analyze_text_ok_and_heavy_bucket_header(client, monkeypatch):
    monkeypatch.setattr(service, "analyze", _fake_analysis)
    r = await client.post(
        "/api/v1/fake-news/analyze",
        json={"mode": "TEXT", "text": "some claim"},
        headers={"x-user-id": "u1"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "UNCERTAIN"
    assert r.headers["x-ratelimit-limit"] == "10"


async def test_analyze_blank_text__422(client, monkeypatch):
    monkeypatch.setattr(service, "analyze", _fake_analysis)
    r = await client.post(
        "/api/v1/fake-news/analyze",
        json={"mode": "TEXT", "text": "   "},
        headers={"x-user-id": "u2"})
    assert r.status_code == 422


async def test_media_extension_spoof__415(client):
    r = await client.post(
        "/api/v1/fake-news/analyze/media",
        files={"file": ("evil.jpg", ELF, "image/jpeg")},
        headers={"x-user-id": "u3"})
    assert r.status_code == 415


async def test_bulk_empty_urls__422(client):
    r = await client.post(
        "/api/v1/fake-news/bulk", json={"urls": []},
        headers={"x-user-id": "u4"})
    assert r.status_code == 422


async def test_heavy_bucket_429_after_10(client, monkeypatch):
    monkeypatch.setattr(service, "analyze", _fake_analysis)
    codes = []
    for _ in range(12):
        r = await client.post(
            "/api/v1/fake-news/analyze",
            json={"mode": "TEXT", "text": "x"},
            headers={"x-user-id": "rl"})
        codes.append(r.status_code)
    assert codes[:10] == [200] * 10
    assert codes[10:] == [429, 429]


async def test_health_is_unlimited(client, monkeypatch):
    # /health is deliberately not rate-limited (liveness probes must not
    # 429). 70 calls (> the 60/min std bucket) must all be 200.
    monkeypatch.setattr(service, "health", _fake_health)
    codes = [(await client.get("/api/v1/fake-news/health")).status_code
             for _ in range(70)]
    assert codes == [200] * 70


def test_max_body_dependency_rejects_over_cap():
    over = str(settings.max_upload_bytes + 1)
    with pytest.raises(HTTPException) as e:
        _max_body(content_length=over)
    assert e.value.status_code == 413


def test_max_body_dependency_allows_small_and_missing():
    assert _max_body(content_length="100") is None
    assert _max_body(content_length=None) is None


def test_max_body_dependency_invalid_content_length__400():
    with pytest.raises(HTTPException) as e:
        _max_body(content_length="not-a-number")
    assert e.value.status_code == 400


async def test_analyze_500_does_not_leak_internals(client, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("secret traceback path C:/keys/service_role.txt")

    monkeypatch.setattr(service, "analyze", _boom)
    r = await client.post(
        "/api/v1/fake-news/analyze",
        json={"mode": "TEXT", "text": "x"},
        headers={"x-user-id": "leak"})
    assert r.status_code == 500
    assert r.json()["detail"] == "analyze failed"
    assert "secret" not in r.text
