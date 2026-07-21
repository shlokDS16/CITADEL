"""
Per-account Telegram credential store + resolver (Phase 6).

Sits under the EXISTING send framework: modules keep calling the Telegram
Bot API the same way, they just resolve (token, chat_id) through here so a
signed-in account can receive on its own chat. Falls back to the env
defaults (TELEGRAM_BOT_TOKEN / TELEGRAM_DEFAULT_CHAT_ID) so nothing that
worked before breaks.

The bot token is a secret: it is stored via the service-role client and
NEVER returned to a client unmasked (see mask_token).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import settings

log = logging.getLogger("citadel.telegram_config")

_API_BASE = getattr(settings, "TELEGRAM_API_BASE", "https://api.telegram.org")


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable: %s", e)
        return None


def get_config(user_id: str) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (
            sb.table("telegram_settings").select("*")
            .eq("user_id", user_id).limit(1).execute()
        ).data or []
        return rows[0] if rows else None
    except Exception as e:  # noqa: BLE001
        log.debug("get_config failed: %s", e)
        return None


def upsert_config(
    user_id: str, chat_id: str, bot_token: Optional[str], enabled: bool = True,
) -> dict[str, Any]:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable")
    row: dict[str, Any] = {
        "user_id": user_id,
        "chat_id": chat_id.strip(),
        "enabled": enabled,
        # a save invalidates a prior verification until re-tested
        "verified_at": None,
    }
    # only overwrite bot_token when a non-blank one is supplied; a blank
    # keeps whatever was there (or stays null = shared bot)
    if bot_token is not None:
        tok = bot_token.strip()
        row["bot_token"] = tok or None
    existing = get_config(user_id)
    if existing:
        sb.table("telegram_settings").update(row).eq("user_id", user_id).execute()
    else:
        sb.table("telegram_settings").insert(row).execute()
    return get_config(user_id) or row


def delete_config(user_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        res = sb.table("telegram_settings").delete().eq("user_id", user_id).execute()
        return bool(res.data)
    except Exception as e:  # noqa: BLE001
        log.debug("delete_config failed: %s", e)
        return False


def mark_verified(user_id: str) -> None:
    sb = _sb()
    if sb is None:
        return
    from datetime import datetime, timezone

    try:
        sb.table("telegram_settings").update(
            {"verified_at": datetime.now(timezone.utc).isoformat()}
        ).eq("user_id", user_id).execute()
    except Exception as e:  # noqa: BLE001
        log.debug("mark_verified failed: %s", e)


def resolve_creds(user_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(token, chat_id) for this user, falling back to the env defaults.

    A user config with enabled=false is ignored (falls back). This is what
    the send helpers call so a configured account receives on its own chat.
    """
    token = settings.TELEGRAM_BOT_TOKEN or None
    chat_id = settings.TELEGRAM_DEFAULT_CHAT_ID or None
    if user_id:
        cfg = get_config(user_id)
        if cfg and cfg.get("enabled") and cfg.get("chat_id"):
            chat_id = cfg["chat_id"]
            if cfg.get("bot_token"):
                token = cfg["bot_token"]
    return token, chat_id


def mask_token(token: Optional[str]) -> Optional[str]:
    """'123456789:AAF...xyz' -> '1234…xyz'. Never expose the full secret."""
    if not token:
        return None
    if len(token) <= 10:
        return "…"
    return f"{token[:4]}…{token[-4:]}"


def send_text(token: Optional[str], chat_id: Optional[str], text: str) -> tuple[bool, str]:
    """Raw sendMessage through the existing Bot API framework.
    Returns (ok, detail). Never raises."""
    if not token:
        return False, "no bot token (platform bot not configured and none supplied)"
    if not chat_id:
        return False, "no chat_id configured"
    try:
        with httpx.Client(timeout=12) as c:
            r = c.post(
                f"{_API_BASE}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
            )
        if r.status_code == 200 and r.json().get("ok"):
            return True, "sent"
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        desc = body.get("description") or f"HTTP {r.status_code}"
        # translate the two most common setup mistakes into plain guidance
        if "chat not found" in desc.lower():
            desc = "chat not found. Message your bot once (press Start), then re-test."
        elif "unauthorized" in desc.lower():
            desc = "bot token rejected (Unauthorized). Check the token from BotFather."
        return False, desc
    except Exception as e:  # noqa: BLE001
        return False, f"network error: {e}"
