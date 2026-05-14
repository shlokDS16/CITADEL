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


def _format_challan_caption(
    *,
    challan_id: str,
    plate: str,
    offense_label: str,
    severity: Optional[str],
    amount: int,
    due_by: str,
    issued_at: Optional[str],
    cam_id: Optional[str],
    location: Optional[str],
    legal_section: Optional[str],
    description: Optional[str],
    evidence_url: Optional[str],
) -> str:
    """
    Compose a formal challan message a citizen would actually take seriously.

    Format intent: top-of-funnel auth (CITADEL Traffic Enforcement), the
    incident facts (offense, place, time), the financial fact (fine + due
    date), the legal anchor (Motor Vehicles Act section), the action prompt
    (one of the two inline buttons below), and the disclaimer.
    """
    sev = (severity or "").upper()
    sev_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}.get(sev, "🟡")

    when = issued_at or ""
    when_human = when.replace("T", " ").split(".")[0][:19] if when else ""

    lines = [
        "🚦 *CITADEL Traffic Enforcement — Official Challan*",
        "",
        f"E-Challan No: *{challan_id}*",
        f"Issued: _{when_human}_" if when_human else None,
        "",
        "*Violation Details*",
        f"• Offense: *{offense_label}* {sev_emoji}",
        f"• Vehicle: `{plate}`",
        f"• Location: {(location + ' · ') if location else ''}{cam_id or 'Camera unknown'}",
    ]
    if description:
        d = description[:180]
        lines.append(f"• Observation: _{d}{'…' if len(description) > 180 else ''}_")
    if legal_section:
        lines.append(f"• Statutory section: _{legal_section}_")

    lines += [
        "",
        "*Penalty*",
        f"• Fine payable: *₹{amount:,}*",
        f"• Pay by: *{due_by}*",
        "",
        "Please review the captured evidence above and respond using the buttons below.",
        "_Tapping_ *Pay Now* _records your acceptance and marks this challan as PAID._",
        "_Tapping_ *Dispute* _flags the case for officer re-review; you will be contacted._",
    ]
    if evidence_url:
        lines += ["", f"[🎞 View full evidence clip]({evidence_url})"]
    lines += [
        "",
        "_If this message reached you in error, please contact the issuing office. This is an automated dispatch from the CITADEL platform on behalf of the traffic-enforcement authority._",
    ]
    return "\n".join([l for l in lines if l is not None])


def send_challan(
    chat_id: Optional[str],
    challan_id: str,
    plate: str,
    offense_label: str,
    amount: int,
    due_by: str,
    legal_section: Optional[str] = None,
    evidence_url: Optional[str] = None,
    *,
    photo_path: Optional[str] = None,
    severity: Optional[str] = None,
    issued_at: Optional[str] = None,
    cam_id: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[dict]:
    """
    Deliver a challan to the driver. If a local annotated-evidence JPG is
    available we sendPhoto so the message has the bounding-box overlay
    attached directly. Otherwise we fall back to sendMessage.

    The two inline buttons (Pay Now / Dispute) ride on either path so the
    callback flow stays identical.

    Returns Telegram message dict (includes message_id) or None when bot
    disabled. Raises TelegramError on send failure.
    """
    if not _enabled():
        log.warning("Telegram bot disabled (TELEGRAM_BOT_TOKEN missing). Skipping send.")
        return None

    target = _resolve_chat(chat_id)
    if not target:
        raise TelegramError(
            "No chat_id available — driver not registered + TELEGRAM_DEFAULT_CHAT_ID empty."
        )

    caption = _format_challan_caption(
        challan_id=challan_id, plate=plate, offense_label=offense_label,
        severity=severity, amount=amount, due_by=due_by,
        issued_at=issued_at, cam_id=cam_id, location=location,
        legal_section=legal_section, description=description,
        evidence_url=evidence_url,
    )
    # Telegram caption hard cap is 1024 chars — trim only the disclaimer if needed
    if len(caption) > 1024:
        caption = caption[:1020] + "…"

    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Pay Now",   "callback_data": f"pay:{challan_id}:yes"},
            {"text": "⚠️ Dispute",  "callback_data": f"pay:{challan_id}:no"},
        ]]
    }

    # ---- Path A: sendPhoto with the annotated evidence JPG ----
    photo_ok = False
    if photo_path:
        try:
            import os
            if os.path.exists(photo_path) and os.path.getsize(photo_path) > 0:
                with open(photo_path, "rb") as fh:
                    files = {"photo": (os.path.basename(photo_path), fh, "image/jpeg")}
                    data = {
                        "chat_id": target,
                        "caption": caption,
                        "parse_mode": "Markdown",
                        # multipart wants JSON strings for nested objects
                        "reply_markup": __import__("json").dumps(reply_markup),
                    }
                    with httpx.Client(timeout=30.0) as c:
                        r = c.post(_api("sendPhoto"), data=data, files=files)
                        body = r.json()
                if body.get("ok"):
                    photo_ok = True
                    return body["result"]
                log.warning("sendPhoto rejected — falling back to sendMessage: %s", body)
        except Exception as e:
            log.warning("sendPhoto failed (%s) — falling back to sendMessage", e)

    # ---- Path B: sendMessage (no photo / photo failed) ----
    payload = {
        "chat_id": target,
        "text": caption,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
        "reply_markup": reply_markup,
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
