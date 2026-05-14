"""
Supabase Storage helpers for traffic violation clips + frames.

Bucket: `incidents` (public, 50 MB limit, mp4 / mov / avi / jpg / png).
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from app.config import settings
from app.database import get_supabase

log = logging.getLogger("citadel.traffic_violations.storage")

BUCKET = "incidents"


def _content_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".webm": "video/webm",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(ext, "application/octet-stream")


def upload_local_file(local_path: str, dest_path: Optional[str] = None) -> Optional[str]:
    """
    Upload a local file to the incidents bucket. Returns public URL or None on failure.
    `dest_path` defaults to a uuid-named file preserving the extension.
    """
    sb = get_supabase()
    p = Path(local_path)
    if not p.exists():
        log.warning("upload_local_file: missing %s", local_path)
        return None

    if dest_path is None:
        dest_path = f"{uuid.uuid4().hex}{p.suffix}"

    try:
        with open(p, "rb") as f:
            data = f.read()
        sb.storage.from_(BUCKET).upload(
            path=dest_path,
            file=data,
            file_options={"content-type": _content_type(p.name), "upsert": "true"},
        )
        return sb.storage.from_(BUCKET).get_public_url(dest_path)
    except Exception as e:
        log.warning("upload_local_file failed: %s", e)
        return None


def upload_bytes(data: bytes, dest_path: str) -> Optional[str]:
    """Upload raw bytes (e.g. JPEG frame) to the incidents bucket."""
    sb = get_supabase()
    try:
        sb.storage.from_(BUCKET).upload(
            path=dest_path,
            file=data,
            file_options={"content-type": _content_type(dest_path), "upsert": "true"},
        )
        return sb.storage.from_(BUCKET).get_public_url(dest_path)
    except Exception as e:
        log.warning("upload_bytes failed: %s", e)
        return None
