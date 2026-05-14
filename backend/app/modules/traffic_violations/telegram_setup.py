"""
Telegram webhook setup helper.

Telegram requires a public HTTPS URL to deliver inline-keyboard callbacks
(Pay-Now / Dispute) from the challan messages. For local dev we tunnel
localhost:8000 via ngrok using pyngrok, then call Telegram's setWebhook with
the public URL + our internal webhook path.

Flow:
  1. POST /api/traffic-violations/telegram/setup-webhook
  2. → opens an ngrok tunnel (uses NGROK_AUTHTOKEN if set, otherwise the
       default ngrok config — `ngrok config add-authtoken <token>` once
       on the host configures it globally).
  3. → calls Telegram's setWebhook with the tunnel URL + the internal
       webhook path.
  4. → returns {ok, public_url, webhook_path, registered}.

After this, every Pay-Now / Dispute click in a challan message is delivered
to our /telegram/webhook endpoint, which already routes to
service.handle_telegram_callback.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from app.config import settings

log = logging.getLogger("citadel.traffic_violations.telegram_setup")

WEBHOOK_PATH = "/api/traffic-violations/telegram/webhook"

# Module-level state — one tunnel per backend process.
_NGROK_TUNNEL = None
_REGISTERED_URL: Optional[str] = None


def _telegram_api(method: str) -> str:
    base = settings.TELEGRAM_API_BASE.rstrip("/")
    return f"{base}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"


def _open_tunnel(local_port: int = 8000) -> str:
    """Open an ngrok HTTPS tunnel; return the public URL."""
    global _NGROK_TUNNEL
    try:
        from pyngrok import ngrok, conf
    except Exception as e:
        raise RuntimeError(f"pyngrok not installed: {e}")

    authtoken = os.getenv("NGROK_AUTHTOKEN")
    if authtoken:
        ngrok.set_auth_token(authtoken)

    # Close any prior tunnel from this process to avoid orphans
    if _NGROK_TUNNEL is not None:
        try:
            ngrok.disconnect(_NGROK_TUNNEL.public_url)
        except Exception:
            pass
        _NGROK_TUNNEL = None

    _NGROK_TUNNEL = ngrok.connect(local_port, "http", bind_tls=True)
    return _NGROK_TUNNEL.public_url


def _close_tunnel() -> None:
    global _NGROK_TUNNEL
    try:
        from pyngrok import ngrok
    except Exception:
        return
    if _NGROK_TUNNEL is not None:
        try:
            ngrok.disconnect(_NGROK_TUNNEL.public_url)
        except Exception:
            pass
        _NGROK_TUNNEL = None


def _set_telegram_webhook(public_url: str) -> dict[str, Any]:
    """Call Telegram's setWebhook with the supplied public URL + our path."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not configured")
    target = public_url.rstrip("/") + WEBHOOK_PATH
    with httpx.Client(timeout=15.0) as c:
        r = c.post(_telegram_api("setWebhook"), json={
            "url": target,
            "allowed_updates": ["callback_query"],
        })
        body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram setWebhook failed: {body}")
    return {"url": target, "telegram_response": body}


def _delete_telegram_webhook() -> dict[str, Any]:
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "reason": "no token"}
    with httpx.Client(timeout=15.0) as c:
        r = c.post(_telegram_api("deleteWebhook"))
        return r.json()


def setup_webhook(local_port: int = 8000) -> dict[str, Any]:
    """Open tunnel + register webhook. Idempotent across calls in one process."""
    global _REGISTERED_URL
    public_url = _open_tunnel(local_port=local_port)
    log.info("ngrok tunnel: %s -> http://localhost:%d", public_url, local_port)
    result = _set_telegram_webhook(public_url)
    _REGISTERED_URL = result["url"]
    log.info("Telegram webhook registered: %s", _REGISTERED_URL)
    return {
        "ok": True,
        "public_url": public_url,
        "webhook_url": _REGISTERED_URL,
        "telegram_response": result["telegram_response"],
    }


def teardown_webhook() -> dict[str, Any]:
    """De-register the webhook with Telegram + close the tunnel."""
    global _REGISTERED_URL
    tg = _delete_telegram_webhook()
    _close_tunnel()
    _REGISTERED_URL = None
    return {"ok": True, "telegram_response": tg}


def webhook_status() -> dict[str, Any]:
    """Inspect current tunnel + Telegram webhook state."""
    public_url = _NGROK_TUNNEL.public_url if _NGROK_TUNNEL else None
    tg_info = None
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            with httpx.Client(timeout=8.0) as c:
                r = c.get(_telegram_api("getWebhookInfo"))
                tg_info = r.json()
        except Exception as e:
            tg_info = {"ok": False, "error": str(e)}
    return {
        "tunnel_open": public_url is not None,
        "public_url": public_url,
        "registered_webhook": _REGISTERED_URL,
        "telegram_getWebhookInfo": tg_info,
    }
