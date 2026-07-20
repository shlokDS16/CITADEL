"""
Expenses — business logic. Paise↔rupees conversion lives HERE and only here.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app import __version__
from app.modules.expenses import anomaly, categorize, merchants, repo, schemas

log = logging.getLogger("citadel.expenses.service")

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: Optional[str]) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _paise(rupees: float) -> int:
    return int(round(float(rupees) * 100))


def _inr(paise: Any) -> float:
    return round(int(paise or 0) / 100, 2)


def _when_label(spent_at: Any) -> str:
    """'Today' / 'Yesterday' / 'N days' — the label the mock UI renders."""
    try:
        d = date.fromisoformat(str(spent_at)[:10])
    except Exception:  # noqa: BLE001
        return "—"
    delta = (date.today() - d).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return f"{delta} days"


def shape_expense(row: dict[str, Any]) -> dict[str, Any]:
    conf = row.get("category_confidence")
    return {
        "id": str(row.get("id")),
        "description": row.get("description") or "",
        "merchant": row.get("merchant"),
        "amount_inr": _inr(row.get("amount_paise")),
        "category": row.get("category") or "Other",
        "category_was_auto": bool(row.get("category_was_auto", True)),
        "category_confidence": conf,
        "spent_at": row.get("spent_at"),
        "tax_deductible": bool(row.get("tax_deductible", False)),
        "tax_section": row.get("tax_section"),
        "is_anomaly": bool(row.get("is_anomaly", False)),
        "anomaly_reason": row.get("anomaly_reason"),
        "source": row.get("source") or "manual",
        "receipt_id": str(row["receipt_id"]) if row.get("receipt_id") else None,
        "notes": row.get("notes"),
        "needs_review": bool(
            row.get("category_was_auto", True)
            and conf is not None
            and conf < categorize.AUTO_APPLY_THRESHOLD
        ),
        "when": _when_label(row.get("spent_at")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# --------------------------------------------------------------------------
# Categorize (preview, no save)
# --------------------------------------------------------------------------
def preview_category(payload: schemas.CategorizeIn) -> dict[str, Any]:
    return categorize.categorize(
        description=_strip_html(payload.description),
        merchant=_strip_html(payload.merchant) or None,
    )


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------
def create_expense(citizen_id: str, payload: schemas.ExpenseCreateIn) -> dict[str, Any]:
    description = _strip_html(payload.description)
    if not description:
        raise ValueError("description is required")
    merchant = _strip_html(payload.merchant) or None
    override = schemas.normalize_expense_category(payload.category)

    cls = categorize.categorize(
        description=description, merchant=merchant, category_override=override,
    )
    amount_paise = _paise(payload.amount_inr)
    spent = payload.spent_at or date.today()

    # anomaly scoring against the citizen's own history for that category,
    # falling back to their all-category distribution when it is thin
    history = repo.category_history_paise(citizen_id, cls["category"])
    overall = (
        repo.all_history_paise(citizen_id)
        if len(history) < anomaly.MIN_SAMPLES_STAT else None
    )
    is_anom, reason = anomaly.score(amount_paise, cls["category"], history, overall)

    row = repo.insert_expense({
        "citizen_id": citizen_id,
        "description": description[:255],
        "merchant": merchant[:128] if merchant else None,
        "amount_paise": amount_paise,
        "category": cls["category"],
        "category_was_auto": cls["source"] != "citizen",
        "category_confidence": cls["confidence"],
        "spent_at": spent.isoformat(),
        "tax_deductible": bool(payload.tax_deductible),
        "tax_section": payload.tax_section,
        "is_anomaly": is_anom,
        "anomaly_reason": reason,
        "source": "manual",
        "notes": _strip_html(payload.notes) or None,
    })
    return {"expense": shape_expense(row), "classification": cls}


def get_expense(citizen_id: str, exp_id: str) -> Optional[dict[str, Any]]:
    row = repo.get_expense(citizen_id, exp_id)
    return shape_expense(row) if row else None


def update_expense(citizen_id: str, exp_id: str, payload: schemas.ExpenseUpdateIn) -> dict[str, Any]:
    existing = repo.get_expense(citizen_id, exp_id)
    if not existing:
        raise LookupError(f"expense {exp_id} not found")

    patch: dict[str, Any] = {}
    if payload.description is not None:
        d = _strip_html(payload.description)
        if not d:
            raise ValueError("description cannot be blank")
        patch["description"] = d[:255]
    if payload.merchant is not None:
        patch["merchant"] = _strip_html(payload.merchant)[:128] or None
    if payload.amount_inr is not None:
        patch["amount_paise"] = _paise(payload.amount_inr)
    if payload.spent_at is not None:
        patch["spent_at"] = payload.spent_at.isoformat()
    if payload.tax_deductible is not None:
        patch["tax_deductible"] = bool(payload.tax_deductible)
    if payload.tax_section is not None:
        patch["tax_section"] = payload.tax_section
    if payload.notes is not None:
        patch["notes"] = _strip_html(payload.notes) or None

    if payload.category is not None:
        cat = schemas.normalize_expense_category(payload.category)
        if cat is None:
            raise ValueError(f"unknown category {payload.category!r}")
        patch["category"] = cat
        patch["category_was_auto"] = False
        patch["category_confidence"] = 1.0
        # A manual re-categorisation is the strongest training signal we
        # get — teach the merchant cache so the whole system learns.
        if cat != existing.get("category"):
            categorize.correct(
                existing.get("description") or "", existing.get("merchant"), cat
            )

    # re-score anomaly when the amount or category changed
    if "amount_paise" in patch or "category" in patch:
        cat = patch.get("category", existing.get("category"))
        amt = patch.get("amount_paise", existing.get("amount_paise"))
        history = repo.category_history_paise(citizen_id, cat, exclude_id=exp_id)
        overall = (
            repo.all_history_paise(citizen_id, exclude_id=exp_id)
            if len(history) < anomaly.MIN_SAMPLES_STAT else None
        )
        is_anom, reason = anomaly.score(int(amt), cat, history, overall)
        patch["is_anomaly"] = is_anom
        patch["anomaly_reason"] = reason

    if not patch:
        return shape_expense(existing)
    updated = repo.update_expense(citizen_id, exp_id, patch)
    return shape_expense(updated or {**existing, **patch})


def delete_expense(citizen_id: str, exp_id: str) -> None:
    if not repo.soft_delete_expense(citizen_id, exp_id):
        raise LookupError(f"expense {exp_id} not found")


def list_expenses(
    citizen_id: str,
    category: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    min_amount_inr: Optional[float] = None,
    anomaly_only: bool = False,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    rows, total = repo.list_expenses(
        citizen_id,
        category=category,
        date_from=date_from,
        date_to=date_to,
        min_amount_paise=_paise(min_amount_inr) if min_amount_inr else None,
        anomaly_only=anomaly_only,
        q=q,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [shape_expense(r) for r in rows],
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def _month_bounds(today: Optional[date] = None) -> tuple[date, date]:
    t = today or date.today()
    start = t.replace(day=1)
    return start, t


def dashboard_kpis(citizen_id: str) -> dict[str, Any]:
    start, today = _month_bounds()
    rows = repo.expenses_between(citizen_id, start, today)
    total_paise = sum(int(r["amount_paise"]) for r in rows)
    days_elapsed = max(1, (today - start).days + 1)
    # 7-day sparkline
    per_day: dict[str, int] = {}
    for r in rows:
        per_day[str(r["spent_at"])[:10]] = per_day.get(str(r["spent_at"])[:10], 0) + int(r["amount_paise"])
    spark = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        spark.append(_inr(per_day.get(d, 0)))
    return {
        "month_label": today.strftime("%B %Y").upper(),
        "total_month_inr": _inr(total_paise),
        "avg_daily_inr": _inr(total_paise / days_elapsed),
        "txn_count": len(rows),
        "anomaly_count": sum(1 for r in rows if r.get("is_anomaly")),
        "spark_daily": spark,
    }


def dashboard_by_category(citizen_id: str) -> list[dict[str, Any]]:
    start, today = _month_bounds()
    rows = repo.expenses_between(citizen_id, start, today)
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = r.get("category") or "Other"
        slot = agg.setdefault(c, {"label": c, "value_paise": 0, "txn_count": 0})
        slot["value_paise"] += int(r["amount_paise"])
        slot["txn_count"] += 1
    out = [
        {"label": s["label"], "value_inr": _inr(s["value_paise"]), "txn_count": s["txn_count"]}
        for s in agg.values()
    ]
    out.sort(key=lambda s: s["value_inr"], reverse=True)
    return out


def dashboard_daily_trend(citizen_id: str, days: int = 30) -> dict[str, Any]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    rows = repo.expenses_between(citizen_id, start, today)
    per_day: dict[str, int] = {}
    for r in rows:
        k = str(r["spent_at"])[:10]
        per_day[k] = per_day.get(k, 0) + int(r["amount_paise"])
    points = []
    for i in range(days):
        d = start + timedelta(days=i)
        points.append({"day": d, "total_inr": _inr(per_day.get(d.isoformat(), 0))})
    highest_day = max(points, key=lambda p: p["total_inr"]) if points else None
    if highest_day and highest_day["total_inr"] == 0:
        highest_day = None
    highest_expense = None
    if rows:
        top = max(rows, key=lambda r: int(r["amount_paise"]))
        highest_expense = shape_expense(top)
    return {"points": points, "highest_day": highest_day, "highest_expense": highest_expense}


def dashboard_recent(citizen_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows, _ = repo.list_expenses(citizen_id, limit=limit)
    return [shape_expense(r) for r in rows]


def dashboard_anomalies(citizen_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows, _ = repo.list_expenses(citizen_id, anomaly_only=True, limit=limit)
    return [shape_expense(r) for r in rows]


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
def health() -> dict[str, Any]:
    tables = repo.probe_tables()
    missing = [t["name"] for t in tables if not t["present"]]
    model = categorize.model_status()
    from app.config import settings

    classifier = {
        "lexicon_patterns": sum(len(v) for v in merchants.LEXICON.values()),
        "categories": len(merchants.CATEGORIES),
        **model,
        "groq_configured": bool(getattr(settings, "GROQ_API_KEY", "")),
        "merchant_cache": repo.cache_stats(),
    }
    notes: list[str] = []
    if missing:
        notes.append(
            f"{len(missing)} table(s) missing: {', '.join(missing)} — apply "
            "supabase/migrations/20260720000006_expenses_module_schema.sql"
        )
    if not classifier["svc_loaded"]:
        notes.append("SVC layer not fitted — lexicon/fuzzy/LLM layers still serve.")
    if not classifier["groq_configured"]:
        notes.append("GROQ_API_KEY not set — unseen merchants fall back to model/Other.")
    return {
        "status": "degraded" if missing else "ok",
        "module": "expenses",
        "version": __version__,
        "tables": tables,
        "classifier": classifier,
        "notes": notes,
    }
