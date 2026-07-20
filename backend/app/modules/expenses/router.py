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

from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
