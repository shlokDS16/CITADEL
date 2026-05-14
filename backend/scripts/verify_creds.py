"""
Smoke test for all 4 external credentials.
Run: python -m scripts.verify_creds   (from backend/ dir)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app.config import settings


def check(name: str, fn) -> bool:
    try:
        fn()
        print(f"  [OK]   {name}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name} -> {e}")
        return False


def main() -> int:
    print("CITADEL credential check")
    print(f"  Env: {settings.APP_ENV}")
    print(f"  Supabase URL: {settings.SUPABASE_URL}")
    print()

    results: list[bool] = []

    # 1. Supabase service role
    def supa_admin():
        r = httpx.get(
            f"{settings.SUPABASE_URL}/rest/v1/",
            headers={
                "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            },
            timeout=10,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()

    results.append(check("Supabase service role", supa_admin))

    # 2. Supabase anon
    def supa_anon():
        r = httpx.get(
            f"{settings.SUPABASE_URL}/auth/v1/health",
            headers={"apikey": settings.SUPABASE_ANON_KEY},
            timeout=10,
        )
        assert r.status_code == 200

    results.append(check("Supabase anon key", supa_anon))

    # 3. OCR Space
    def ocr_space():
        from io import BytesIO

        from PIL import Image, ImageDraw

        img = Image.new("RGB", (300, 80), "white")
        d = ImageDraw.Draw(img)
        d.text((10, 30), "TEST", fill="black")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        r = httpx.post(
            settings.OCR_SPACE_ENDPOINT,
            data={"apikey": settings.OCR_SPACE_API_KEY, "language": "eng"},
            files={"file": ("test.png", buf, "image/png")},
            timeout=30,
        )
        assert r.status_code == 200
        body = r.json()
        assert not body.get("IsErroredOnProcessing", True), body.get("ErrorMessage")

    results.append(check("OCR.space API", ocr_space))

    # 4. Groq
    def groq():
        r = httpx.post(
            settings.GROQ_ENDPOINT,
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.GROQ_CLASSIFIER_MODEL,
                "messages": [
                    {"role": "system", "content": "Reply with the single word: OK"},
                    {"role": "user", "content": "ping"},
                ],
                "max_tokens": 4,
                "temperature": 0,
            },
            timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        content = r.json()["choices"][0]["message"]["content"].strip()
        assert content, "empty response"

    results.append(check(f"Groq ({settings.GROQ_CLASSIFIER_MODEL})", groq))

    print()
    ok = sum(results)
    print(f"Result: {ok}/{len(results)} checks passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
