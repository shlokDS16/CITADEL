"""
Telegram settings endpoints — /api/v1/telegram/*.

Authenticated (any role). The bot token is never returned unmasked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.shared import telegram_config as tg

log = logging.getLogger("citadel.telegram.router")
router = APIRouter()
_TAG = "telegram"


def _uid(request: Request) -> str:
    claims = getattr(request.state, "user", None)
    if not claims or not claims.get("sub"):
        raise HTTPException(status_code=401, detail="authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    return str(claims["sub"])


class TelegramConfigIn(BaseModel):
    chat_id: str = Field(..., min_length=1, max_length=64,
                         description="Your numeric Telegram chat id (from @userinfobot).")
    bot_token: Optional[str] = Field(
        default=None, max_length=100,
        description="Optional. Leave blank to use the platform's shared CITADEL bot.")
    enabled: bool = True


class TelegramConfigOut(BaseModel):
    configured: bool
    enabled: bool = False
    chat_id: Optional[str] = None
    uses_own_bot: bool = False
    bot_token_masked: Optional[str] = None
    verified_at: Optional[datetime] = None
    platform_bot_available: bool = Field(
        ..., description="True when the platform's shared bot token is set server-side.")
    platform_bot_username: Optional[str] = None


def _shape(uid: str) -> dict[str, Any]:
    cfg = tg.get_config(uid)
    platform_bot = bool(settings.TELEGRAM_BOT_TOKEN)
    if not cfg:
        return {
            "configured": False, "platform_bot_available": platform_bot,
            "platform_bot_username": getattr(settings, "TELEGRAM_BOT_USERNAME", None) or "citadel2005_bot",
        }
    return {
        "configured": True,
        "enabled": bool(cfg.get("enabled")),
        "chat_id": cfg.get("chat_id"),
        "uses_own_bot": bool(cfg.get("bot_token")),
        "bot_token_masked": tg.mask_token(cfg.get("bot_token")),
        "verified_at": cfg.get("verified_at"),
        "platform_bot_available": platform_bot,
        "platform_bot_username": getattr(settings, "TELEGRAM_BOT_USERNAME", None) or "citadel2005_bot",
    }


@router.get("/v1/telegram/config", response_model=TelegramConfigOut, tags=[_TAG],
            summary="Current account's Telegram config (token masked)")
async def get_config(request: Request) -> TelegramConfigOut:
    uid = _uid(request)
    return TelegramConfigOut(**await run_in_threadpool(_shape, uid))


@router.put("/v1/telegram/config", response_model=TelegramConfigOut, tags=[_TAG],
            summary="Save chat id (+ optional own bot token)")
async def put_config(request: Request, payload: TelegramConfigIn) -> TelegramConfigOut:
    uid = _uid(request)
    if not payload.bot_token and not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=400,
                            detail="No platform bot configured — you must supply your own bot token.")
    try:
        await run_in_threadpool(tg.upsert_config, uid, payload.chat_id, payload.bot_token, payload.enabled)
    except Exception as e:  # noqa: BLE001
        log.exception("telegram save failed")
        raise HTTPException(status_code=500, detail=str(e))
    return TelegramConfigOut(**await run_in_threadpool(_shape, uid))


@router.delete("/v1/telegram/config", status_code=204, tags=[_TAG],
               summary="Disconnect Telegram for this account")
async def delete_config(request: Request) -> None:
    await run_in_threadpool(tg.delete_config, _uid(request))


class TestOut(BaseModel):
    ok: bool
    detail: str


@router.post("/v1/telegram/test", response_model=TestOut, tags=[_TAG],
             summary="Send a live test alert to your Telegram (proves delivery)")
async def send_test(request: Request) -> TestOut:
    uid = _uid(request)
    claims = getattr(request.state, "user", {})
    token, chat_id = await run_in_threadpool(tg.resolve_creds, uid)
    if not tg.get_config(uid):
        raise HTTPException(status_code=400, detail="Save your chat id first, then send a test.")
    who = claims.get("username") or "operator"
    text = (
        "<b>CITADEL</b> — Telegram connected ✅\n"
        f"You are now receiving alerts as <b>{who}</b>.\n"
        f"<i>{datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}</i>\n\n"
        "Challans, anomaly alerts and other notifications you trigger will arrive here."
    )
    ok, detail = await run_in_threadpool(tg.send_text, token, chat_id, text)
    if ok:
        await run_in_threadpool(tg.mark_verified, uid)
    return TestOut(ok=ok, detail=detail)
