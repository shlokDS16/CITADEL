"""
Expense Categorizer — HTTP endpoints (spec-08, base /api/v1/expenses).

Identity: personal finance MUST be scoped per citizen even pre-auth, so
X-User-Id (a uuid — the browser identity the tickets module mints) is
REQUIRED on every citizen route; a missing/malformed value is a 400, not
an implicit "show everything". Phase 3 replaces it with the JWT subject.

Classification is CPU + (rarely) one Groq hop → run_in_threadpool, tight
ML rate budget on the endpoints that can reach the LLM.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.shared.ratelimit import rate_limit
from app.modules.expenses import schemas, service

log = logging.getLogger("citadel.expenses.router")
router = APIRouter()

_TAG = "expenses"
_RL_ML = Depends(rate_limit("expenses:ml", 30, 60))    # can reach Groq (cached ⇒ cheap)
_RL_STD = Depends(rate_limit("expenses:std", 60, 60))


def _citizen(x_user_id: Optional[str] = Header(default=None, alias="X-User-Id")) -> str:
    if not x_user_id:
        raise HTTPException(status_code=400, detail="X-User-Id header (uuid) is required")
    try:
        return str(UUID(x_user_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="X-User-Id must be a uuid")


@router.get(
    "/v1/expenses/health",
    response_model=schemas.HealthResponse,
    tags=[_TAG],
    summary="Liveness — tables, classifier layers, merchant cache",
)
async def health() -> schemas.HealthResponse:
    try:
        return schemas.HealthResponse(**await run_in_threadpool(service.health))
    except Exception as e:  # noqa: BLE001
        log.exception("expenses health failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/v1/expenses/categorize",
    response_model=schemas.CategorizeOut,
    tags=[_TAG],
    summary="Predict a category (no save) — powers the Add form live",
    dependencies=[_RL_ML],
)
async def categorize_preview(payload: schemas.CategorizeIn) -> schemas.CategorizeOut:
    if not (payload.description or payload.merchant):
        raise HTTPException(status_code=400, detail="description or merchant required")
    try:
        return schemas.CategorizeOut(**await run_in_threadpool(service.preview_category, payload))
    except Exception as e:  # noqa: BLE001
        log.exception("categorize preview failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/v1/expenses",
    response_model=schemas.ExpenseCreateOut,
    status_code=201,
    tags=[_TAG],
    summary="Add an expense (auto-categorised + anomaly-scored)",
    dependencies=[_RL_ML],
)
async def create_expense(
    payload: schemas.ExpenseCreateIn,
    citizen: str = Depends(_citizen),
) -> schemas.ExpenseCreateOut:
    try:
        result = await run_in_threadpool(service.create_expense, citizen, payload)
        return schemas.ExpenseCreateOut(
            expense=schemas.ExpenseOut(**result["expense"]),
            classification=schemas.CategorizeOut(**result["classification"]),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("create expense failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---- dashboard (declared before /{exp_id} so the paths don't collide) ----
@router.get(
    "/v1/expenses/dashboard/kpis",
    response_model=schemas.DashboardKpisOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Month total, avg daily, txn count, anomaly count",
)
async def dashboard_kpis(citizen: str = Depends(_citizen)) -> schemas.DashboardKpisOut:
    return schemas.DashboardKpisOut(**await run_in_threadpool(service.dashboard_kpis, citizen))


@router.get(
    "/v1/expenses/dashboard/by-category",
    response_model=list[schemas.CategorySliceOut],
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Current-month donut data",
)
async def dashboard_by_category(citizen: str = Depends(_citizen)) -> list[schemas.CategorySliceOut]:
    rows = await run_in_threadpool(service.dashboard_by_category, citizen)
    return [schemas.CategorySliceOut(**r) for r in rows]


@router.get(
    "/v1/expenses/dashboard/daily-trend",
    response_model=schemas.DailyTrendOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Spend per day, last N days",
)
async def dashboard_daily_trend(
    days: int = Query(default=30, ge=7, le=90),
    citizen: str = Depends(_citizen),
) -> schemas.DailyTrendOut:
    return schemas.DailyTrendOut(
        **await run_in_threadpool(service.dashboard_daily_trend, citizen, days)
    )


@router.get(
    "/v1/expenses/dashboard/recent",
    response_model=list[schemas.ExpenseOut],
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Latest transactions with anomaly flags",
)
async def dashboard_recent(
    limit: int = Query(default=10, ge=1, le=50),
    citizen: str = Depends(_citizen),
) -> list[schemas.ExpenseOut]:
    rows = await run_in_threadpool(service.dashboard_recent, citizen, limit)
    return [schemas.ExpenseOut(**r) for r in rows]


@router.get(
    "/v1/expenses/dashboard/anomalies",
    response_model=list[schemas.ExpenseOut],
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Flagged expenses with plain-language reasons",
)
async def dashboard_anomalies(citizen: str = Depends(_citizen)) -> list[schemas.ExpenseOut]:
    rows = await run_in_threadpool(service.dashboard_anomalies, citizen)
    return [schemas.ExpenseOut(**r) for r in rows]


def _max_body(content_length: Optional[str] = Header(default=None)) -> None:
    """Reject oversized uploads from Content-Length before Starlette
    spools the body. Shared by imports + receipts."""
    if content_length is None:
        return
    try:
        n = int(content_length)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid Content-Length")
    from app.config import settings

    if n > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="upload exceeds size limit")


# ---- imports (bank statements) ----
@router.post(
    "/v1/expenses/imports/csv",
    response_model=schemas.ImportBatchOut,
    status_code=201,
    tags=[_TAG],
    summary="Upload a bank/card CSV — parsed, classified, duplicate-flagged",
    dependencies=[Depends(rate_limit("expenses:import", 5, 60)), Depends(_max_body)],
)
async def import_csv(
    file: UploadFile = File(...),
    citizen: str = Depends(_citizen),
) -> schemas.ImportBatchOut:
    name = file.filename or "statement.csv"
    if not name.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="expected a .csv file")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        row = await run_in_threadpool(service.create_import, citizen, content, name, "bank_csv")
        return schemas.ImportBatchOut(**row)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("csv import failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/v1/expenses/imports/pdf",
    response_model=schemas.ImportBatchOut,
    status_code=201,
    tags=[_TAG],
    summary="Upload a bank PDF statement (text layer required — scans refused)",
    dependencies=[Depends(rate_limit("expenses:import", 5, 60)), Depends(_max_body)],
)
async def import_pdf(
    file: UploadFile = File(...),
    citizen: str = Depends(_citizen),
) -> schemas.ImportBatchOut:
    from app.shared.filetype import assert_upload_kind

    name = file.filename or "statement.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="expected a .pdf file")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    assert_upload_kind(name, content, {"pdf"})
    try:
        row = await run_in_threadpool(service.create_import, citizen, content, name, "bank_pdf")
        return schemas.ImportBatchOut(**row)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("pdf import failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/v1/expenses/imports/{batch_id}",
    response_model=schemas.ImportBatchOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Import batch status + per-row classification and duplicate flags",
)
async def get_import(batch_id: str, citizen: str = Depends(_citizen)) -> schemas.ImportBatchOut:
    row = await run_in_threadpool(service.get_import, citizen, batch_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"import batch {batch_id} not found")
    return schemas.ImportBatchOut(**row)


@router.post(
    "/v1/expenses/imports/{batch_id}/confirm",
    response_model=schemas.ImportConfirmOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Commit selected rows to expenses (duplicates skipped unless opted in)",
)
async def confirm_import(
    batch_id: str,
    payload: schemas.ImportConfirmIn,
    citizen: str = Depends(_citizen),
) -> schemas.ImportConfirmOut:
    try:
        result = await run_in_threadpool(service.confirm_import, citizen, batch_id, payload)
        return schemas.ImportConfirmOut(
            batch=schemas.ImportBatchOut(**result["batch"]),
            committed=result["committed"],
            skipped_duplicates=result["skipped_duplicates"],
        )
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=409, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("confirm import failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---- receipts ----
_RECEIPT_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


@router.post(
    "/v1/expenses/receipts/upload",
    response_model=schemas.ReceiptOut,
    status_code=201,
    tags=[_TAG],
    summary="Scan a receipt — OCR + field extraction + category, lands in review",
    dependencies=[Depends(rate_limit("expenses:ocr", 10, 60)), Depends(_max_body)],
)
async def upload_receipt(
    file: UploadFile = File(...),
    citizen: str = Depends(_citizen),
) -> schemas.ReceiptOut:
    from app.config import settings
    from app.shared.filetype import assert_upload_kind
    from app.modules.expenses import receipts as rc

    name = file.filename or "receipt.jpg"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in _RECEIPT_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"extension {ext or '(none)'} not allowed; expected {', '.join(sorted(_RECEIPT_EXTS))}",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="upload exceeds size limit")
    assert_upload_kind(name, content, {"image"})   # content sniff → 415 on spoof

    ok, note = await run_in_threadpool(rc.ensure_bucket)
    if not ok:
        raise HTTPException(status_code=503, detail=note or "receipt storage unavailable")
    try:
        row = await run_in_threadpool(
            service.upload_receipt, citizen, content, name,
            ext, file.content_type or "image/jpeg",
        )
        return schemas.ReceiptOut(**row)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("receipt upload failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/v1/expenses/receipts",
    response_model=schemas.ReceiptListOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="List receipts — filter ?cat=&status=",
)
async def list_receipts(
    cat: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    citizen: str = Depends(_citizen),
) -> schemas.ReceiptListOut:
    result = await run_in_threadpool(
        service.list_receipts, citizen, cat, status, limit, offset
    )
    return schemas.ReceiptListOut(**result)


@router.get(
    "/v1/expenses/receipts/{receipt_id}",
    response_model=schemas.ReceiptOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Receipt detail with extracted fields + signed image URL",
)
async def get_receipt(receipt_id: str, citizen: str = Depends(_citizen)) -> schemas.ReceiptOut:
    row = await run_in_threadpool(service.get_receipt, citizen, receipt_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"receipt {receipt_id} not found")
    return schemas.ReceiptOut(**row)


@router.post(
    "/v1/expenses/receipts/{receipt_id}/edit",
    response_model=schemas.ReceiptOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Correct OCR fields before confirming",
)
async def edit_receipt(
    receipt_id: str, payload: schemas.ReceiptEditIn, citizen: str = Depends(_citizen),
) -> schemas.ReceiptOut:
    try:
        return schemas.ReceiptOut(
            **await run_in_threadpool(service.edit_receipt, citizen, receipt_id, payload)
        )
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=409 if "confirmed" in str(ve) else 400, detail=str(ve))


@router.post(
    "/v1/expenses/receipts/{receipt_id}/confirm",
    response_model=schemas.ReceiptConfirmOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Confirm extraction — creates the linked, anomaly-scored expense",
)
async def confirm_receipt(
    receipt_id: str,
    payload: schemas.ReceiptConfirmIn,
    citizen: str = Depends(_citizen),
) -> schemas.ReceiptConfirmOut:
    try:
        result = await run_in_threadpool(
            service.confirm_receipt, citizen, receipt_id, payload
        )
        return schemas.ReceiptConfirmOut(
            receipt=schemas.ReceiptOut(**result["receipt"]),
            expense=schemas.ExpenseOut(**result["expense"]),
        )
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=409, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("confirm receipt failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/v1/expenses/receipts/{receipt_id}/image",
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Pre-signed receipt image URL (5 min TTL)",
)
async def receipt_image(receipt_id: str, citizen: str = Depends(_citizen)) -> dict[str, object]:
    url = await run_in_threadpool(service.receipt_image_url, citizen, receipt_id)
    if not url:
        raise HTTPException(status_code=404, detail="receipt not found")
    from app.modules.expenses import receipts as rc

    return {"download_url": url, "expires_in": rc.SIGNED_URL_TTL_SECONDS}


# ---- budgets ----
@router.get(
    "/v1/expenses/budgets",
    response_model=list[schemas.BudgetOut],
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Budgets with live spent/pct/status for the current period",
)
async def list_budgets(citizen: str = Depends(_citizen)) -> list[schemas.BudgetOut]:
    rows = await run_in_threadpool(service.list_budgets, citizen)
    return [schemas.BudgetOut(**r) for r in rows]


@router.post(
    "/v1/expenses/budgets",
    response_model=schemas.BudgetOut,
    status_code=201,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Create a per-category budget",
)
async def create_budget(
    payload: schemas.BudgetCreateIn, citizen: str = Depends(_citizen),
) -> schemas.BudgetOut:
    try:
        return schemas.BudgetOut(**await run_in_threadpool(service.create_budget, citizen, payload))
    except ValueError as ve:
        # duplicate active budget is a state conflict, not bad syntax
        code = 409 if "already exists" in str(ve) else 400
        raise HTTPException(status_code=code, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("create budget failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/v1/expenses/budgets/{budget_id}",
    response_model=schemas.BudgetOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Update amount / period / alert threshold",
)
async def update_budget(
    budget_id: str, payload: schemas.BudgetUpdateIn, citizen: str = Depends(_citizen),
) -> schemas.BudgetOut:
    try:
        return schemas.BudgetOut(
            **await run_in_threadpool(service.update_budget, citizen, budget_id, payload)
        )
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))


@router.delete(
    "/v1/expenses/budgets/{budget_id}",
    status_code=204,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Deactivate a budget (frees the category slot, keeps history)",
)
async def delete_budget(budget_id: str, citizen: str = Depends(_citizen)) -> None:
    try:
        await run_in_threadpool(service.delete_budget, citizen, budget_id)
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))


# ---- list / detail / edit / delete ----
@router.get(
    "/v1/expenses",
    response_model=schemas.ExpenseListOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="List expenses — filters: category, dates, min amount, anomaly, q",
)
async def list_expenses(
    category: Optional[str] = Query(default=None),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    min_amt: Optional[float] = Query(default=None, gt=0),
    anomaly: bool = Query(default=False),
    q: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    citizen: str = Depends(_citizen),
) -> schemas.ExpenseListOut:
    result = await run_in_threadpool(
        service.list_expenses, citizen, category, date_from, date_to,
        min_amt, anomaly, q, limit, offset,
    )
    return schemas.ExpenseListOut(**result)


@router.get(
    "/v1/expenses/{exp_id}",
    response_model=schemas.ExpenseOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Expense detail",
)
async def get_expense(exp_id: str, citizen: str = Depends(_citizen)) -> schemas.ExpenseOut:
    row = await run_in_threadpool(service.get_expense, citizen, exp_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"expense {exp_id} not found")
    return schemas.ExpenseOut(**row)


@router.patch(
    "/v1/expenses/{exp_id}",
    response_model=schemas.ExpenseOut,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Edit an expense (a category edit teaches the merchant cache)",
)
async def update_expense(
    exp_id: str,
    payload: schemas.ExpenseUpdateIn,
    citizen: str = Depends(_citizen),
) -> schemas.ExpenseOut:
    try:
        return schemas.ExpenseOut(
            **await run_in_threadpool(service.update_expense, citizen, exp_id, payload)
        )
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:  # noqa: BLE001
        log.exception("update expense failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/v1/expenses/{exp_id}",
    status_code=204,
    tags=[_TAG],
    dependencies=[_RL_STD],
    summary="Soft-delete an expense",
)
async def delete_expense(exp_id: str, citizen: str = Depends(_citizen)) -> None:
    try:
        await run_in_threadpool(service.delete_expense, citizen, exp_id)
    except LookupError as le:
        raise HTTPException(status_code=404, detail=str(le))
