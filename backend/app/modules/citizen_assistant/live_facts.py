"""
Live facts injector.

The knowledge corpus deliberately does NOT hard-code mutable numbers
(fines, fees). Instead, at query time we pull the current values from the
same source of truth the rest of CITADEL uses — so when an official edits
a traffic fine, the chatbot quotes the new amount on the very next
question, with zero rebuild.

This is the requirement-2 mechanism: "if a rule is updated it is
reflected in the chatbot too."
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger("citadel.citizen_assistant.live_facts")

_CACHE: dict[str, Any] = {"ts": 0.0, "text": "", "fines": []}
_TTL = 20  # seconds — short, so an edited fine shows up almost immediately


def _fetch_fines() -> list[dict[str, Any]]:
    try:
        from app.database import get_supabase
        sb = get_supabase()
        rows = (
            sb.table("govt_fines_penalties")
            .select("violation_type, fine_amount, legal_section, description")
            .order("violation_type")
            .execute()
        ).data or []
        return rows
    except Exception as e:
        log.warning("live fines fetch failed: %s", e)
        return []


def _humanize(vt: str) -> str:
    return (vt or "").replace("_", " ").strip().title()


def get_live_facts() -> dict[str, Any]:
    """
    Returns {'text': <block to inject into the LLM prompt>, 'fines': [...]}.
    Cached for a few seconds to avoid hammering the DB on every token.
    """
    now = time.time()
    if _CACHE["text"] and (now - _CACHE["ts"]) < _TTL:
        return {"text": _CACHE["text"], "fines": _CACHE["fines"]}

    fines = _fetch_fines()
    lines = []
    if fines:
        lines.append("CURRENT TRAFFIC FINES (live from the CITADEL fines table — "
                      "authoritative, overrides any example figure in the knowledge base):")
        for f in fines:
            amt = f.get("fine_amount")
            sec = f.get("legal_section")
            seg = f"- {_humanize(f.get('violation_type'))}: Rs {amt}"
            if sec:
                seg += f" (Legal section: {sec})"
            desc = (f.get("description") or "").strip()
            if desc:
                seg += f" — {desc}"
            lines.append(seg)
    text = "\n".join(lines)
    _CACHE.update({"ts": now, "text": text, "fines": fines})
    return {"text": text, "fines": fines}


def fine_for(violation_type: str) -> dict[str, Any] | None:
    """Direct lookup used by deterministic answers / verification."""
    for f in get_live_facts()["fines"]:
        if (f.get("violation_type") or "").lower() == (violation_type or "").lower():
            return f
    return None
