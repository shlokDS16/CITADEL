"""
Tickets — business logic. Routers stay thin; this holds the rules.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app import __version__
from app.modules.tickets import geo, pipeline, repo, schemas, storage

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
        "geo_h3": (
            geo.cell_for(payload.geo_lat, payload.geo_lng)
            if payload.geo_lat is not None and payload.geo_lng is not None
            else None
        ),
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
# My Tickets — list, KPIs, citizen actions
# --------------------------------------------------------------------------
#: Citizen may reopen a resolved ticket within this window (spec-07).
REOPEN_WINDOW_DAYS = 14


def list_tickets(
    submitted_by: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    rows, total = repo.list_tickets(
        submitted_by=submitted_by, status=status, category=category,
        limit=limit, offset=offset,
    )
    return {
        "data": [shape_ticket(r) for r in rows],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


def _avg_resolution_label(samples: list[tuple[str, str]]) -> str:
    """Mean resolution time over real resolved tickets. '—' when there are
    none — an invented number here would be a lie on a gov dashboard."""
    deltas: list[float] = []
    for created, resolved in samples:
        c, r = _parse_dt(created), _parse_dt(resolved)
        if c and r and r >= c:
            deltas.append((r - c).total_seconds())
    if not deltas:
        return "—"
    mean = sum(deltas) / len(deltas)
    if mean < 3600:
        return f"{int(mean // 60)}m"
    if mean < 86400:
        return f"{int(mean // 3600)}h"
    return f"{mean / 86400:.1f}d"


def ticket_stats(submitted_by: Optional[str] = None) -> dict[str, Any]:
    """KPI strip for the My-Tickets tab. Every number is computed from the
    DB — the frontend mock's hardcoded 1/2/8/36h is replaced, not mirrored."""
    counts = repo.status_counts(submitted_by)
    in_progress = sum(
        counts.get(s, 0) for s in ("assigned", "in_progress", "verification")
    )
    return {
        "open": counts.get("open", 0) + counts.get("reopened", 0),
        "in_progress": in_progress,
        "resolved": counts.get("resolved", 0) + counts.get("closed", 0),
        "avg_resolution": _avg_resolution_label(repo.resolution_samples(submitted_by)),
        "by_status": counts,
    }


def add_citizen_update(
    ticket_id: str,
    text: str,
    actor_id: Optional[str] = None,
    actor_label: str = "You",
) -> dict[str, Any]:
    body = _strip_html(text)
    if not body:
        raise ValueError("text is required")
    if not repo.get_ticket(ticket_id):
        raise LookupError(f"ticket {ticket_id} not found")
    row = repo.add_update(
        ticket_id, text=body, actor_label=actor_label,
        actor_role="citizen", actor_id=actor_id, visibility="public",
    )
    if row is None:
        raise RuntimeError("could not record update")
    return {
        "id": str(row.get("id")),
        "ticket_id": row.get("ticket_id"),
        "actor_id": row.get("actor_id"),
        "actor_label": row.get("actor_label"),
        "actor_role": row.get("actor_role"),
        "text": row.get("text"),
        "visibility": row.get("visibility"),
        "created_at": row.get("created_at"),
    }


def rate_ticket(ticket_id: str, rating: int, comment: Optional[str] = None) -> dict[str, Any]:
    """Citizen rates the resolution 1-5. Only meaningful once resolved."""
    if rating < 1 or rating > 5:
        raise ValueError("rating must be between 1 and 5")
    row = repo.get_ticket(ticket_id)
    if not row:
        raise LookupError(f"ticket {ticket_id} not found")
    if row.get("status") not in ("resolved", "closed"):
        raise ValueError(
            f"ticket is {row.get('status')} — only a resolved ticket can be rated"
        )
    patch: dict[str, Any] = {"rating": rating}
    if comment:
        patch["rating_comment"] = _strip_html(comment)[:2000]
    updated = repo.update_ticket(ticket_id, patch)
    repo.add_update(
        ticket_id, text=f"Citizen rated the resolution {rating}/5.",
        actor_label="You", actor_role="citizen",
    )
    return shape_ticket(updated or {**row, **patch})


def reopen_ticket(ticket_id: str, reason: str) -> dict[str, Any]:
    """Reopen a resolved ticket within REOPEN_WINDOW_DAYS of resolution."""
    body = _strip_html(reason)
    if not body:
        raise ValueError("a reason is required to reopen")
    row = repo.get_ticket(ticket_id)
    if not row:
        raise LookupError(f"ticket {ticket_id} not found")
    if row.get("status") not in ("resolved", "closed"):
        raise ValueError(f"ticket is {row.get('status')} — only a resolved ticket can be reopened")

    resolved = _parse_dt(row.get("resolved_at"))
    if resolved:
        age_days = (datetime.now(timezone.utc) - resolved).total_seconds() / 86400
        if age_days > REOPEN_WINDOW_DAYS:
            raise ValueError(
                f"reopen window is {REOPEN_WINDOW_DAYS} days; this ticket was "
                f"resolved {int(age_days)} days ago"
            )

    now = datetime.now(timezone.utc)
    updated = repo.update_ticket(ticket_id, {
        "status": "reopened",
        "reopened_at": now.isoformat(),
        "resolved_at": None,
        "closed_at": None,
    })
    repo.add_update(
        ticket_id, text=f"Ticket reopened by citizen: {body}",
        actor_label="You", actor_role="citizen",
    )
    return shape_ticket(updated or row)


