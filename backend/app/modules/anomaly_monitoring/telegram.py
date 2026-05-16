"""
Telegram dispatch for Anomaly Monitoring.

Sends a structured, operations-grade alert: severity banner, the factual
reading, the affected area + estimated population at risk, and the
first-60-minute action checklist. Reuses the project bot token /
default chat id (same bot as Traffic Violations).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import settings

log = logging.getLogger("citadel.anomaly_monitoring.telegram")


class TelegramError(Exception):
    pass


def _api(method: str) -> str:
    return f"{settings.TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def _enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN)


def _resolve_chat(chat_id: Optional[str]) -> Optional[str]:
    return chat_id or settings.TELEGRAM_DEFAULT_CHAT_ID or None


_SEV_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}


def format_alert(alert: dict[str, Any]) -> str:
    sev = (alert.get("severity") or "MEDIUM").upper()
    emoji = _SEV_EMOJI.get(sev, "🟡")
    impact = alert.get("impact") or {}
    actions = impact.get("immediate_actions") or []
    zones = impact.get("affected_zones") or []
    pop = impact.get("population_at_risk_est")

    lines = [
        f"{emoji} *CITADEL Anomaly Alert — {sev}*",
        "",
        f"*{alert.get('title')}*",
        f"`{alert.get('id')}` · {alert.get('category')}",
        "",
        "*Reading*",
        f"• {alert.get('metric')}: *{alert.get('value')} {alert.get('unit')}* "
        f"(threshold {alert.get('threshold')} {alert.get('unit')})",
        f"• Confidence: *{alert.get('confidence')}%*",
        f"• Location: {alert.get('city')} · {alert.get('zone')} "
        f"(station {alert.get('station_id')})",
        f"• Detected: {(alert.get('detected_at') or '')[:19].replace('T',' ')} UTC",
        "",
        f"_{alert.get('why')}_",
        "",
        "*Projected Impact*",
        f"• Radius: *{impact.get('impact_radius_km','?')} km* "
        f"(~{impact.get('impact_area_km2','?')} km²)",
        f"• Population at risk (est.): *{pop:,}*" if isinstance(pop, int) else "• Population at risk: n/a",
        f"• Owning dept: {impact.get('owning_department','—')}",
    ]
    if zones:
        lines.append("• Affected: " + "; ".join(zones[:3]))
    if actions:
        lines.append("")
        lines.append("*Immediate Actions (first 60 min)*")
        for i, a in enumerate(actions[:5], 1):
            lines.append(f"{i}. {a}")
    sols = impact.get("recommended_solutions") or []
    if sols:
        lines.append("")
        lines.append("*Recommended Mitigation*")
        for s in sols[:3]:
            lines.append(f"• {s}")
    lines += [
        "",
        "_Automated dispatch from the CITADEL Anomaly Monitoring module. "
        "Acknowledge & raise a work order in the console._",
    ]
    return "\n".join(lines)


def send_alert(alert: dict[str, Any], chat_id: Optional[str] = None) -> Optional[dict]:
    """
    Deliver one anomaly alert. Returns the Telegram message dict (with
    message_id) or None when the bot is disabled. Raises TelegramError on
    a hard send failure so the caller can record telegram_failed.
    """
    if not _enabled():
        log.warning("Telegram disabled (no TELEGRAM_BOT_TOKEN). Skipping.")
        return None
    target = _resolve_chat(chat_id)
    if not target:
        raise TelegramError(
            "No chat_id — TELEGRAM_DEFAULT_CHAT_ID empty and none supplied."
        )
    text = format_alert(alert)
    if len(text) > 4000:
        text = text[:3990] + "…"
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Acknowledge", "callback_data": f"anm:{alert.get('id')}:ack"},
                {"text": "🛠 Work Order",  "callback_data": f"anm:{alert.get('id')}:wo"},
            ]]
        },
    }
    with httpx.Client(timeout=15.0) as c:
        r = c.post(_api("sendMessage"), json=payload)
        body = r.json()
    if not body.get("ok"):
        raise TelegramError(f"sendMessage failed: {body}")
    return body["result"]
