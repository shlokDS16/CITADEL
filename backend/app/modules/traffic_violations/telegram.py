"""
Telegram bot — Traffic Violations module.

Sends:
  - Challan delivery to drivers with inline pay-yes / dispute buttons (Phase 3).
  - Offender nags with running tally (Phase 5).

Bot: TELEGRAM_BOT_TOKEN env (@citadel2005_bot in current config).
Driver chat-id lookup: tv_drivers.telegram_chat_id  →  TELEGRAM_DEFAULT_CHAT_ID fallback.

Inbound callback flow (Phase 4 will wire the webhook):
  callback_data format: "pay:{challan_id}:yes" | "pay:{challan_id}:no"
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger("citadel.traffic_violations.telegram")


class TelegramError(Exception):
    pass


def _api(method: str) -> str:
    return f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def _enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def _resolve_chat(chat_id: Optional[str]) -> Optional[str]:
    """Use supplied chat_id or fall back to the configured default (demo)."""
    if chat_id:
        return chat_id
    if settings.TELEGRAM_DEFAULT_CHAT_ID:
        return settings.TELEGRAM_DEFAULT_CHAT_ID
    return None


def send_challan(
    chat_id: Optional[str],
    challan_id: str,
    plate: str,
    offense_label: str,
    amount: int,
    due_by: str,
    legal_section: Optional[str] = None,
    evidence_url: Optional[str] = None,
) -> Optional[dict]:
    """
    Deliver a challan with pay-yes / dispute inline keyboard.
    Returns Telegram message dict (includes message_id) or None when bot disabled.
    Raises TelegramError on send failure.
    """
    if not _enabled():
        log.warning("Telegram bot disabled (TELEGRAM_BOT_TOKEN missing). Skipping send.")
        return None

    target = _resolve_chat(chat_id)
    if not target:
        raise TelegramError(
            "No chat_id available — driver not registered + TELEGRAM_DEFAULT_CHAT_ID empty."
        )

    lines = [
        f"\U0001f6a8 *Traffic Challan Issued* — *{challan_id}*",
        "",
        f"Vehicle: `{plate}`",
        f"Offense: *{offense_label}*",
        f"Fine: ₹*{amount:,}*",
        f"Due by: *{due_by}*",
    ]
    if legal_section:
        lines.append(f"Section: _{legal_section}_")
    if evidence_url:
        lines.append("")
        lines.append(f"[\U0001f3a5 View Evidence Clip]({evidence_url})")
    lines.append("")
    lines.append("Tap a button below:")

    payload = {
        "chat_id": target,
        "text": "\n".join(lines),
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Pay Now",   "callback_data": f"pay:{challan_id}:yes"},
                    {"text": "⚠️ Dispute", "callback_data": f"pay:{challan_id}:no"},
                ]
            ]
        },
    }

    with httpx.Client(timeout=15.0) as c:
        r = c.post(_api("sendMessage"), json=payload)
        body = r.json()
    if not body.get("ok"):
        raise TelegramError(f"Telegram sendMessage failed: {body}")
    return body["result"]


def send_offender_nag(
    chat_id: Optional[str],
    plate: str,
    driver_name: Optional[str],
    offense_count: int,
    total_pending: int,
) -> Optional[dict]:
    """Notify a repeat offender of running tally (Phase 5)."""
    if not _enabled():
        return None
    target = _resolve_chat(chat_id)
    if not target:
        raise TelegramError("No chat_id and no demo default configured.")

    name_line = f", {driver_name}" if driver_name else ""
    text = (
        f"\U0001f4cc Hello{name_line} — reminder from CITADEL Traffic.\n\n"
        f"Vehicle `{plate}` has *{offense_count} pending violations* "
        f"with total outstanding fines of ₹*{total_pending:,}*.\n\n"
        "Please clear your dues to avoid registration suspension."
    )
    with httpx.Client(timeout=15.0) as c:
        r = c.post(_api("sendMessage"),
                   json={"chat_id": target, "text": text, "parse_mode": "Markdown"})
        body = r.json()
    if not body.get("ok"):
        raise TelegramError(f"Telegram nag failed: {body}")
    return body["result"]


def parse_pay_callback(callback_data: str) -> Optional[tuple[str, bool]]:
    """Parse 'pay:CH-7823:yes' / 'pay:CH-7823:no' → (challan_id, will_pay)."""
    parts = (callback_data or "").split(":")
    if len(parts) != 3 or parts[0] != "pay":
        return None
    return parts[1], (parts[2] == "yes")


def answer_callback(callback_query_id: str, text: str = "") -> None:
    """Ack an inline button press so Telegram stops spinning the loader."""
    if not _enabled():
        return
    try:
        with httpx.Client(timeout=8.0) as c:
            c.post(_api("answerCallbackQuery"),
                   json={"callback_query_id": callback_query_id, "text": text})
    except Exception as e:
        log.debug("answer_callback failed: %s", e)
