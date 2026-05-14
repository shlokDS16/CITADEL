"""
Audit log helper — every state change on a document MUST go through here.
Ref: .claude/rules/security-baseline.md (audit trail), data-handling.md.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.database import get_supabase

log = logging.getLogger("citadel.audit")

# Vocabulary of allowed actions. Frontend-readable.
ACTION_UPLOADED = "uploaded"
ACTION_PROCESSED = "processed"
ACTION_PII_DETECTED = "pii_detected"
ACTION_SIGNATURE_DETECTED = "signature_detected"
ACTION_CLASSIFIED = "classified"
ACTION_INDEXED = "indexed"
ACTION_APPROVED = "approved"
ACTION_REJECTED = "rejected"
ACTION_ARCHIVED = "archived"
ACTION_REASSIGNED = "reassigned"
ACTION_EDITED = "edited"
ACTION_FAILED = "failed"
ACTION_DOWNLOADED = "downloaded"


def write_audit(
    document_id: str,
    action: str,
    details: Optional[dict[str, Any]] = None,
    performed_by: str = "system",
) -> None:
    """Insert an audit row. Best-effort — never raises into the calling pipeline."""
    try:
        get_supabase().table("audit_log").insert(
            {
                "document_id": document_id,
                "action": action,
                "details": details or {},
                "performed_by": performed_by,
            }
        ).execute()
    except Exception as e:  # pragma: no cover
        log.warning("audit write failed for doc=%s action=%s: %s", document_id, action, e)