# --------------------------------------------------------------------------
# Community
# --------------------------------------------------------------------------
#: Upvotes needed to escalate a ticket's priority one step. spec-07 left
#: the exact number open; 25 is the starting value and lives here as a
#: single named constant so it is trivial to retune once there is real
#: usage data. Escalation only ever raises priority, never lowers it.
UPVOTE_ESCALATION_THRESHOLD = 25

#: tickets.priority -> the severity vocabulary the community UI renders.
_SEVERITY_OF_PRIORITY = {
    "LOW": "LOW",
    "NORMAL": "MEDIUM",
    "HIGH": "HIGH",
    "CRITICAL": "CRITICAL",
}


def _trending_score(row: dict[str, Any], comments: int) -> float:
    """Upvotes + discussion, decayed by age.

    A 3-day-old issue with 40 supports should outrank a 2-hour-old one
    with 3. Half-life of 48h keeps the feed moving without letting a fresh
    post with no support jump the queue.
    """
    upvotes = int(row.get("upvotes") or 0)
    created = _parse_dt(row.get("created_at"))
    age_h = (
        (datetime.now(timezone.utc) - created).total_seconds() / 3600 if created else 0.0
    )
    engagement = upvotes + 2.0 * comments
    return engagement / (1.0 + age_h / 48.0)


_haversine_km = geo.haversine_km


def community(
    sort: str = "trending",
    q: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    citizen_id: Optional[str] = None,
) -> dict[str, Any]:
    sort = (sort or "trending").lower()
    # 'nearby' needs a wider candidate set than the page, since distance is
    # computed in Python rather than in the query.
    fetch_limit = 200 if sort in ("trending", "nearby") else limit
    rows, total = repo.community_tickets(
        sort=sort, q=q, limit=fetch_limit, offset=0 if sort in ("trending", "nearby") else offset
    )
    counts = repo.comment_counts([r["id"] for r in rows if r.get("id")])

    if sort == "nearby":
        if lat is None or lng is None:
            raise ValueError("sort=nearby requires lat and lng")
        located = []
        for r in rows:
            if r.get("geo_lat") is None or r.get("geo_lng") is None:
                continue
            r = {**r, "_distance_km": round(
                _haversine_km(lat, lng, float(r["geo_lat"]), float(r["geo_lng"])), 2
            )}
            located.append(r)
        located.sort(key=lambda r: r["_distance_km"])
        rows, total = located, len(located)
        rows = rows[offset:offset + limit]
    elif sort == "trending":
        rows.sort(key=lambda r: _trending_score(r, counts.get(r.get("id"), 0)), reverse=True)
        rows = rows[offset:offset + limit]

    data = []
    for r in rows:
        tid = r.get("id")
        priority = r.get("priority") or "NORMAL"
        cat = r.get("category") or "Other"
        data.append({
            "id": tid,
            "title": r.get("subject") or "",
            "location_label": r.get("location_label"),
            "category": cat,
            "display_category": schemas.DISPLAY_CATEGORY.get(cat, cat),
            "upvotes": int(r.get("upvotes") or 0),
            "response_count": counts.get(tid, 0),
            "age": _age(r.get("created_at")),
            "severity": _SEVERITY_OF_PRIORITY.get(priority, "MEDIUM"),
            "status": r.get("status") or "open",
            "distance_km": r.get("_distance_km"),
            "has_upvoted": repo.has_upvoted(tid, citizen_id) if citizen_id else False,
        })
    return {"data": data, "meta": {"total": total, "limit": limit, "offset": offset, "sort": sort}}


def _reconcile_upvotes(ticket_id: str) -> tuple[int, Optional[str]]:
    """Recount from the join table, write the cache, and escalate priority
    if the ticket crossed the support threshold.

    Returns (count, new_priority | None). The count is always the authoritative
    join-table value, never an increment of a possibly-stale cache.
    """
    count = repo.count_upvotes(ticket_id)
    patch: dict[str, Any] = {"upvotes": count}
    escalated: Optional[str] = None

    row = repo.get_ticket(ticket_id) or {}
    current = row.get("priority") or "NORMAL"
    if (
        count >= UPVOTE_ESCALATION_THRESHOLD
        and current in ("LOW", "NORMAL")
        and row.get("status") not in ("resolved", "closed")
    ):
        escalated = "HIGH"
        patch["priority"] = escalated
        patch["priority_was_auto"] = True

    repo.update_ticket(ticket_id, patch)
    if escalated:
        repo.add_update(
            ticket_id,
            text=(
                f"Priority raised to {escalated} — {count} residents have supported "
                f"this issue (threshold {UPVOTE_ESCALATION_THRESHOLD})."
            ),
            actor_label="CITADEL AI",
            actor_role="system",
        )
    return count, escalated


