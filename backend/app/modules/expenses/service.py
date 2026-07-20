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
# Imports
# --------------------------------------------------------------------------
def _shape_import_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(r.get("id")),
        "description": r.get("parsed_description"),
        "merchant": r.get("parsed_merchant"),
        "amount_inr": _inr_opt(r.get("parsed_amount_paise")),
        "spent_at": r.get("parsed_date"),
        "predicted_category": r.get("predicted_category"),
        "predicted_confidence": r.get("predicted_confidence"),
        "is_duplicate": r.get("is_duplicate_of") is not None,
        "duplicate_of": str(r["is_duplicate_of"]) if r.get("is_duplicate_of") else None,
        "selected_for_commit": bool(r.get("selected_for_commit")),
        "committed_expense_id": str(r["expense_id"]) if r.get("expense_id") else None,
    }


def _shape_batch(
    row: dict[str, Any],
    rows: Optional[list[dict[str, Any]]] = None,
    notes: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "source": row.get("source"),
        "source_label": row.get("source_label"),
        "status": row.get("status") or "pending",
        "total_rows": int(row.get("total_rows") or 0),
        "parsed_rows": int(row.get("parsed_rows") or 0),
        "duplicate_rows": int(row.get("duplicate_rows") or 0),
        "committed_rows": int(row.get("committed_rows") or 0),
        "notes": notes or [],
        "rows": [_shape_import_row(r) for r in (rows or [])],
        "uploaded_at": row.get("uploaded_at"),
        "committed_at": row.get("committed_at"),
    }


def create_import(
    citizen_id: str, content: bytes, filename: str, source: str,
) -> dict[str, Any]:
    """Parse, classify (LLM-capped), duplicate-flag, persist as a batch in
    'parsed' for the citizen to review. Inline: a 2000-row statement
    parses in well under the 30s budget."""
    from app.modules.expenses import imports as imp

    if source == "bank_csv":
        rows, notes = imp.parse_csv(content)
    else:
        rows, notes = imp.parse_pdf(content)

    if not rows:
        raise ValueError("; ".join(notes) if notes else "no rows recognised")

    imp.classify_rows(rows)
    existing = repo.all_recent_expenses(citizen_id)
    dupes = imp.flag_duplicates(rows, existing)

    batch = repo.insert_batch({
        "citizen_id": citizen_id,
        "source": source,
        "source_label": filename[:64],
        "total_rows": len(rows),
        "parsed_rows": len(rows),
        "duplicate_rows": dupes,
        "status": "parsed",
    })
    repo.insert_batch_rows(str(batch["id"]), rows)
    stored = repo.get_batch_rows(str(batch["id"]))
    return _shape_batch(batch, rows=stored, notes=notes)


def get_import(citizen_id: str, batch_id: str) -> Optional[dict[str, Any]]:
    batch = repo.get_batch(citizen_id, batch_id)
    if not batch:
        return None
    return _shape_batch(batch, rows=repo.get_batch_rows(batch_id))


