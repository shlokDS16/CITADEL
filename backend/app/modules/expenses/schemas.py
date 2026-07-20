"""
Pydantic models for the expenses module.

Money convention (spec-08 deviation, recorded in migration 20260720000006):
the DB stores paise as bigint; the API accepts and returns **rupees** as
`amount_inr` (float in, rounded int paise internally). The mock UI works
in rupees and the spec's own field name says inr — one wire unit, one
storage unit, converted in service.py only.

Categories are display names ("Food & Dining"), the single vocabulary
shared by merchants.py, the DB CHECKs and the UI.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.modules.expenses.merchants import CATEGORIES

Category = Literal[
    "Food & Dining", "Groceries", "Transport", "Utilities", "Healthcare",
    "Shopping", "Education", "Entertainment", "Housing", "Insurance", "Other",
]
TaxSection = Literal["80C", "80D", "HRA", "BUSINESS", "NONE"]
Source = Literal["manual", "receipt_ocr", "bank_csv", "bank_pdf", "upi", "card"]


def normalize_expense_category(value: Optional[str]) -> Optional[str]:
    """'Auto-detect'/blank/None → None; otherwise case-insensitive match
    against the canonical list (accepts 'food & dining', 'FOOD & DINING')."""
    if value is None:
        return None
    raw = value.strip()
    if not raw or raw.lower() in {"auto-detect", "auto", "autodetect"}:
        return None
    low = raw.lower()
    for c in CATEGORIES:
        if c.lower() == low:
            return c
    return None


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    module: Literal["expenses"]
    version: str
    tables: list[dict[str, Any]]
    classifier: dict[str, Any] = Field(
        ..., description="Layer availability: lexicon size, SVC fit, Groq config, cache rows."
    )
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Categorize (no save)
# --------------------------------------------------------------------------
class CategorizeIn(BaseModel):
    description: str = Field(default="", max_length=255)
    merchant: Optional[str] = Field(default=None, max_length=128)
    amount_inr: Optional[float] = Field(default=None, gt=0)


class CategorizeOut(BaseModel):
    category: Category
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: str = Field(
        ..., description="Which layer answered: citizen|cache:*|lexicon|fuzzy|model|llm|fallback."
    )
    alternates: list[tuple[str, float]] = Field(default_factory=list)
    merchant_key: str
    needs_review: bool
    quota_exhausted: bool = False


# --------------------------------------------------------------------------
# Expense CRUD
# --------------------------------------------------------------------------
class ExpenseCreateIn(BaseModel):
    description: str = Field(..., min_length=1, max_length=255)
    merchant: Optional[str] = Field(default=None, max_length=128)
    amount_inr: float = Field(..., gt=0, description="Rupees; stored as paise.")
    category: Optional[str] = Field(default=None, description="null/'Auto-detect' → classifier.")
    spent_at: Optional[date] = Field(default=None, description="Defaults to today.")
    tax_deductible: bool = False
    tax_section: Optional[TaxSection] = None
    notes: Optional[str] = Field(default=None, max_length=500)

    @field_validator("amount_inr")
    @classmethod
    def _sane_amount(cls, v: float) -> float:
        if v > 10_00_00_000:  # ₹10 crore in one personal expense is a typo
            raise ValueError("amount_inr implausibly large")
        return v


class ExpenseUpdateIn(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1, max_length=255)
    merchant: Optional[str] = Field(default=None, max_length=128)
    amount_inr: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = None
    spent_at: Optional[date] = None
    tax_deductible: Optional[bool] = None
    tax_section: Optional[TaxSection] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class ExpenseOut(BaseModel):
    id: str
    description: str
    merchant: Optional[str] = None
    amount_inr: float
    category: Category
    category_was_auto: bool
    category_confidence: Optional[float] = None
    spent_at: date
    tax_deductible: bool
    tax_section: Optional[TaxSection] = None
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    source: Source
    receipt_id: Optional[str] = None
    notes: Optional[str] = None
    needs_review: bool = False
    when: str = Field(..., description="Human label the UI renders: 'Today', 'Yesterday', '3 days'.")
    created_at: datetime
    updated_at: datetime


class ExpenseCreateOut(BaseModel):
    expense: ExpenseOut
    classification: CategorizeOut


class ExpenseListMeta(BaseModel):
    total: int
    limit: int
    offset: int


class ExpenseListOut(BaseModel):
    data: list[ExpenseOut]
    meta: ExpenseListMeta


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
class DashboardKpisOut(BaseModel):
    month_label: str = Field(..., examples=["JULY 2026"])
    total_month_inr: float
    avg_daily_inr: float
    txn_count: int
    anomaly_count: int
    spark_daily: list[float] = Field(
        default_factory=list, description="Last 7 days spend for the KPI sparkline."
    )


class CategorySliceOut(BaseModel):
    label: Category
    value_inr: float
    txn_count: int


class DailyPointOut(BaseModel):
    day: date
    total_inr: float


class DailyTrendOut(BaseModel):
    points: list[DailyPointOut]
    highest_day: Optional[DailyPointOut] = None
    highest_expense: Optional[ExpenseOut] = None
