"""
Thin wrapper around Telegram Bot API.

Exposes:
  - get_me()                    → bot identity (username, name)
  - get_updates()               → fetch and persist any new chat_ids users started
  - send_to_all(text, parse_mode='HTML') → broadcast to every stored chat_id
  - send_to(chat_id, text)      → targeted send
  - generate_cheerup(name, role)→ Groq one-liner reject letter

Chat IDs are stored in `telegram_chats` table after the user sends `/start` to
the bot. We never store user content, only the chat metadata.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.database import get_supabase
from app.modules.resume.parser import _coerce_json, _groq_chat

log = logging.getLogger("citadel.resume.telegram")


def _api(method: str) -> str:
    return f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def _enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


# ---------------------------------------------------------------
# Bot identity
# ---------------------------------------------------------------
def get_me() -> dict[str, Any]:
    if not _enabled():
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    try:
        r = httpx.get(_api("getMe"), timeout=10)
        r.raise_for_status()
        body = r.json()
        if body.get("ok") and body.get("result"):
            res = body["result"]
            return {"ok": True, "id": res.get("id"), "username": res.get("username"), "first_name": res.get("first_name")}
        return {"ok": False, "error": str(body)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------
# Discovery: pull updates and store chat_ids
# ---------------------------------------------------------------
def discover_chats() -> dict[str, Any]:
    if not _enabled():
        return {"ok": False, "error": "Bot not configured", "chats": []}
    try:
        r = httpx.get(_api("getUpdates"), params={"limit": 100, "timeout": 0}, timeout=10)
        r.raise_for_status()
        body = r.json()
        if not body.get("ok"):
            return {"ok": False, "error": body.get("description", "unknown"), "chats": []}
    except Exception as e:
        return {"ok": False, "error": str(e), "chats": []}

    seen: dict[str, dict] = {}
    for upd in body.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        seen[str(cid)] = {
            "chat_id": str(cid),
            "chat_type": chat.get("type"),
            "title": chat.get("title") or chat.get("first_name") or "",
            "username": chat.get("username"),
        }

    if not seen:
        return {"ok": True, "chats": list(_existing_chats()), "newly_added": 0}

    supa = get_supabase()
    rows = list(seen.values())
    try:
        supa.table("telegram_chats").upsert(rows, on_conflict="chat_id").execute()
    except Exception as e:
        log.warning("telegram_chats upsert failed: %s", e)

    return {"ok": True, "chats": list(_existing_chats()), "newly_added": len(rows)}


def _existing_chats() -> list[dict]:
    try:
        return get_supabase().table("telegram_chats").select("*").execute().data or []
    except Exception:
        return []


def list_chats() -> list[dict]:
    return _existing_chats()


# ---------------------------------------------------------------
# Send
# ---------------------------------------------------------------
def send_to(chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
    if not _enabled():
        return {"ok": False, "error": "Bot not configured"}
    try:
        r = httpx.post(
            _api("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"ok": False}
        return body
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_to_all(text: str, parse_mode: str = "HTML") -> dict[str, Any]:
    """Broadcast to every stored chat. Falls back to TELEGRAM_DEFAULT_CHAT_ID if no chats stored."""
    chats = _existing_chats()
    chat_ids = [c["chat_id"] for c in chats]
    if not chat_ids and settings.TELEGRAM_DEFAULT_CHAT_ID:
        chat_ids = [settings.TELEGRAM_DEFAULT_CHAT_ID]

    if not chat_ids:
        return {"ok": False, "error": "No Telegram chats connected. Have someone send /start to the bot first.", "delivered": 0, "total": 0}

    results = []
    delivered = 0
    for cid in chat_ids:
        res = send_to(cid, text, parse_mode)
        ok = bool(res.get("ok"))
        if ok:
            delivered += 1
        results.append({"chat_id": cid, "ok": ok, "raw": res})
    return {"ok": delivered > 0, "delivered": delivered, "total": len(chat_ids), "results": results}


# ---------------------------------------------------------------
# AI cheer-up (used in reject flow)
# ---------------------------------------------------------------
CHEERUP_PROMPT = """You write short, kind, encouraging rejection messages from a hiring team to a candidate. The tone is warm, professional, specific where possible. Keep it under 4 sentences. Do not use exclamation marks. No corporate cliches like 'we will keep your resume on file'. End with a sincere wish for their search."""


def generate_cheerup(candidate_name: str, role: str, custom_hint: str = "") -> str:
    user = f"Candidate name: {candidate_name or 'the candidate'}\nRole applied for: {role or 'the position'}"
    if custom_hint:
        user += f"\nAdditional context to weave in: {custom_hint}"
    try:
        return _groq_chat(CHEERUP_PROMPT, user, max_tokens=220, timeout=15).strip()
    except Exception as e:
        log.warning("cheerup generation failed: %s", e)
        return (
            f"Hi {candidate_name or 'there'}, thank you for applying for the {role or 'role'}. "
            "While we are not moving forward at this time, your background was genuinely interesting "
            "and we wish you the very best in your search."
        )


# ---------------------------------------------------------------
# Convenience formatters used by the router
# ---------------------------------------------------------------
def format_interview_message(candidate_name: str, role: str, when_iso: str, prep: str = "") -> str:
    nice_when = when_iso.replace("T", " ").split("+")[0]
    body = (
        f"<b>Interview scheduled</b>\n"
        f"<b>Candidate:</b> {candidate_name or '(name redacted)'}\n"
        f"<b>Role:</b> {role}\n"
        f"<b>When:</b> {nice_when}"
    )
    if prep:
        body += f"\n\n<b>Prep:</b> {prep}"
    return body


def format_advance_message(candidate_name: str, role: str, new_stage: str) -> str:
    return (
        f"<b>Pipeline update</b>\n"
        f"<b>Candidate:</b> {candidate_name or '(name redacted)'}\n"
        f"<b>Role:</b> {role}\n"
        f"<b>Moved to:</b> {new_stage.upper()}"
    )