def upvote(ticket_id: str, citizen_id: str) -> dict[str, Any]:
    if not repo.get_ticket(ticket_id):
        raise LookupError(f"ticket {ticket_id} not found")
    created = repo.add_upvote(ticket_id, citizen_id)
    count, escalated = _reconcile_upvotes(ticket_id)
    return {
        "ticket_id": ticket_id,
        "upvotes": count,
        "has_upvoted": True,
        "created": created,
        "priority_escalated_to": escalated,
    }


def remove_upvote(ticket_id: str, citizen_id: str) -> dict[str, Any]:
    if not repo.get_ticket(ticket_id):
        raise LookupError(f"ticket {ticket_id} not found")
    removed = repo.remove_upvote(ticket_id, citizen_id)
    count, _ = _reconcile_upvotes(ticket_id)
    return {
        "ticket_id": ticket_id,
        "upvotes": count,
        "has_upvoted": False,
        "created": False,
        "removed": removed,
    }


def add_comment(ticket_id: str, citizen_id: str, text: str) -> dict[str, Any]:
    body = _strip_html(text)
    if not body:
        raise ValueError("text is required")
    if not repo.get_ticket(ticket_id):
        raise LookupError(f"ticket {ticket_id} not found")
    row = repo.add_comment(ticket_id, citizen_id, body[:2000])
    if row is None:
        raise RuntimeError("could not record comment")
    return _shape_comment(row)


def _shape_comment(row: dict[str, Any]) -> dict[str, Any]:
    """Comments are public. The citizen uuid is deliberately NOT exposed —
    only a short stable pseudonym, so a public feed cannot be used to
    correlate a person across the tickets they commented on."""
    cid = str(row.get("citizen_id") or "")
    return {
        "id": str(row.get("id")),
        "ticket_id": row.get("ticket_id"),
        "author_label": f"Citizen {cid[:4].upper()}" if cid else "Citizen",
        "text": row.get("text") or "",
        "created_at": row.get("created_at"),
        "age": _age(row.get("created_at")),
    }


def list_comments(ticket_id: str) -> list[dict[str, Any]]:
    return [_shape_comment(r) for r in repo.list_comments(ticket_id)]


# --------------------------------------------------------------------------
# Map
# --------------------------------------------------------------------------
def map_nearby(
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    include_resolved: bool = False,
) -> dict[str, Any]:
    """Located tickets within a true radius + H3 cluster summary.

    Bounding box narrows in SQL, haversine trims exactly, H3 groups for
    the map layer. See geo.py for why this is not ST_DWithin.
    """
    min_lat, max_lat, min_lng, max_lng = geo.bounding_box(lat, lng, radius_km)
    candidates = repo.tickets_in_bbox(
        min_lat, max_lat, min_lng, max_lng, include_resolved=include_resolved
    )

    within: list[dict[str, Any]] = []
    for r in candidates:
        d = geo.haversine_km(lat, lng, float(r["geo_lat"]), float(r["geo_lng"]))
        if d <= radius_km:
            within.append({**r, "_distance_km": round(d, 2)})
    within.sort(key=lambda r: r["_distance_km"])

    counts = repo.comment_counts([r["id"] for r in within])
    pins = []
    for r in within:
        cat = r.get("category") or "Other"
        pri = r.get("priority") or "NORMAL"
        pins.append({
            "id": r["id"],
            "title": r.get("subject") or "",
            "lat": r["geo_lat"],
            "lng": r["geo_lng"],
            "distance_km": r["_distance_km"],
            "category": cat,
            "display_category": schemas.DISPLAY_CATEGORY.get(cat, cat),
            "severity": _SEVERITY_OF_PRIORITY.get(pri, "MEDIUM"),
            "status": r.get("status") or "open",
            "upvotes": int(r.get("upvotes") or 0),
            "response_count": counts.get(r["id"], 0),
            "age": _age(r.get("created_at")),
            "location_label": r.get("location_label"),
        })

    resolution = geo.resolution_for_radius(radius_km)
    return {
        "center": {"lat": lat, "lng": lng},
        "radius_km": radius_km,
        "count": len(pins),
        "pins": pins,
        "clusters": geo.cluster(within, resolution),
        "h3_resolution": resolution,
        "h3_available": geo.h3_available(),
    }


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
