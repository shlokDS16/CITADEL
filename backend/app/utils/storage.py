"""
Supabase Storage helpers — uploads, signed downloads, deletes.
Two buckets:
  - `documents`  → originals (uploaded by users)
  - `processed`  → derived artifacts (redacted text, regenerated PDFs, etc.)
"""
from __future__ import annotations

import logging
import mimetypes
from datetime import datetime
from uuid import uuid4

from app.config import settings
from app.database import get_supabase

log = logging.getLogger("citadel.storage")

DOCUMENTS_BUCKET = settings.SUPABASE_BUCKET_DOCUMENTS
PROCESSED_BUCKET = settings.SUPABASE_BUCKET_PROCESSED


def _today_prefix() -> str:
    return datetime.utcnow().strftime("%Y/%m/%d")


def storage_path_for(filename: str) -> str:
    """Make a non-guessable path: documents/2026/05/02/<uuid>.<ext>"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"{_today_prefix()}/{uuid4().hex}.{ext}"


def upload_original(content: bytes, filename: str) -> tuple[str, str]:
    """
    Upload raw file bytes into the `documents` bucket.
    Returns (storage_path, mime_type).
    """
    path = storage_path_for(filename)
    mime, _ = mimetypes.guess_type(filename)
    mime = mime or "application/octet-stream"

    supa = get_supabase()
    supa.storage.from_(DOCUMENTS_BUCKET).upload(
        path=path,
        file=content,
        file_options={"content-type": mime, "upsert": "false"},
    )
    return path, mime


def upload_processed(content: bytes, filename: str, mime: str = "application/octet-stream") -> str:
    """Upload a derived artifact (redacted PDF, regenerated DOCX) to `processed`."""
    path = storage_path_for(filename)
    get_supabase().storage.from_(PROCESSED_BUCKET).upload(
        path=path,
        file=content,
        file_options={"content-type": mime, "upsert": "false"},
    )
    return path


def signed_url(bucket: str, path: str, expires_seconds: int = 300) -> str:
    """Pre-signed download URL (default 5 min TTL — ref security-baseline.md)."""
    res = get_supabase().storage.from_(bucket).create_signed_url(path, expires_seconds)
    # supabase-py returns dict with 'signedURL' or 'signedUrl' depending on version
    return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url", "")


def download_bytes(bucket: str, path: str) -> bytes:
    return get_supabase().storage.from_(bucket).download(path)


def delete_object(bucket: str, path: str) -> None:
    try:
        get_supabase().storage.from_(bucket).remove([path])
    except Exception as e:  # pragma: no cover
        log.warning("delete failed bucket=%s path=%s: %s", bucket, path, e)
