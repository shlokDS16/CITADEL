"""
Supabase persistence for expenses (service-role client).

Same resilience contract as tickets/fake_news: reads degrade to empty,
writes that must not be silently lost raise. All queries are scoped by
citizen_id — personal finance is never cross-citizen, even pre-auth.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

log = logging.getLogger("citadel.expenses.repo")

TABLES = (
    "expenses", "receipts", "receipt_items", "budgets",
    "import_batches", "import_rows", "exports", "expense_merchant_cache",
)


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable: %s", e)
        return None


def probe_tables() -> list[dict[str, Any]]:
    sb = _sb()
    out: list[dict[str, Any]] = []
    for name in TABLES:
        if sb is None:
            out.append({"name": name, "present": False, "rows": None})
            continue
        try:
            res = sb.table(name).select("*", count="exact").limit(1).execute()
            out.append({"name": name, "present": True, "rows": res.count or 0})
        except Exception:  # noqa: BLE001
            out.append({"name": name, "present": False, "rows": None})
    return out


# --------------------------------------------------------------------------
# Expenses
# --------------------------------------------------------------------------
def insert_expense(row: dict[str, Any]) -> dict[str, Any]:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot record expense")
    res = sb.table("expenses").insert(row).execute()
    data = res.data or []
    if not data:
        raise RuntimeError("expense insert returned no row")
    return data[0]


def get_expense(citizen_id: str, exp_id: str) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (
            sb.table("expenses").select("*")
            .eq("id", exp_id).eq("citizen_id", citizen_id)
            .is_("deleted_at", "null").limit(1).execute()
        ).data or []
        return rows[0] if rows else None
    except Exception as e:  # noqa: BLE001
        log.debug("get_expense failed: %s", e)
        return None


def update_expense(citizen_id: str, exp_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot update expense")
    res = (
        sb.table("expenses").update(patch)
        .eq("id", exp_id).eq("citizen_id", citizen_id)
        .is_("deleted_at", "null").execute()
    )
    data = res.data or []
    return data[0] if data else None


def soft_delete_expense(citizen_id: str, exp_id: str) -> bool:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase unavailable — cannot delete expense")
    res = (
        sb.table("expenses")
        .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", exp_id).eq("citizen_id", citizen_id)
        .is_("deleted_at", "null").execute()
    )
    return bool(res.data)


def list_expenses(
    citizen_id: str,
    category: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    min_amount_paise: Optional[int] = None,
    anomaly_only: bool = False,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    sb = _sb()
    if sb is None:
        return [], 0
    try:
        query = (
            sb.table("expenses").select("*", count="exact")
            .eq("citizen_id", citizen_id).is_("deleted_at", "null")
        )
        if category:
            query = query.in_("category", [c.strip() for c in category.split(",") if c.strip()])
        if date_from:
            query = query.gte("spent_at", date_from.isoformat())
        if date_to:
            query = query.lte("spent_at", date_to.isoformat())
        if min_amount_paise:
            query = query.gte("amount_paise", min_amount_paise)
        if anomaly_only:
            query = query.eq("is_anomaly", True)
        if q:
            esc = q.replace("%", "").replace(",", " ")
            query = query.or_(f"description.ilike.%{esc}%,merchant.ilike.%{esc}%")
        res = (
            query.order("spent_at", desc=True).order("created_at", desc=True)
            .range(offset, offset + limit - 1).execute()
        )
        return (res.data or []), (res.count or 0)
    except Exception as e:  # noqa: BLE001
        log.debug("list_expenses failed: %s", e)
        return [], 0


def category_history_paise(
    citizen_id: str, category: str, days: int = 90, exclude_id: Optional[str] = None,
) -> list[int]:
    """Amounts (paise) of prior expenses in this category — the anomaly
    baseline window."""
    sb = _sb()
    if sb is None:
        return []
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        query = (
            sb.table("expenses").select("id, amount_paise")
            .eq("citizen_id", citizen_id).eq("category", category)
            .is_("deleted_at", "null").gte("spent_at", cutoff)
            .limit(500)
        )
        rows = query.execute().data or []
        return [int(r["amount_paise"]) for r in rows
                if r.get("amount_paise") and r.get("id") != exclude_id]
    except Exception as e:  # noqa: BLE001
        log.debug("category_history failed: %s", e)
        return []


def all_history_paise(
    citizen_id: str, days: int = 90, exclude_id: Optional[str] = None,
) -> list[int]:
    """Amounts across ALL categories — the anomaly fallback baseline for a
    category with too little history of its own."""
    sb = _sb()
    if sb is None:
        return []
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        rows = (
            sb.table("expenses").select("id, amount_paise")
            .eq("citizen_id", citizen_id).is_("deleted_at", "null")
            .gte("spent_at", cutoff).limit(500).execute()
        ).data or []
        return [int(r["amount_paise"]) for r in rows
                if r.get("amount_paise") and r.get("id") != exclude_id]
    except Exception as e:  # noqa: BLE001
        log.debug("all_history failed: %s", e)
        return []


def expenses_between(
    citizen_id: str, date_from: date, date_to: date,
) -> list[dict[str, Any]]:
    """All non-deleted expenses in [from, to] — dashboard aggregation input.
    One fetch, aggregated in Python: a citizen-month is hundreds of rows,
    not millions, and PostgREST group-by is clumsier than this."""
    sb = _sb()
    if sb is None:
        return []
    try:
        return (
            sb.table("expenses").select("*")
            .eq("citizen_id", citizen_id).is_("deleted_at", "null")
            .gte("spent_at", date_from.isoformat())
            .lte("spent_at", date_to.isoformat())
            .order("spent_at", desc=True)
            .limit(2000).execute()
        ).data or []
    except Exception as e:  # noqa: BLE001
        log.debug("expenses_between failed: %s", e)
        return []


def cache_stats() -> dict[str, Any]:
    sb = _sb()
    if sb is None:
        return {"rows": 0}
    try:
        res = (
            sb.table("expense_merchant_cache")
            .select("merchant_key", count="exact").limit(1).execute()
        )
        return {"rows": res.count or 0}
    except Exception:  # noqa: BLE001
        return {"rows": 0}
