"""
Supabase persistence for the tickets module (service-role client).

Every call degrades gracefully when Supabase or a table is unavailable —
the same resilience contract the anomaly and fake_news modules use. A
missing table must never 500 the health probe; it shows up as
`present: false` instead.

Tables: tickets, ticket_attachments, ticket_updates, ticket_upvotes,
ticket_comments, ticket_templates, routing_rules (migration
20260720000005).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("citadel.tickets.repo")

TABLES = (
    "tickets",
    "ticket_attachments",
    "ticket_updates",
    "ticket_upvotes",
    "ticket_comments",
    "ticket_templates",
    "routing_rules",
)


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable: %s", e)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Probes (health)
# --------------------------------------------------------------------------
def probe_tables() -> list[dict[str, Any]]:
    """Report presence + row count per table. Never raises."""
    sb = _sb()
    out: list[dict[str, Any]] = []
    for name in TABLES:
        if sb is None:
            out.append({"name": name, "present": False, "rows": None})
            continue
        try:
            res = sb.table(name).select("*", count="exact").limit(1).execute()
            out.append({"name": name, "present": True, "rows": res.count or 0})
        except Exception as e:  # noqa: BLE001
            log.debug("probe %s failed: %s", name, e)
            out.append({"name": name, "present": False, "rows": None})
    return out


def queue_depth() -> dict[str, int]:
    """Unresolved ticket count per department. Empty dict if unavailable."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        rows = (
            sb.table("tickets")
            .select("department, status")
            .not_.in_("status", ["resolved", "closed"])
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("queue_depth failed: %s", e)
        return {}
    depth: dict[str, int] = {}
    for r in rows:
        dept = r.get("department") or "unknown"
        depth[dept] = depth.get(dept, 0) + 1
    return depth


