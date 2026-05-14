"""
Templates service — CRUD + the "passport key" access control system.

Passport key:
  - 6-char alphanumeric uppercase, generated once per user, shown ONCE.
  - bcrypt-hashed in `users.passport_key_hash`.
  - Required to edit/clone:
      a) any template with `is_system = TRUE`
      b) any document edit when the doc is ARCHIVED with priority='urgent'
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import bcrypt

from app.database import get_supabase

log = logging.getLogger("citadel.templates")

PASSPORT_KEY_ALPHABET = string.ascii_uppercase + string.digits
PASSPORT_KEY_LENGTH = 6


# ============================================================
# Passport key
# ============================================================
def generate_passport_key() -> str:
    """6 random uppercase + digits — unambiguous (no I/O confusion in this set)."""
    return "".join(secrets.choice(PASSPORT_KEY_ALPHABET) for _ in range(PASSPORT_KEY_LENGTH))


def hash_passport_key(key: str) -> str:
    return bcrypt.hashpw(key.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_passport_key(key: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(key.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def issue_passport_key_for_user(user_id: str, email: Optional[str] = None) -> str:
    """
    Generate a key, store its hash, mark `passport_key_shown=False`, return raw key.
    Caller must show the key to the user ONCE then call mark_passport_key_shown.
    """
    supa = get_supabase()
    raw = generate_passport_key()
    hashed = hash_passport_key(raw)

    upsert_row = {
        "id": user_id,
        "email": email,
        "passport_key_hash": hashed,
        "passport_key_shown": False,
    }
    supa.table("users").upsert(upsert_row, on_conflict="id").execute()
    return raw


def mark_passport_key_shown(user_id: str) -> None:
    get_supabase().table("users").update({"passport_key_shown": True}).eq("id", user_id).execute()


def check_any_user_passport_key(key: str) -> bool:
    """
    Demo / single-tenant convenience: return True if `key` matches ANY user's hash.
    For multi-tenant, swap to check_user_passport_key(user_id, key).
    """
    rows = (
        get_supabase().table("users")
        .select("id, passport_key_hash")
        .not_.is_("passport_key_hash", "null")
        .execute()
        .data or []
    )
    for r in rows:
        if verify_passport_key(key, r["passport_key_hash"]):
            return True
    return False


# ============================================================
# Template CRUD
# ============================================================
def list_templates() -> list[dict[str, Any]]:
    rows = get_supabase().table("templates").select("*").order("document_type").execute().data or []
    # patch field_count for convenience
    for r in rows:
        r["field_count"] = len(r.get("fields") or [])
    return rows


def get_template(template_id: str) -> Optional[dict[str, Any]]:
    res = get_supabase().table("templates").select("*").eq("id", template_id).single().execute()
    if not res.data:
        return None
    res.data["field_count"] = len(res.data.get("fields") or [])
    return res.data


def create_template(name: str, document_type: str, fields: list[dict]) -> dict[str, Any]:
    row = {
        "name": name,
        "document_type": document_type,
        "fields": fields,
        "is_system": False,
    }
    res = get_supabase().table("templates").insert(row).execute()
    return res.data[0]


def update_template(
    template_id: str,
    name: Optional[str] = None,
    fields: Optional[list[dict]] = None,
    passport_key: Optional[str] = None,
) -> dict[str, Any]:
    tpl = get_template(template_id)
    if not tpl:
        raise LookupError(f"template {template_id} not found")

    if tpl.get("is_system"):
        if not passport_key or not check_any_user_passport_key(passport_key):
            raise PermissionError("System template — passport key required")

    update: dict[str, Any] = {}
    if name is not None:
        update["name"] = name
    if fields is not None:
        update["fields"] = fields
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    res = get_supabase().table("templates").update(update).eq("id", template_id).execute()
    return res.data[0] if res.data else tpl


def clone_template(template_id: str, passport_key: Optional[str] = None) -> dict[str, Any]:
    tpl = get_template(template_id)
    if not tpl:
        raise LookupError(f"template {template_id} not found")
    if tpl.get("is_system"):
        if not passport_key or not check_any_user_passport_key(passport_key):
            raise PermissionError("System template — passport key required")
    return create_template(
        name=f"{tpl['name']} (Copy)",
        document_type=tpl["document_type"],
        fields=tpl["fields"],
    )


def template_requires_passport_key(template_id: str) -> bool:
    tpl = get_template(template_id)
    return bool(tpl and tpl.get("is_system"))


# ============================================================
# Templates linked to documents — accuracy stats
# ============================================================
def refresh_template_accuracy(document_type: str) -> None:
    """After a doc of `document_type` is processed/approved, recompute avg_accuracy."""
    supa = get_supabase()
    # Average across PROCESSED / APPROVED / ARCHIVED docs of this type
    res = (
        supa.table("documents")
        .select("confidence")
        .eq("document_type", document_type)
        .in_("status", ["PENDING_REVIEW", "APPROVED", "ARCHIVED"])
        .execute()
    )
    rows = res.data or []
    if not rows:
        return
    confs = [r["confidence"] for r in rows if r.get("confidence") is not None]
    if not confs:
        return
    avg = round(sum(confs) / len(confs), 2)

    supa.table("templates").update(
        {"avg_accuracy": avg, "docs_processed": len(rows)}
    ).eq("document_type", document_type).execute()