def confirm_import(
    citizen_id: str, batch_id: str, payload: schemas.ImportConfirmIn,
) -> dict[str, Any]:
    batch = repo.get_batch(citizen_id, batch_id)
    if not batch:
        raise LookupError(f"import batch {batch_id} not found")
    if batch.get("status") == "committed":
        raise ValueError("batch already committed")

    rows = repo.get_batch_rows(batch_id)
    wanted: Optional[set[str]] = set(payload.row_ids) if payload.row_ids else None

    committed = 0
    skipped_dupes = 0
    for r in rows:
        rid = str(r.get("id"))
        if r.get("expense_id"):
            continue  # already committed earlier
        if wanted is not None and rid not in wanted:
            continue
        if r.get("is_duplicate_of") and not payload.include_duplicates:
            skipped_dupes += 1
            continue
        amount = r.get("parsed_amount_paise")
        spent = r.get("parsed_date")
        if not amount or not spent:
            continue
        category = r.get("predicted_category") or "Other"
        history = repo.category_history_paise(citizen_id, category)
        overall = (
            repo.all_history_paise(citizen_id)
            if len(history) < anomaly.MIN_SAMPLES_STAT else None
        )
        is_anom, reason = anomaly.score(int(amount), category, history, overall)
        expense = repo.insert_expense({
            "citizen_id": citizen_id,
            "description": (r.get("parsed_description") or "Imported transaction")[:255],
            "merchant": r.get("parsed_merchant"),
            "amount_paise": int(amount),
            "category": category,
            "category_was_auto": True,
            "category_confidence": r.get("predicted_confidence"),
            "spent_at": str(spent)[:10],
            "is_anomaly": is_anom,
            "anomaly_reason": reason,
            "source": batch.get("source") or "bank_csv",
            "import_batch_id": batch_id,
        })
        repo.mark_row_committed(rid, str(expense["id"]))
        committed += 1

    repo.update_batch(citizen_id, batch_id, {
        "status": "committed",
        "committed_rows": int(batch.get("committed_rows") or 0) + committed,
        "committed_at": datetime.now(timezone.utc).isoformat(),
    })
    fresh = repo.get_batch(citizen_id, batch_id) or batch
    return {
        "batch": _shape_batch(fresh, rows=repo.get_batch_rows(batch_id)),
        "committed": committed,
        "skipped_duplicates": skipped_dupes,
    }


# --------------------------------------------------------------------------
# Receipts
# --------------------------------------------------------------------------
def _inr_opt(paise: Any) -> Optional[float]:
    return _inr(paise) if paise is not None else None


def shape_receipt(
    row: dict[str, Any],
    items: Optional[list[dict[str, Any]]] = None,
    sign: bool = False,
) -> dict[str, Any]:
    from app.modules.expenses import receipts as rc

    return {
        "id": str(row.get("id")),
        "status": row.get("status") or "review",
        "merchant": row.get("merchant"),
        "items": [
            {
                "name": i.get("name") or "",
                "qty": int(i.get("qty") or 1),
                "unit_price_inr": _inr_opt(i.get("unit_price_paise")),
                "line_total_inr": _inr_opt(i.get("line_total_paise")),
            }
            for i in (items or [])
        ],
        "subtotal_inr": _inr_opt(row.get("subtotal_paise")),
        "tax_inr": _inr_opt(row.get("tax_paise")),
        "total_inr": _inr_opt(row.get("total_paise")),
        "purchase_date": row.get("purchase_date"),
        "predicted_category": row.get("predicted_category"),
        "confidence": row.get("confidence"),
        "ocr_confidence": (row.get("_ocr_confidence")),
        "ocr_engine": row.get("ocr_engine"),
        "image_url": rc.signed_url(row.get("storage_path") or "") if sign else None,
        "expense_id": str(row["expense_id"]) if row.get("expense_id") else None,
        "created_at": row.get("created_at"),
        "confirmed_at": row.get("confirmed_at"),
    }


def upload_receipt(
    citizen_id: str, content: bytes, filename: str, ext: str, content_type: str,
) -> dict[str, Any]:
    """OCR + parse + classify inline (2-5s typical on OCR.Space), store the
    image in the private bucket, land the receipt in 'review'. Storage
    first, row second, object removed if the row fails — no orphans."""
    from app.modules.expenses import receipts as rc

    raw_text, ocr_conf, engine = rc.run_ocr(content, filename)
    fields = rc.parse_fields(raw_text)

    cls = None
    if fields["merchant"] or raw_text:
        cls = categorize.categorize(
            description=(fields["merchant"] or raw_text[:120]),
            merchant=fields["merchant"],
        )

    path = rc.upload(citizen_id, content, ext, content_type)
    try:
        row = repo.insert_receipt({
            "citizen_id": citizen_id,
            "storage_path": path,
            "original_filename": filename[:255],
            "status": "review",
            "merchant": fields["merchant"],
            "subtotal_paise": fields["subtotal_paise"],
            "tax_paise": fields["tax_paise"],
            "total_paise": fields["total_paise"],
            "purchase_date": fields["purchase_date"].isoformat() if fields["purchase_date"] else None,
            "predicted_category": cls["category"] if cls else None,
            "confidence": cls["confidence"] if cls else None,
            "ocr_raw_text": raw_text[:20000] or None,
            "ocr_engine": engine,
        })
    except Exception:
        rc.remove(path)
        raise
    repo.insert_receipt_items(str(row["id"]), fields["items"])
    shaped = shape_receipt(
        {**row, "_ocr_confidence": ocr_conf},
        items=fields["items"], sign=True,
    )
    return shaped


