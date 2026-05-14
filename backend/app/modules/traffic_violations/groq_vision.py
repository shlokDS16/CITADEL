"""
Groq Vision pass for traffic-violation classification.

Pretrained YOLO localizes vehicles/persons but can't recognize semantic events
(accidents, lane violations, red-light running). Groq's Llama-4-Scout (17B
multimodal) understands the scene and labels violations from JPEG frames.

Per uploaded video: sample 4-8 evenly-spaced keyframes → ship each to
Llama-4-Scout with a structured JSON prompt → merge results with the YOLO+tracker
detections in `pipeline.detect_in_video()`.

Latency: ~1 s per frame on Groq. 6 keyframes ≈ 6 s extra per upload.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("citadel.traffic_violations.groq_vision")

VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = (
    "You are a traffic enforcement vision assistant analyzing a road camera frame. "
    "Reply ONLY with valid JSON in the requested schema."
)

_USER_PROMPT = """Analyze this frame from a road/traffic camera. List every traffic violation or notable incident you can see.

Reply with JSON exactly matching this schema:
{
  "violations": [
    {
      "type": "<one of: accident | no_helmet | speeding | wrong_lane | red_light | no_seatbelt | illegal_parking | rash_driving | lane_violation | overload | overturned | debris>",
      "severity": "<one of: low | medium | high | critical>",
      "description": "<one-sentence factual description>",
      "plate_visible": <true|false>
    }
  ],
  "scene": "<one-sentence overall scene description>"
}

Severity rubric:
  critical = collision / vehicle overturned / fire / injury / pedestrian hit
  high     = imminent danger, accident in progress, rider on the ground
  medium   = clear violation (no helmet on rider, wrong lane, signal jump)
  low      = minor / ambiguous

Only include violations that are ACTUALLY VISIBLE. Do NOT speculate. If the frame shows normal traffic, return {"violations": [], "scene": "..."}.
"""


def _encode_jpeg_b64(jpeg_bytes: bytes) -> str:
    return base64.b64encode(jpeg_bytes).decode("ascii")


def _is_quota_or_auth_error(exc: Exception) -> bool:
    """Detect Groq quota/rate/auth failures that warrant Ollama fallback."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 402, 403, 429):
            return True
        body = (exc.response.text or "").lower()
        return any(k in body for k in ("quota", "rate limit", "rate_limit", "exhausted", "exceeded"))
    return False


def _classify_with_ollama(jpeg_bytes: bytes) -> dict[str, Any]:
    """
    Local-LLM fallback via Ollama LLaVa-style multimodal models.
    Slower (~5-10s per frame on CPU) but free + offline.
    Requires `ollama pull llava` (or llama3.2-vision) on the host.
    """
    try:
        import ollama  # lazy import
    except Exception:
        return {"violations": [], "scene": "(ollama not installed)"}

    model = os.getenv("OLLAMA_VISION_MODEL", "llava")
    try:
        client = ollama.Client(host=os.getenv("LLM_BASE_URL", "http://localhost:11434"))
        resp = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT, "images": [jpeg_bytes]},
            ],
            options={"temperature": 0.1, "num_predict": 500},
            format="json",
        )
        content = (resp.get("message") or {}).get("content") or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            log.warning("Ollama vision returned non-JSON: %s", content[:200])
            return {"violations": [], "scene": "(ollama unparseable)"}
    except Exception as e:
        log.warning("Ollama vision fallback failed: %s", e)
        return {"violations": [], "scene": f"(ollama error: {e})"}


def classify_frame(jpeg_bytes: bytes, timeout: float = 30.0) -> dict[str, Any]:
    """
    Send one frame to Groq Vision. Returns parsed dict matching the JSON schema.
    On quota/auth errors → fall back to local Ollama LLaVa.
    On any other error → return empty payload (never raises).
    """
    if not settings.GROQ_API_KEY:
        # No Groq key at all → try Ollama directly
        return _classify_with_ollama(jpeg_bytes)

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{_encode_jpeg_b64(jpeg_bytes)}"
                        },
                    },
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.post(
                GROQ_CHAT_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                json=payload,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            log.warning("Groq Vision returned non-JSON: %s", (content or "")[:200])
            return {"violations": [], "scene": "(unparseable response)"}
    except httpx.HTTPStatusError as e:
        if _is_quota_or_auth_error(e):
            log.warning("Groq Vision quota/auth error (HTTP %s) → falling back to Ollama", e.response.status_code)
            return _classify_with_ollama(jpeg_bytes)
        log.warning("Groq Vision call failed: HTTP %s — %s", e.response.status_code, (e.response.text or "")[:200])
        return {"violations": [], "scene": f"(http error: {e.response.status_code})"}
    except Exception as e:
        log.warning("Groq Vision call failed: %s", e)
        return {"violations": [], "scene": f"(error: {e})"}


def classify_keyframes(
    keyframes: list[tuple[int, bytes]],
) -> list[dict[str, Any]]:
    """
    Classify several (frame_idx, jpeg_bytes) tuples. Returns a flat list of:
        {frame_idx, type, severity, description, plate_visible, scene}
    One entry per violation. Tolerant of failures — silent skip.
    """
    out: list[dict[str, Any]] = []
    for frame_idx, jpeg in keyframes:
        result = classify_frame(jpeg)
        scene = (result or {}).get("scene")
        for v in (result or {}).get("violations") or []:
            vtype = (v.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
            if not vtype:
                continue
            out.append({
                "frame_idx": frame_idx,
                "type": vtype,
                "severity": (v.get("severity") or "medium").lower(),
                "description": v.get("description") or "",
                "plate_visible": bool(v.get("plate_visible")),
                "scene": scene,
            })
    return out
