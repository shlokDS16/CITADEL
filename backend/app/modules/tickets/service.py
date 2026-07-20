"""
Tickets — business logic. Routers stay thin; this holds the rules.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app import __version__
from app.modules.tickets import pipeline, repo, schemas, storage

log = logging.getLogger("citadel.tickets.service")

# UI timeline (pages.jsx StatusTimeline): Submitted → Assigned → In Progress
# → Verification → Resolved. `step` is the index the frontend highlights.
_STATUS_STEP = {
    "open": 0,
    "reopened": 0,
    "assigned": 1,
    "in_progress": 2,
    "verification": 3,
    "resolved": 4,
    "closed": 4,
}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """security-baseline.md: free-text fields are HTML-stripped at the
    schema layer before storage."""
    return _TAG_RE.sub("", text or "").strip()


def _age(created_at: Any) -> str:
    """Human age string the UI renders ('2d', '3h', '12m')."""
    if not created_at:
        return "—"
    try:
        if isinstance(created_at, str):
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            dt = created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return "—"
    secs = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:  # noqa: BLE001
        return None


#: A ticket is "at risk" once this fraction of its SLA window is left.
_AT_RISK_FRACTION = 0.25


def _sla_status(sla_due_at: Any, status: str, created_at: Any = None) -> str:
    """on_track / at_risk / breached, computed live from the due time.

    The threshold is a *fraction of the ticket's own SLA window*, not a
    fixed number of hours. A fixed 4h threshold meant every CRITICAL
    ticket (4h SLA) was born "at_risk" the instant it was created.

    Stored sla_status is a cache; this is the truth at read time, so a
    ticket cannot silently sit "on_track" past its deadline.
    """
    if status in ("resolved", "closed"):
        return "on_track"
    due = _parse_dt(sla_due_at)
    if due is None:
        return "on_track"

    now = datetime.now(timezone.utc)
    remaining = (due - now).total_seconds()
    if remaining < 0:
        return "breached"

    created = _parse_dt(created_at)
    window = (due - created).total_seconds() if created else 0
    # Fall back to a 4h absolute threshold only when the window is unknown.
    threshold = window * _AT_RISK_FRACTION if window > 0 else 3600 * 4
    return "at_risk" if remaining < threshold else "on_track"


def shape_ticket(
    row: dict[str, Any],
    attachments: Optional[list[dict[str, Any]]] = None,
    updates: Optional[list[dict[str, Any]]] = None,
    sign_urls: bool = False,
) -> dict[str, Any]:
    """DB row → the shape TicketOut / the frontend expects.

    `sign_urls` is off by default: each signed URL is a storage API round
    trip, so list endpoints skip them and only the detail view pays.
    """
    cat = row.get("category") or "Other"
    status = row.get("status") or "open"
    return {
        "id": row.get("id"),
        "subject": row.get("subject") or "",
        "description": row.get("description") or "",
        "category": cat,
        "display_category": schemas.DISPLAY_CATEGORY.get(cat, cat),
        "priority": row.get("priority") or "NORMAL",
        "priority_was_auto": bool(row.get("priority_was_auto", True)),
        "status": status,
        "department": row.get("department") or "PWD",
        "submitted_by": row.get("submitted_by"),
        "is_anonymous": bool(row.get("is_anonymous", False)),
        "geo_lat": row.get("geo_lat"),
        "geo_lng": row.get("geo_lng"),
        "location_label": row.get("location_label"),
        "upvotes": int(row.get("upvotes") or 0),
        "age": _age(row.get("created_at")),
        "step": _STATUS_STEP.get(status, 0),
        "created_at": row.get("created_at"),
        "assigned_at": row.get("assigned_at"),
        "resolved_at": row.get("resolved_at"),
        "sla_due_at": row.get("sla_due_at"),
        "sla_status": _sla_status(row.get("sla_due_at"), status, row.get("created_at")),
        "rating": row.get("rating"),
        "sentiment": row.get("sentiment"),
        "ai_classification": row.get("ai_classification") or {},
        "attachments": [
            {
                "id": str(a.get("id")),
                "type": a.get("type"),
                "name": a.get("name"),
                "size_bytes": int(a.get("size_bytes") or 0),
                "mime_type": a.get("mime_type"),
                "download_url": (
                    storage.signed_url(a.get("storage_path") or "") if sign_urls else None
                ),
                "transcript": a.get("transcript"),
            }
            for a in (attachments or [])
        ],
        "updates": [
            {
                "id": str(u.get("id")),
                "ticket_id": u.get("ticket_id"),
                "actor_id": u.get("actor_id"),
                "actor_label": u.get("actor_label") or "System",
                "actor_role": u.get("actor_role") or "system",
                "text": u.get("text") or "",
                "visibility": u.get("visibility") or "public",
                "created_at": u.get("created_at"),
            }
            for u in (updates or [])
        ],
    }


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------
def list_templates() -> list[dict[str, Any]]:
    out = []
    for t in repo.templates():
        cat = t.get("category") or "Other"
        out.append({
            "id": str(t.get("id")),
            "title": t.get("title") or "",
            "body": t.get("body") or "",
            "category": cat,
            "display_category": schemas.DISPLAY_CATEGORY.get(cat, cat),
        })
    return out


# --------------------------------------------------------------------------
# Preview (no persistence)
# --------------------------------------------------------------------------
def preview(payload: schemas.TicketPreviewIn) -> dict[str, Any]:
    result = pipeline.classify(
        subject=payload.subject,
        description=payload.description,
        category_override=payload.category,
        priority_override=payload.priority,
    )
    return {k: v for k, v in result.items() if k in {
        "predicted_category", "display_category", "predicted_priority",
        "predicted_department", "predicted_sla_label", "predicted_sla_due_at",
        "sentiment", "confidence", "reasoning_summary", "source",
        "quota_exhausted",
    }}


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------
def create_ticket(
    payload: schemas.TicketCreateIn,
    submitted_by: Optional[str] = None,
) -> dict[str, Any]:
    """Classify, persist, seed the timeline. Raises on persistence failure —
    we never report a ticket created when it wasn't."""
    subject = _strip_html(payload.subject)
    description = _strip_html(payload.description)
    if not subject:
        raise ValueError("subject is required")

    result = pipeline.classify(
        subject=subject,
        description=description,
        category_override=payload.category,
        priority_override=payload.priority,
    )

    # An anonymous ticket must not carry a submitter — the DB enforces this
    # too (tickets_anonymous_check); mirroring it here keeps the error a
    # clean 4xx instead of a 23514.
    owner = None if payload.is_anonymous else submitted_by

    ticket_id = repo.next_ticket_id()
    row = {
        "id": ticket_id,
        "subject": subject[:255],
        "description": description,
        "category": result["predicted_category"],
        "priority": result["predicted_priority"],
        "priority_was_auto": result["priority_was_auto"],
        "status": "open",
        "department": result["predicted_department"],
        "submitted_by": owner,
        "is_anonymous": bool(payload.is_anonymous),
        "geo_lat": payload.geo_lat,
        "geo_lng": payload.geo_lng,
        "location_label": payload.location_label,
        "sentiment": result["sentiment"],
        "sla_due_at": result["predicted_sla_due_at"].isoformat(),
        "sla_status": "on_track",
        "ai_classification": {
            "source": result["source"],
            "confidence": result["confidence"],
            "reasoning": result["reasoning_summary"],
            "sentiment_compound": result["sentiment_compound"],
            "sla_hours": result["sla_hours"],
            "quota_exhausted": result["quota_exhausted"],
            "classified_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    stored = repo.insert_ticket(row)

    # Seed the timeline so "Submitted" is a real row, not a UI placeholder.
    repo.add_update(
        ticket_id,
        text="Issue reported." + (" Submitted anonymously." if payload.is_anonymous else ""),
        actor_label="You" if not payload.is_anonymous else "Anonymous",
        actor_role="citizen",
        actor_id=owner,
    )
    repo.add_update(
        ticket_id,
        text=(
            f"Auto-routed to {result['predicted_department']} · "
            f"{result['predicted_priority']} priority · SLA {result['predicted_sla_label']} "
            f"({result['source']})"
        ),
        actor_label="CITADEL AI",
        actor_role="system",
    )

    updates = repo.list_updates(ticket_id)
    preview_out = {k: v for k, v in result.items() if k in {
        "predicted_category", "display_category", "predicted_priority",
        "predicted_department", "predicted_sla_label", "predicted_sla_due_at",
        "sentiment", "confidence", "reasoning_summary", "source",
        "quota_exhausted",
    }}
    return {
        "ticket": shape_ticket(stored, attachments=[], updates=updates),
        "preview": preview_out,
    }


def get_ticket(ticket_id: str) -> Optional[dict[str, Any]]:
    row = repo.get_ticket(ticket_id)
    if not row:
        return None
    return shape_ticket(
        row,
        attachments=repo.list_attachments(ticket_id),
        updates=repo.list_updates(ticket_id),
        sign_urls=True,
    )


# --------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------
def attach_file(
    ticket_id: str,
    kind: str,
    content: bytes,
    filename: Optional[str],
    detected_kind: str,
) -> dict[str, Any]:
    """Upload one attachment and record it.

    Storage first, then the DB row. If the row fails the object is removed,
    so we never leave an orphan the periodic scan would have to quarantine.
    """
    if not repo.get_ticket(ticket_id):
        raise LookupError(f"ticket {ticket_id} not found")

    display_name = storage.sanitize_filename(filename, fallback=f"{kind}{storage.extension_of(filename)}")
    mime = storage.guess_mime(filename, detected_kind)
    path = storage.upload(ticket_id, content, filename, mime)

    try:
        row = repo.insert_attachment({
            "ticket_id": ticket_id,
            "type": kind,
            "name": display_name,
            "storage_path": path,
            "mime_type": mime,
            "size_bytes": len(content),
        })
    except Exception:
        storage.remove(path)
        raise

    repo.add_update(
        ticket_id,
        text=f"Attachment added: {display_name}",
        actor_label="You",
        actor_role="citizen",
    )
    return {
        "id": str(row.get("id")),
        "type": row.get("type"),
        "name": row.get("name"),
        "size_bytes": int(row.get("size_bytes") or 0),
        "mime_type": row.get("mime_type"),
        "download_url": storage.signed_url(path),
        "transcript": row.get("transcript"),
    }


def attachment_download_url(ticket_id: str, att_id: str) -> Optional[str]:
    row = repo.get_attachment(att_id, ticket_id=ticket_id)
    if not row:
        return None
    return storage.signed_url(row.get("storage_path") or "")


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
def health() -> dict[str, Any]:
    tables = repo.probe_tables()
    classifier = pipeline.classifier_status()
    missing = [t["name"] for t in tables if not t["present"]]
    bucket_ok, bucket_note = storage.bucket_ready()

    notes: list[str] = []
    if bucket_note:
        notes.append(bucket_note)
    if missing:
        notes.append(
            f"{len(missing)} table(s) missing: {', '.join(missing)} — apply "
            "supabase/migrations/20260720000005_tickets_module_schema.sql"
        )
    if not classifier["groq_configured"]:
        notes.append("GROQ_API_KEY not set — classification uses the keyword rule router only.")
    if not classifier["vader_available"]:
        notes.append("vaderSentiment not importable — sentiment will report neutral.")
    if classifier["rules_loaded"] == 0:
        notes.append("routing_rules is empty — department/SLA routing cannot work.")
    notes.append(
        "No PostGIS on this project: geo is geo_lat/geo_lng + app-side H3, not GEOGRAPHY."
    )

    degraded = bool(missing) or classifier["mode"] == "unavailable" or not bucket_ok
    return {
        "status": "degraded" if degraded else "ok",
        "module": "tickets",
        "version": __version__,
        "tables": tables,
        "classifier": classifier,
        "storage": {"bucket": storage.BUCKET, "ready": bucket_ok, "private": bucket_ok},
        "queue_depth": repo.queue_depth(),
        "notes": notes,
    }
