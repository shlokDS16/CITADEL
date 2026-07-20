"""
Ticket attachment storage (Supabase Storage, bucket `tickets`).

The bucket is PRIVATE. Ticket attachments are citizen PII — photos of
homes, voice recordings, GPS traces — so per .claude/rules/data-handling.md
they are never publicly readable. Downloads go through a signed URL with a
5-minute TTL, as spec-07 requires.

Object layout follows security-baseline.md "File storage":
    <module>/<yyyy-mm-dd>/<uuid>.<ext>
The stored name is a server-generated UUID so objects cannot be
enumerated; the citizen's original filename lives in the DB row only.
"""
from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("citadel.tickets.storage")

BUCKET = "tickets"
SIGNED_URL_TTL_SECONDS = 300  # 5 min, per spec-07

#: attachment type -> the content families assert_upload_kind may return.
KIND_ALLOWLIST: dict[str, set[str]] = {
    "photo": {"image"},
    "video": {"video"},
    "voice": {"audio"},
    "file": {"pdf", "text", "image"},
}

#: extension allowlist per type — the first gate, before content sniffing.
EXT_ALLOWLIST: dict[str, set[str]] = {
    "photo": {".jpg", ".jpeg", ".png", ".webp", ".heic"},
    "video": {".mp4", ".mov", ".webm"},
    "voice": {".ogg", ".mp3", ".wav", ".webm", ".m4a"},
    "file": {".pdf", ".txt", ".jpg", ".jpeg", ".png"},
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


def sanitize_filename(name: str | None, fallback: str = "attachment") -> str:
    """Keep the citizen's filename readable but inert.

    Strips path separators and control characters so the value is safe to
    echo in a Content-Disposition header or render in the UI. This is the
    *display* name only — it never becomes the object key.
    """
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    base = _SAFE_NAME.sub("_", base)
    base = base.lstrip(".") or fallback
    return base[:255]


def extension_of(filename: str | None) -> str:
    base = sanitize_filename(filename)
    if "." not in base:
        return ""
    return "." + base.rsplit(".", 1)[-1].lower()


def guess_mime(filename: str | None, kind: str) -> str:
    guessed, _ = mimetypes.guess_type(sanitize_filename(filename))
    if guessed:
        return guessed
    return {
        "image": "image/jpeg",
        "video": "video/mp4",
        "audio": "audio/ogg",
        "pdf": "application/pdf",
        "text": "text/plain",
    }.get(kind, "application/octet-stream")


def object_key(ticket_id: str, filename: str | None) -> str:
    """Server-generated, non-enumerable object key."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ext = extension_of(filename)
    return f"{ticket_id}/{day}/{uuid.uuid4()}{ext}"


def _client():  # noqa: ANN202
    from app.database import get_supabase

    return get_supabase()


def upload(
    ticket_id: str,
    content: bytes,
    filename: Optional[str],
    content_type: str,
) -> str:
    """Upload bytes, return the storage path. Raises on failure — an
    attachment row must never point at an object that isn't there."""
    key = object_key(ticket_id, filename)
    sb = _client()
    sb.storage.from_(BUCKET).upload(
        path=key,
        file=content,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return key


def signed_url(storage_path: str, ttl: int = SIGNED_URL_TTL_SECONDS) -> Optional[str]:
    """Time-limited download URL. Returns None rather than raising — a
    broken link must not take down the whole ticket detail response."""
    if not storage_path:
        return None
    try:
        res = _client().storage.from_(BUCKET).create_signed_url(storage_path, ttl)
    except Exception as e:  # noqa: BLE001
        log.warning("signed_url failed for %s: %s", storage_path, e)
        return None
    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    return getattr(res, "signed_url", None)


def remove(storage_path: str) -> bool:
    """Best-effort delete, used to roll back an orphaned object when the
    DB row fails to insert."""
    try:
        _client().storage.from_(BUCKET).remove([storage_path])
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("storage remove failed for %s: %s", storage_path, e)
        return False


def bucket_ready() -> tuple[bool, Optional[str]]:
    """Health probe: does the bucket exist and is it private?"""
    try:
        for b in _client().storage.list_buckets():
            name = getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None)
            if name != BUCKET:
                continue
            public = getattr(b, "public", None)
            if public is None and isinstance(b, dict):
                public = b.get("public")
            if public:
                return False, f"bucket '{BUCKET}' is PUBLIC — attachments are citizen PII"
            return True, None
        return False, f"bucket '{BUCKET}' not found"
    except Exception as e:  # noqa: BLE001
        return False, f"storage unreachable: {e}"
