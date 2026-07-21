"""Telegram self-setup (Phase 6).

Any signed-in account (gov or citizen) can point CITADEL alerts at its own
Telegram chat, reusing the platform's shared bot or its own BotFather bot.
The delivery path is unchanged; only the recipient credentials become
per-account. See app/shared/telegram_config.py.
"""
from app.modules.telegram.router import router  # noqa: F401