def get_receipt(citizen_id: str, receipt_id: str, sign: bool = True) -> Optional[dict[str, Any]]:
    row = repo.get_receipt(citizen_id, receipt_id)
    if not row:
        return None
    return shape_receipt(row, items=repo.get_receipt_items(receipt_id), sign=sign)


def list_receipts(
    citizen_id: str,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    cat = schemas.normalize_expense_category(category) if category else None
    rows, total = repo.list_receipts(citizen_id, category=cat, status=status,
                                     limit=limit, offset=offset)
    return {
        "data": [shape_receipt(r) for r in rows],   # list view: no signing
        "meta": {"total": total, "limit": limit, "offset": offset},
    }


def edit_receipt(citizen_id: str, receipt_id: str, payload: schemas.ReceiptEditIn) -> dict[str, Any]:
    row = repo.get_receipt(citizen_id, receipt_id)
    if not row:
        raise LookupError(f"receipt {receipt_id} not found")
    if row.get("status") == "confirmed":
        raise ValueError("receipt already confirmed — edit the linked expense instead")

    patch: dict[str, Any] = {}
    if payload.merchant is not None:
        patch["merchant"] = _strip_html(payload.merchant)[:128] or None
    if payload.total_inr is not None:
        patch["total_paise"] = _paise(payload.total_inr)
    if payload.tax_inr is not None:
        patch["tax_paise"] = _paise(payload.tax_inr)
    if payload.purchase_date is not None:
        patch["purchase_date"] = payload.purchase_date.isoformat()
    if payload.category is not None:
        cat = schemas.normalize_expense_category(payload.category)
        if cat is None:
            raise ValueError(f"unknown category {payload.category!r}")
        patch["predicted_category"] = cat
        patch["confidence"] = 1.0
    if not patch:
        raise ValueError("nothing to update")
    updated = repo.update_receipt(citizen_id, receipt_id, patch)
    return shape_receipt(updated or {**row, **patch},
                         items=repo.get_receipt_items(receipt_id), sign=True)


def confirm_receipt(
    citizen_id: str, receipt_id: str, payload: schemas.ReceiptConfirmIn,
) -> dict[str, Any]:
    """Turn a reviewed receipt into a real, anomaly-scored expense."""
    row = repo.get_receipt(citizen_id, receipt_id)
    if not row:
        raise LookupError(f"receipt {receipt_id} not found")
    if row.get("status") == "confirmed":
        raise ValueError("receipt already confirmed")
    total = row.get("total_paise")
    if not total or int(total) <= 0:
        raise ValueError("receipt has no total — edit it before confirming")

    merchant = row.get("merchant")
    category = row.get("predicted_category") or "Other"
    spent = row.get("purchase_date") or date.today().isoformat()

    history = repo.category_history_paise(citizen_id, category)
    overall = (
        repo.all_history_paise(citizen_id)
        if len(history) < anomaly.MIN_SAMPLES_STAT else None
    )
    is_anom, reason = anomaly.score(int(total), category, history, overall)

    expense_row = repo.insert_expense({
        "citizen_id": citizen_id,
        "description": (merchant or "Receipt")[:255],
        "merchant": merchant,
        "amount_paise": int(total),
        "category": category,
        "category_was_auto": bool(row.get("confidence") != 1.0),
        "category_confidence": row.get("confidence"),
        "spent_at": str(spent)[:10],
        "tax_deductible": bool(payload.tax_deductible),
        "tax_section": payload.tax_section,
        "is_anomaly": is_anom,
        "anomaly_reason": reason,
        "source": "receipt_ocr",
        "receipt_id": str(row["id"]),
    })
    updated = repo.update_receipt(citizen_id, receipt_id, {
        "status": "confirmed",
        "expense_id": str(expense_row["id"]),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "receipt": shape_receipt(updated or row, items=repo.get_receipt_items(receipt_id)),
        "expense": shape_expense(expense_row),
    }


def receipt_image_url(citizen_id: str, receipt_id: str) -> Optional[str]:
    from app.modules.expenses import receipts as rc

    row = repo.get_receipt(citizen_id, receipt_id)
    if not row:
        return None
    return rc.signed_url(row.get("storage_path") or "")


# --------------------------------------------------------------------------
# Budgets
# --------------------------------------------------------------------------
def _period_bounds(period: str, today: Optional[date] = None) -> tuple[date, date, str]:
    """(start, end, label) of the CURRENT period. Spend against a budget is
    always computed live from expenses inside these bounds — there is no
    stored spent counter to drift."""
    t = today or date.today()
    if period == "weekly":
        start = t - timedelta(days=t.weekday())
        return start, t, f"WEEK OF {start.strftime('%d %b').upper()}"
    if period == "yearly":
        # Indian financial year: 1 April – 31 March
        fy_start = date(t.year if t.month >= 4 else t.year - 1, 4, 1)
        return fy_start, t, f"FY{(fy_start.year + 1) % 100}"
    start = t.replace(day=1)
    return start, t, t.strftime("%B %Y").upper()


def _shape_budget(row: dict[str, Any], spent_paise: int) -> dict[str, Any]:
    amount_paise = int(row.get("amount_paise") or 1)
    pct = round(spent_paise * 100.0 / amount_paise, 1)
    threshold = int(row.get("alert_threshold_pct") or 80)
    status = "over" if pct > 100 else ("near" if pct >= threshold else "under")
    _, _, label = _period_bounds(row.get("period") or "monthly")
    return {
        "id": str(row.get("id")),
        "category": row.get("category"),
        "amount_inr": _inr(amount_paise),
        "period": row.get("period") or "monthly",
        "spent_inr": _inr(spent_paise),
        "pct_used": pct,
        "status": status,
        "alert_threshold_pct": threshold,
        "remaining_inr": _inr(amount_paise - spent_paise),
        "period_label": label,
        "created_at": row.get("created_at"),
    }


def list_budgets(citizen_id: str) -> list[dict[str, Any]]:
    rows = repo.list_budgets(citizen_id)
    if not rows:
        return []
    # one expenses fetch covers every budget's window (widest wins)
    starts = [_period_bounds(r.get("period") or "monthly")[0] for r in rows]
    window_start = min(starts)
    expenses = repo.expenses_between(citizen_id, window_start, date.today())
    out = []
    for r in rows:
        start, end, _ = _period_bounds(r.get("period") or "monthly")
        spent = sum(
            int(e["amount_paise"]) for e in expenses
            if e.get("category") == r.get("category")
            and start.isoformat() <= str(e["spent_at"])[:10] <= end.isoformat()
        )
        out.append(_shape_budget(r, spent))
    return out


def create_budget(citizen_id: str, payload: schemas.BudgetCreateIn) -> dict[str, Any]:
    cat = schemas.normalize_expense_category(payload.category)
    if cat is None:
        raise ValueError(f"unknown category {payload.category!r}")
    try:
        row = repo.insert_budget({
            "citizen_id": citizen_id,
            "category": cat,
            "amount_paise": _paise(payload.amount_inr),
            "period": payload.period,
            "alert_threshold_pct": payload.alert_threshold_pct,
        })
    except Exception as e:
        if "23505" in str(e) or "duplicate key" in str(e).lower():
            raise ValueError(
                f"an active {payload.period} budget for {cat} already exists — edit it instead"
            ) from e
        raise
    return list_budget_one(citizen_id, row)


def list_budget_one(citizen_id: str, row: dict[str, Any]) -> dict[str, Any]:
    start, end, _ = _period_bounds(row.get("period") or "monthly")
    expenses = repo.expenses_between(citizen_id, start, end)
    spent = sum(
        int(e["amount_paise"]) for e in expenses
        if e.get("category") == row.get("category")
    )
    return _shape_budget(row, spent)


def update_budget(citizen_id: str, budget_id: str, payload: schemas.BudgetUpdateIn) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if payload.amount_inr is not None:
        patch["amount_paise"] = _paise(payload.amount_inr)
    if payload.period is not None:
        patch["period"] = payload.period
    if payload.alert_threshold_pct is not None:
        patch["alert_threshold_pct"] = payload.alert_threshold_pct
    if not patch:
        raise ValueError("nothing to update")
    row = repo.update_budget(citizen_id, budget_id, patch)
    if row is None:
        raise LookupError(f"budget {budget_id} not found")
    return list_budget_one(citizen_id, row)


def delete_budget(citizen_id: str, budget_id: str) -> None:
    if not repo.deactivate_budget(citizen_id, budget_id):
        raise LookupError(f"budget {budget_id} not found")


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
def _fy_bounds(today: Optional[date] = None) -> tuple[date, date, str]:
    t = today or date.today()
    start = date(t.year if t.month >= 4 else t.year - 1, 4, 1)
    return start, t, f"FY{(start.year + 1) % 100}"


def fy_summary(citizen_id: str) -> dict[str, Any]:
    """FY spend + tax figures from real rows. savings_pct and
    net_worth_delta stay null — they need income/asset data the platform
    does not hold, and the mock's 22% / +₹18k were fiction."""
    start, today, fy = _fy_bounds()
    rows = repo.expenses_between(citizen_id, start, today)
    total = sum(int(r["amount_paise"]) for r in rows)
    deductible = sum(int(r["amount_paise"]) for r in rows if r.get("tax_deductible"))
    months = max(1, (today.year - start.year) * 12 + today.month - start.month + 1)
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r.get("category") or "Other"] = by_cat.get(r.get("category") or "Other", 0) + int(r["amount_paise"])
    top = max(by_cat.items(), key=lambda kv: kv[1])[0] if by_cat else None
    return {
        "fy": fy,
        "fy_start": start,
        "total_spend_inr": _inr(total),
        "tax_deductible_inr": _inr(deductible),
        "txn_count": len(rows),
        "top_category": top,
        "avg_monthly_inr": _inr(total / months),
        "savings_pct": None,
        "net_worth_delta_inr": None,
    }


def monthly_trend(citizen_id: str, months: int = 12) -> list[dict[str, Any]]:
    today = date.today()
    # first day of the window month
    y, m = today.year, today.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    start = date(y, m, 1)
    rows = repo.expenses_between(citizen_id, start, today)
    per_month: dict[str, int] = {}
    for r in rows:
        key = str(r["spent_at"])[:7]
        per_month[key] = per_month.get(key, 0) + int(r["amount_paise"])
    out = []
    yy, mm = y, m
    for _ in range(months):
        key = f"{yy:04d}-{mm:02d}"
        out.append({
            "month": key,
            "label": date(yy, mm, 1).strftime("%b").upper(),
            "total_inr": _inr(per_month.get(key, 0)),
        })
        mm += 1
        if mm > 12:
            mm = 1
            yy += 1
    return out


def tax_summary(citizen_id: str) -> dict[str, Any]:
    start, today, fy = _fy_bounds()
    rows = repo.expenses_between(citizen_id, start, today)
    buckets = {"80C": 0, "80D": 0, "BUSINESS": 0, "HRA": 0, "OTHER": 0}
    by_month: dict[str, int] = {}
    for r in rows:
        if not r.get("tax_deductible"):
            continue
        amt = int(r["amount_paise"])
        sec = (r.get("tax_section") or "").upper()
        buckets[sec if sec in ("80C", "80D", "BUSINESS", "HRA") else "OTHER"] += amt
        mk = str(r["spent_at"])[:7]
        by_month[mk] = by_month.get(mk, 0) + amt
    total = sum(buckets.values())
    return {
        "fy": fy,
        "section_80c_inr": _inr(buckets["80C"]),
        "section_80d_inr": _inr(buckets["80D"]),
        "business_inr": _inr(buckets["BUSINESS"]),
        "hra_inr": _inr(buckets["HRA"]),
        "other_deductible_inr": _inr(buckets["OTHER"]),
        "total_deductible_inr": _inr(total),
        "breakdown_by_month": {k: _inr(v) for k, v in sorted(by_month.items())},
        "note": (
            "Computed from expenses you marked tax-deductible with their "
            "section. This is a working summary, not tax advice — verify "
            "against receipts before ITR filing."
        ),
    }


_EXPORT_COLUMNS = (
    "spent_at", "description", "merchant", "category", "amount_inr",
    "tax_deductible", "tax_section", "is_anomaly", "source", "notes",
)


def _export_rows(citizen_id: str) -> list[dict[str, Any]]:
    start, today, _ = _fy_bounds()
    rows = repo.expenses_between(citizen_id, start, today)
    rows.sort(key=lambda r: str(r.get("spent_at")))
    return [
        {
            "spent_at": str(r.get("spent_at"))[:10],
            "description": r.get("description") or "",
            "merchant": r.get("merchant") or "",
            "category": r.get("category") or "",
            "amount_inr": _inr(r.get("amount_paise")),
            "tax_deductible": bool(r.get("tax_deductible")),
            "tax_section": r.get("tax_section") or "",
            "is_anomaly": bool(r.get("is_anomaly")),
            "source": r.get("source") or "",
            "notes": r.get("notes") or "",
        }
        for r in rows
    ]


def export_csv(citizen_id: str) -> tuple[bytes, str]:
    import csv as _csv
    import io as _io

    rows = _export_rows(citizen_id)
    buf = _io.StringIO()
    w = _csv.DictWriter(buf, fieldnames=_EXPORT_COLUMNS)
    w.writeheader()
    w.writerows(rows)
    _, _, fy = _fy_bounds()
    return buf.getvalue().encode("utf-8-sig"), f"citadel-expenses-{fy}.csv"


def export_xlsx(citizen_id: str) -> tuple[bytes, str]:
    import io as _io

    from openpyxl import Workbook

    rows = _export_rows(citizen_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws.append([c for c in _EXPORT_COLUMNS])
    for r in rows:
        ws.append([r[c] for c in _EXPORT_COLUMNS])
    ts = tax_summary(citizen_id)
    ws2 = wb.create_sheet("Tax Summary")
    for label, key in (("Section 80C", "section_80c_inr"), ("Section 80D", "section_80d_inr"),
                       ("Business", "business_inr"), ("HRA", "hra_inr"),
                       ("Other deductible", "other_deductible_inr"),
                       ("TOTAL DEDUCTIBLE", "total_deductible_inr")):
        ws2.append([label, ts[key]])
    buf = _io.BytesIO()
    wb.save(buf)
    _, _, fy = _fy_bounds()
    return buf.getvalue(), f"citadel-expenses-{fy}.xlsx"


def export_tax_package(citizen_id: str) -> tuple[bytes, str]:
    """ZIP: full CSV + tax summary JSON + deductible-only CSV — the bundle
    a citizen hands their CA before ITR filing."""
    import io as _io
    import json as _json
    import zipfile

    csv_bytes, csv_name = export_csv(citizen_id)
    ts = tax_summary(citizen_id)
    deductible = [r for r in _export_rows(citizen_id) if r["tax_deductible"]]

    import csv as _csv
    dbuf = _io.StringIO()
    w = _csv.DictWriter(dbuf, fieldnames=_EXPORT_COLUMNS)
    w.writeheader()
    w.writerows(deductible)

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(csv_name, csv_bytes)
        z.writestr(f"tax-summary-{ts['fy']}.json", _json.dumps(ts, indent=2, default=str))
        z.writestr(f"deductible-only-{ts['fy']}.csv", dbuf.getvalue().encode("utf-8-sig"))
    return buf.getvalue(), f"citadel-tax-package-{ts['fy']}.zip"


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