# --------------------------------------------------------------------------
# Routing rules
# --------------------------------------------------------------------------
def routing_rules(active_only: bool = True) -> list[dict[str, Any]]:
    """All routing rules. Empty list if the table is unreachable — callers
    must treat an empty result as "no rules", not as an error."""
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("routing_rules").select("*")
        if active_only:
            q = q.eq("active", True)
        return q.order("category").execute().data or []
    except Exception as e:  # noqa: BLE001
        log.debug("routing_rules failed: %s", e)
        return []


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------
def templates() -> list[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (
            sb.table("ticket_templates")
            .select("*")
            .eq("active", True)
            .order("sort_order")
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("templates failed: %s", e)
        return []


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------
def next_ticket_id() -> str:
    """Allocate the next TKT-#### id.

    Uses the DB function public.next_ticket_id(), which does an atomic
    UPDATE ... RETURNING — two concurrent submits cannot collide. Raises
    if unavailable: a ticket without an id must not be invented here.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot allocate ticket id")
    res = sb.rpc("next_ticket_id", {}).execute()
    tid = res.data
    if isinstance(tid, list):  # some PostgREST versions wrap scalars
        tid = tid[0] if tid else None
    if not tid or not isinstance(tid, str):
        raise RuntimeError(f"next_ticket_id() returned {tid!r}")
    return tid


def insert_ticket(row: dict[str, Any]) -> dict[str, Any]:
    """Insert and return the stored row. Raises on failure — the caller
    must not report a ticket as created when it was not."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot create ticket")
    res = sb.table("tickets").insert(row).execute()
    data = res.data or []
    if not data:
        raise RuntimeError("ticket insert returned no row")
    return data[0]


def get_ticket(ticket_id: str) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (
            sb.table("tickets").select("*").eq("id", ticket_id).limit(1).execute()
        ).data or []
        return rows[0] if rows else None
    except Exception as e:  # noqa: BLE001
        log.debug("get_ticket failed: %s", e)
        return None


def list_tickets(
    submitted_by: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Filtered ticket list + unfiltered-by-paging total.

    `submitted_by=None` means "no identity" — until Phase 3 auth exists we
    cannot scope to a real citizen, so the caller decides whether that
    means everything (demo) or nothing.
    """
    sb = _sb()
    if sb is None:
        return [], 0
    try:
        q = sb.table("tickets").select("*", count="exact")
        if submitted_by:
            q = q.eq("submitted_by", submitted_by)
        if status:
            q = q.in_("status", [s.strip() for s in status.split(",") if s.strip()])
        if category:
            q = q.in_("category", [c.strip() for c in category.split(",") if c.strip()])
        res = (
            q.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return (res.data or []), (res.count or 0)
    except Exception as e:  # noqa: BLE001
        log.debug("list_tickets failed: %s", e)
        return [], 0


def update_ticket(ticket_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot update ticket")
    res = sb.table("tickets").update(patch).eq("id", ticket_id).execute()
    data = res.data or []
    return data[0] if data else None


def status_counts(submitted_by: Optional[str] = None) -> dict[str, int]:
    """Counts per status, for the My-Tickets KPI strip."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        q = sb.table("tickets").select("status")
        if submitted_by:
            q = q.eq("submitted_by", submitted_by)
        rows = q.execute().data or []
    except Exception as e:  # noqa: BLE001
        log.debug("status_counts failed: %s", e)
        return {}
    out: dict[str, int] = {}
    for r in rows:
        s = r.get("status") or "open"
        out[s] = out.get(s, 0) + 1
    return out


def resolution_samples(submitted_by: Optional[str] = None, limit: int = 200) -> list[tuple[str, str]]:
    """(created_at, resolved_at) pairs for resolved tickets — feeds the
    average-resolution KPI. Computed from real timestamps, never guessed."""
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (
            sb.table("tickets")
            .select("created_at, resolved_at")
            .not_.is_("resolved_at", "null")
        )
        if submitted_by:
            q = q.eq("submitted_by", submitted_by)
        rows = q.limit(limit).execute().data or []
    except Exception as e:  # noqa: BLE001
        log.debug("resolution_samples failed: %s", e)
        return []
    return [
        (r["created_at"], r["resolved_at"])
        for r in rows
        if r.get("created_at") and r.get("resolved_at")
    ]


def community_tickets(
    sort: str = "trending",
    q: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Public (non-anonymous-safe) community feed.

    Anonymous tickets ARE included — whistleblower mode hides the
    submitter, not the issue — but no submitter field is ever projected.
    """
    sb = _sb()
    if sb is None:
        return [], 0
    try:
        sel = (
            "id, subject, category, priority, status, department, upvotes, "
            "location_label, geo_lat, geo_lng, created_at, sla_due_at"
        )
        query = sb.table("tickets").select(sel, count="exact")
        if q:
            # PostgREST or-filter; ilike is safe here (parameterized by the client)
            esc = q.replace("%", "").replace(",", " ")
            query = query.or_(f"subject.ilike.%{esc}%,location_label.ilike.%{esc}%")
        if sort == "unresolved":
            query = query.not_.in_("status", ["resolved", "closed"])

        if sort == "new":
            query = query.order("created_at", desc=True)
        elif sort == "unresolved":
            query = query.order("created_at", desc=True)
        else:  # trending / nearby -> ranked after fetch
            query = query.order("upvotes", desc=True).order("created_at", desc=True)

        res = query.range(offset, offset + limit - 1).execute()
        return (res.data or []), (res.count or 0)
    except Exception as e:  # noqa: BLE001
        log.debug("community_tickets failed: %s", e)
        return [], 0


def tickets_in_bbox(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
    include_resolved: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Located tickets inside a lat/lng box.

    This is the PostGIS-free prefilter — ix_tickets_geo_latlng covers it —
    and the caller trims to a true radius with haversine.
    """
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (
            sb.table("tickets")
            .select(
                "id, subject, category, priority, status, department, upvotes, "
                "location_label, geo_lat, geo_lng, geo_h3, created_at"
            )
            .not_.is_("geo_lat", "null")
            .gte("geo_lat", min_lat).lte("geo_lat", max_lat)
            .gte("geo_lng", min_lng).lte("geo_lng", max_lng)
        )
        if not include_resolved:
            q = q.not_.in_("status", ["resolved", "closed"])
        return q.limit(limit).execute().data or []
    except Exception as e:  # noqa: BLE001
        log.debug("tickets_in_bbox failed: %s", e)
        return []


def backfill_geo_h3(resolution: int, limit: int = 1000) -> int:
    """Populate geo_h3 for located tickets that lack it.

    Needed because tickets created before h3 was a dependency stored
    coordinates but no cell. Returns the number updated.
    """
    sb = _sb()
    if sb is None:
        return 0
    from app.modules.tickets import geo

    if not geo.h3_available():
        return 0
    try:
        rows = (
            sb.table("tickets")
            .select("id, geo_lat, geo_lng")
            .not_.is_("geo_lat", "null")
            .is_("geo_h3", "null")
            .limit(limit)
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("backfill query failed: %s", e)
        return 0

    n = 0
    for r in rows:
        cell = geo.cell_for(float(r["geo_lat"]), float(r["geo_lng"]), resolution)
        if not cell:
            continue
        try:
            sb.table("tickets").update({"geo_h3": cell}).eq("id", r["id"]).execute()
            n += 1
        except Exception as e:  # noqa: BLE001
            log.debug("backfill update failed for %s: %s", r.get("id"), e)
    return n


def comment_counts(ticket_ids: list[str]) -> dict[str, int]:
    """Comment count per ticket, in one round trip."""
    sb = _sb()
    if sb is None or not ticket_ids:
        return {}
    try:
        rows = (
            sb.table("ticket_comments")
            .select("ticket_id")
            .in_("ticket_id", ticket_ids)
            .is_("deleted_at", "null")
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("comment_counts failed: %s", e)
        return {}
    out: dict[str, int] = {}
    for r in rows:
        tid = r.get("ticket_id")
        if tid:
            out[tid] = out.get(tid, 0) + 1
    return out


def add_upvote(ticket_id: str, citizen_id: str) -> bool:
    """Idempotent per (ticket, citizen) via the composite PK.

    Returns True if this was a new upvote, False if already present.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot upvote")
    try:
        sb.table("ticket_upvotes").insert(
            {"ticket_id": ticket_id, "citizen_id": citizen_id}
        ).execute()
        return True
    except Exception as e:  # noqa: BLE001
        # 23505 unique_violation = already upvoted; that is success, not error
        if "23505" in str(e) or "duplicate key" in str(e).lower():
            return False
        raise


def remove_upvote(ticket_id: str, citizen_id: str) -> bool:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot remove upvote")
    res = (
        sb.table("ticket_upvotes")
        .delete()
        .eq("ticket_id", ticket_id)
        .eq("citizen_id", citizen_id)
        .execute()
    )
    return bool(res.data)


def count_upvotes(ticket_id: str) -> int:
    """Authoritative count from the join table — the tickets.upvotes column
    is a denormalized cache and must be reconciled against this."""
    sb = _sb()
    if sb is None:
        return 0
    try:
        res = (
            sb.table("ticket_upvotes")
            .select("citizen_id", count="exact")
            .eq("ticket_id", ticket_id)
            .execute()
        )
        return res.count or 0
    except Exception as e:  # noqa: BLE001
        log.debug("count_upvotes failed: %s", e)
        return 0


def has_upvoted(ticket_id: str, citizen_id: str) -> bool:
    sb = _sb()
    if sb is None or not citizen_id:
        return False
    try:
        rows = (
            sb.table("ticket_upvotes")
            .select("citizen_id")
            .eq("ticket_id", ticket_id)
            .eq("citizen_id", citizen_id)
            .limit(1)
            .execute()
        ).data or []
        return bool(rows)
    except Exception as e:  # noqa: BLE001
        log.debug("has_upvoted failed: %s", e)
        return False


def add_comment(ticket_id: str, citizen_id: str, text: str) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot comment")
    res = sb.table("ticket_comments").insert(
        {"ticket_id": ticket_id, "citizen_id": citizen_id, "text": text}
    ).execute()
    return (res.data or [None])[0]


def list_comments(ticket_id: str, limit: int = 100) -> list[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (
            sb.table("ticket_comments")
            .select("*")
            .eq("ticket_id", ticket_id)
            .is_("deleted_at", "null")
            .order("created_at")
            .limit(limit)
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("list_comments failed: %s", e)
        return []


def add_update(
    ticket_id: str,
    text: str,
    actor_label: str = "System",
    actor_role: str = "system",
    actor_id: Optional[str] = None,
    visibility: str = "public",
) -> Optional[dict[str, Any]]:
    """Append a timeline entry. Best-effort: a failed update must not undo
    a successfully created ticket."""
    sb = _sb()
    if sb is None:
        return None
    try:
        res = sb.table("ticket_updates").insert({
            "ticket_id": ticket_id,
            "text": text,
            "actor_label": actor_label,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "visibility": visibility,
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:  # noqa: BLE001
        log.warning("add_update failed for %s: %s", ticket_id, e)
        return None


def list_updates(ticket_id: str, include_internal: bool = False) -> list[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("ticket_updates").select("*").eq("ticket_id", ticket_id)
        if not include_internal:
            q = q.eq("visibility", "public")
        return q.order("created_at", desc=True).execute().data or []
    except Exception as e:  # noqa: BLE001
        log.debug("list_updates failed: %s", e)
        return []


def insert_attachment(row: dict[str, Any]) -> dict[str, Any]:
    """Record an uploaded attachment. Raises — the caller removes the
    orphaned storage object if this fails."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot record attachment")
    res = sb.table("ticket_attachments").insert(row).execute()
    data = res.data or []
    if not data:
        raise RuntimeError("attachment insert returned no row")
    return data[0]


def get_attachment(att_id: str, ticket_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return None
    try:
        q = sb.table("ticket_attachments").select("*").eq("id", att_id)
        if ticket_id:
            q = q.eq("ticket_id", ticket_id)
        rows = (q.limit(1).execute()).data or []
        return rows[0] if rows else None
    except Exception as e:  # noqa: BLE001
        log.debug("get_attachment failed: %s", e)
        return None


def list_attachments(ticket_id: str) -> list[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (
            sb.table("ticket_attachments")
            .select("*")
            .eq("ticket_id", ticket_id)
            .order("created_at")
            .execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("list_attachments failed: %s", e)
        return []
