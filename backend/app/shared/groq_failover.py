"""Groq chat call with automatic API-key failover.

Every module that talks to Groq builds an OpenAI-compatible chat payload
and POSTs it with a Bearer key. This helper centralises the send so that a
*second* key can transparently take over when the first one is exhausted.

Primary key: ``settings.GROQ_API_KEY``.
Backup key:  ``settings.GROQ_API_KEY_2`` (optional).

On a key-exhaustion signal from the primary — HTTP 429 (rate / daily token
cap) or 401/403 (key disabled or account quota) — the *same* request is
replayed against the backup key. Any other status (a real 200, or a 400
the caller must see) is returned immediately without burning the backup.

The model is chosen by the caller via ``payload["model"]`` — both keys send
the identical model, so the backup is a drop-in for the primary.

Returns the raw ``httpx.Response`` so each caller keeps its own parsing and
error handling unchanged. When *all* keys are exhausted, the last (429/403)
response is returned, so callers' existing 429 handling still fires.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger("citadel.shared.groq")

#: statuses that mean "this key is spent — try the next one"
_EXHAUSTED = frozenset({401, 403, 429})


def groq_keys() -> list[str]:
    """Configured Groq keys in priority order (primary, then backup)."""
    return [k for k in (settings.GROQ_API_KEY, getattr(settings, "GROQ_API_KEY_2", "")) if k]


def has_backup_key() -> bool:
    return bool(getattr(settings, "GROQ_API_KEY_2", ""))


def post_chat(
    payload: dict,
    *,
    timeout: float = 30.0,
    endpoint: str | None = None,
) -> httpx.Response:
    """POST a chat-completions payload, failing over across configured keys.

    Args:
        payload: OpenAI-compatible chat body (must include ``model``).
        timeout: per-request timeout in seconds.
        endpoint: override the chat endpoint (defaults to
            ``settings.GROQ_ENDPOINT``); used by Groq Vision.

    Returns:
        The ``httpx.Response`` from the first key that did not report
        exhaustion, or the last exhausted response if every key is spent.

    Raises:
        RuntimeError: no Groq key configured at all.
        httpx.RequestError: network failure (surfaced to the caller as today).
    """
    url = endpoint or settings.GROQ_ENDPOINT
    keys = groq_keys()
    if not keys:
        raise RuntimeError("GROQ_API_KEY not configured")

    last: httpx.Response | None = None
    for idx, key in enumerate(keys):
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code not in _EXHAUSTED:
            return resp
        last = resp
        if idx + 1 < len(keys):
            log.warning(
                "Groq key #%d exhausted (HTTP %s) — failing over to backup key",
                idx + 1, resp.status_code,
            )
    log.warning("All %d Groq key(s) exhausted (last HTTP %s)", len(keys), last.status_code)
    return last  # type: ignore[return-value]  # keys non-empty => last is set
