"""
Layer 4 — LLM rationale (Groq llama-3.3-70b via LiteLLM).

Production systems do NOT run an LLM on every post (too slow / expensive,
and Groq's free tier is 100k tokens/day). This layer is the waterfall's
top step: it only runs for **high-risk or ambiguous** content (gated in
service by FN_HIGH_RISK_THRESHOLD / UNCERTAIN) and produces a
human-readable rationale for moderators — it does NOT override the
fact-checked verdict from Layer 3 (that stays authoritative).

Reuses the project LLM-resilience pattern from citizen_assistant
(Groq → Gemini → Ollama, honest _QuotaExhausted) so a drained Groq
quota degrades to an honest "rationale unavailable" rather than a
vague failure — the verdict itself still stands (Layers 1-3 are local).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from app.config import settings

log = logging.getLogger("citadel.fake_news.llm_rationale")

_FN_MODEL = os.getenv("FN_LLM_MODEL", f"groq/{settings.GROQ_CLASSIFIER_MODEL}")
_MAX_INPUT = 1400


class _QuotaExhausted(Exception):
    def __init__(self, retry_hint: str = ""):
        super().__init__("LLM quota exhausted")
        self.retry_hint = retry_hint


def _provider_chain() -> list[str]:
    chain = [_FN_MODEL]
    gkey = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gkey:
        os.environ.setdefault("GEMINI_API_KEY", gkey)
        chain.append(os.getenv("CITIZEN_GEMINI_MODEL", "gemini/gemini-1.5-flash"))
    try:
        import httpx as _hx

        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        _hx.get(base + "/api/tags", timeout=0.6)
        chain.append(f"ollama/{os.getenv('OLLAMA_MODEL', 'llama3.2')}")
    except Exception:  # noqa: BLE001
        pass
    return chain


def _is_rate_limit(exc: Exception) -> bool:
    s = (str(exc) or "").lower()
    return ("ratelimit" in s or "rate_limit" in s or "rate limit" in s
            or "quota" in s or "tokens per day" in s or "tpd" in s
            or "429" in s)


def _retry_hint(exc: Exception) -> str:
    m = re.search(r"try again in ([0-9]+m[0-9.]+s|[0-9.]+s)", str(exc) or "")
    return m.group(1) if m else ""


def _llm(prompt: str, max_tokens: int = 360, temperature: float = 0.2) -> str:
    import litellm

    litellm.drop_params = True
    msgs = [{"role": "user", "content": prompt}]
    chain = _provider_chain()
    all_rate_limited = True
    quota_hint = ""
    last_err: Exception | None = None
    for model in chain:
        for attempt in range(2):
            try:
                r = litellm.completion(
                    model=model, messages=msgs,
                    temperature=temperature if attempt == 0 else 0.3,
                    max_tokens=max_tokens)
                txt = (r.choices[0].message.content or "").strip()
                if txt:
                    return txt
                all_rate_limited = False
            except Exception as e:  # noqa: BLE001
                last_err = e
                if _is_rate_limit(e):
                    quota_hint = quota_hint or _retry_hint(e)
                    break
                all_rate_limited = False
                time.sleep(0.5 * (attempt + 1))
    if last_err:
        log.warning("LLM rationale providers failed (%d): %s", len(chain), last_err)
    if all_rate_limited and last_err is not None:
        raise _QuotaExhausted(quota_hint)
    return ""


_PROMPT = """You are a misinformation analyst assisting a human moderator. \
Given a piece of content and the automated signals already computed, write a \
concise rationale. Do NOT change the verdict — explain it.

CONTENT (excerpt):
\"\"\"{excerpt}\"\"\"

AUTOMATED SIGNALS:
- Verdict: {verdict} (confidence {confidence})
- Risk score: {risk}
- Red flags: {flags}
- Claim checks: {claims}

Return STRICT JSON only, no prose around it:
{{"central_claim": "<the single main factual claim, one sentence>", \
"rationale": "<2-4 sentences: why this verdict, citing the signals/claims>", \
"recommendation": "<one short line for the moderator>"}}"""


def rationale(*, excerpt: str, verdict: str, confidence: float, risk: float,
              red_flags: list[str], claims: list[dict]) -> dict:
    """Human-readable rationale for high-risk/ambiguous content.

    Never raises. On drained quota returns quota_exhausted=True (the verdict
    still stands from Layers 1-3 — those are local, not quota-bound).
    """
    claim_brief = "; ".join(
        f"{c.get('verdict')} ({c.get('text', '')[:80]})" for c in claims[:3]
    ) or "none extracted"
    prompt = _PROMPT.format(
        excerpt=(excerpt or "")[:_MAX_INPUT],
        verdict=verdict, confidence=round(confidence, 2), risk=round(risk, 2),
        flags="; ".join(red_flags[:6]) or "none",
        claims=claim_brief,
    )
    try:
        raw = _llm(prompt)
    except _QuotaExhausted as q:
        return {"available": False, "quota_exhausted": True,
                "retry_hint": q.retry_hint, "model": _FN_MODEL}
    if not raw:
        return {"available": False, "quota_exhausted": False, "model": _FN_MODEL}
    data = _extract_json(raw)
    if not data:
        # model answered but not as JSON — still useful as free text
        return {"available": True, "quota_exhausted": False, "model": _FN_MODEL,
                "central_claim": "", "rationale": raw[:600], "recommendation": ""}
    return {
        "available": True, "quota_exhausted": False, "model": _FN_MODEL,
        "central_claim": str(data.get("central_claim", ""))[:300],
        "rationale": str(data.get("rationale", ""))[:800],
        "recommendation": str(data.get("recommendation", ""))[:300],
    }


def _extract_json(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except Exception:  # noqa: BLE001
        return None
