"""HTTP layer: happy path + 4xx (validation / spoof) + rate-limit 429.

Heavy collaborators are monkeypatched so NO Groq token, NO model
download, NO Supabase call happens (testing.md: mock the boundary)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.modules.fake_news import schemas, service

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
