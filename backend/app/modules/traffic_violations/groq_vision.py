"""
Vision pass for traffic-violation classification.

Pretrained YOLO localizes vehicles/persons but can't recognize semantic events
(accidents, lane violations, red-light running). A multimodal LLM understands
the scene and labels violations from JPEG frames.

Provider selection (TV_VISION_PROVIDER env):
  - "ollama"  → local Gemma 4 (default) — zero quota, ~5-10 s/frame on CPU
  - "groq"    → Groq Llama-4-Scout — ~1 s/frame, has rate limits
  - "auto"    → try Ollama first, fall back to Groq if Ollama unavailable

Latency comparison (per frame):
  Gemma 4 (8B, Q4) on CPU:  ~6-10 s
  Gemma 4 (8B, Q4) on GPU:  ~1-2 s
  Groq Llama-4-Scout:       ~1 s   (subject to quota)

Module name kept as `groq_vision.py` for backwards-compat with the upload
pipeline imports — but the primary classifier is now local Gemma 4.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from app.config import settings
from app.shared import groq_failover

log = logging.getLogger("citadel.traffic_violations.groq_vision")

VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
GROQ_CHAT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Phase B.1 — Gemma 4 (Ollama) is the new default. Released April 2026, natively
# multimodal, no quota, runs entirely on the local host (Ollama service on :11434).
OLLAMA_MODEL = os.getenv("OLLAMA_VISION_MODEL", "gemma4:latest")
OLLAMA_HOST = os.getenv("LLM_BASE_URL", "http://localhost:11434")
# Provider order: "ollama" (default, fastest path on local hardware), "groq", or "auto"
VISION_PROVIDER = os.getenv("TV_VISION_PROVIDER", "ollama").strip().lower()

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


def _classify_with_ollama(jpeg_bytes: bytes, timeout: float = 90.0) -> dict[str, Any]:
    """
    Local multimodal classification via Ollama. Default model is Gemma 4
    (gemma4:latest, 8B, multimodal). Latency varies with hardware: ~6-10 s/frame
    on CPU, ~1-2 s on a GPU host. Zero quota, runs offline.

    Requires the Ollama service running on `LLM_BASE_URL` and the model pulled
    (e.g. `ollama pull gemma4:latest`).
    """
    try:
        import ollama  # lazy import
    except Exception:
        return {"violations": [], "scene": "(ollama python client not installed)"}

    try:
        client = ollama.Client(host=OLLAMA_HOST, timeout=timeout)
        resp = client.chat(
            model=OLLAMA_MODEL,
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
        log.warning("Ollama vision call failed: %s", e)
        return {"violations": [], "scene": f"(ollama error: {e})"}


def _classify_with_groq(jpeg_bytes: bytes, timeout: float = 30.0) -> dict[str, Any]:
    """Send one frame to Groq Vision (Llama-4-Scout). Returns parsed JSON dict."""
    if not settings.GROQ_API_KEY:
        return {"violations": [], "scene": "(no groq api key)"}

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
        r = groq_failover.post_chat(payload, timeout=timeout, endpoint=GROQ_CHAT_ENDPOINT)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            log.warning("Groq Vision returned non-JSON: %s", (content or "")[:200])
            return {"violations": [], "scene": "(groq unparseable)"}
    except httpx.HTTPStatusError as e:
        if _is_quota_or_auth_error(e):
            log.warning("Groq Vision quota/auth error (HTTP %s)", e.response.status_code)
            return {"violations": [], "scene": f"(http error: {e.response.status_code})"}
        log.warning("Groq Vision call failed: HTTP %s — %s", e.response.status_code, (e.response.text or "")[:200])
        return {"violations": [], "scene": f"(http error: {e.response.status_code})"}
    except Exception as e:
        log.warning("Groq Vision call failed: %s", e)
        return {"violations": [], "scene": f"(error: {e})"}


def classify_frame(jpeg_bytes: bytes, timeout: float = 90.0) -> dict[str, Any]:
    """
    Classify one frame. Provider order is driven by TV_VISION_PROVIDER env:
      - "ollama" (default): Gemma 4 only. If Gemma fails, returns empty payload.
      - "groq":             Groq only. If Groq fails (e.g. 429), returns empty.
      - "auto":             try Gemma 4 first; on local error fall back to Groq.

    Returns a dict matching the JSON schema in _USER_PROMPT. Never raises.
    """
    provider = VISION_PROVIDER
    if provider == "groq":
        return _classify_with_groq(jpeg_bytes, timeout=30.0)
    if provider == "auto":
        local = _classify_with_ollama(jpeg_bytes, timeout=timeout)
        scene = (local or {}).get("scene") or ""
        if "(ollama" in scene or "error:" in scene:
            log.info("Vision: Ollama unavailable, falling back to Groq")
            return _classify_with_groq(jpeg_bytes, timeout=30.0)
        return local
    # default — "ollama"
    return _classify_with_ollama(jpeg_bytes, timeout=timeout)


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
