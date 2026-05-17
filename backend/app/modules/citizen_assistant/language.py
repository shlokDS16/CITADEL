"""
Language detection.

Dynamic, model-based detection so the assistant can answer in whatever
language the citizen wrote in (requirement 3) and the frontend can pick a
matching voice for speech output. One cheap Groq call; resilient default
to English on any failure.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("citadel.citizen_assistant.language")

# name -> BCP-47 tag used by the browser SpeechSynthesis/Recognition APIs
_BCP47 = {
    "english": "en-IN", "hindi": "hi-IN", "bengali": "bn-IN", "tamil": "ta-IN",
    "telugu": "te-IN", "marathi": "mr-IN", "gujarati": "gu-IN", "kannada": "kn-IN",
    "malayalam": "ml-IN", "punjabi": "pa-IN", "odia": "or-IN", "urdu": "ur-IN",
    "assamese": "as-IN", "spanish": "es-ES", "french": "fr-FR", "german": "de-DE",
    "arabic": "ar-SA", "chinese": "zh-CN", "japanese": "ja-JP", "portuguese": "pt-BR",
    "russian": "ru-RU",
}


def detect(text: str) -> dict[str, Any]:
    """Return {language, bcp47, confidence}. Defaults to English."""
    t = (text or "").strip()
    if not t:
        return {"language": "English", "bcp47": "en-IN", "confidence": 0}

    # Fast script heuristic first (covers the common Indian scripts w/o a call)
    if re.search(r"[ऀ-ॿ]", t):  return _mk("Hindi")
    if re.search(r"[ঀ-৿]", t):  return _mk("Bengali")
    if re.search(r"[஀-௿]", t):  return _mk("Tamil")
    if re.search(r"[ఀ-౿]", t):  return _mk("Telugu")
    if re.search(r"[઀-૿]", t):  return _mk("Gujarati")
    if re.search(r"[ಀ-೿]", t):  return _mk("Kannada")
    if re.search(r"[ഀ-ൿ]", t):  return _mk("Malayalam")
    if re.search(r"[਀-੿]", t):  return _mk("Punjabi")
    if re.search(r"[؀-ۿ]", t):  return _mk("Urdu")

    # Latin script could be English or romanised/other — ask the model.
    try:
        from app.modules.citizen_assistant.pageindex_engine import PI_MODEL
        from pageindex.utils import llm_completion
        prompt = (
            "Identify the natural language of the following user message. "
            'Reply ONLY as compact JSON: {"language":"<English name>"}. '
            "If it is romanised Hindi/Indian language, name that language.\n\n"
            f"Message: {t[:400]}"
        )
        raw = llm_completion(PI_MODEL, prompt)
        m = re.search(r"\{.*\}", raw or "", re.S)
        if m:
            name = (json.loads(m.group(0)).get("language") or "English").strip()
            return _mk(name)
    except Exception as e:
        log.info("language detect fell back to English: %s", e)
    return _mk("English")


def _mk(name: str) -> dict[str, Any]:
    key = (name or "English").strip().lower()
    return {
        "language": name.strip().title() if name else "English",
        "bcp47": _BCP47.get(key, "en-IN"),
        "confidence": 90,
    }
