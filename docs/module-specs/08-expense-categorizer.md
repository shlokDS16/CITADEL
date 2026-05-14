# Module Spec — 08 · Expense Categorizer

> Frontend: `ExpenseCategorizer` in `pages.jsx`. Tabs: Add Expense · Dashboard · Budget · Receipts · Reports.
> Backend: `backend/app/modules/expenses/`. Prefix: `/api/v1/expenses`.
> Audience: citizens (`citizen` only). Personal finance — never aggregated to gov surface without consent.

## Outcome
A citizen logs personal expenses (manual entry, receipt scan, bank-statement upload, UPI/card import). The system auto-categorizes each transaction (Food & Dining, Transport, Utilities, Healthcare, Shopping, Education, Entertainment, Housing, Insurance, Other) using TF-IDF + LinearSVC trained on Indian merchant + UPI VPA patterns. IsolationForest flags anomalous spends (e.g., a ₹45,000 Croma purchase against a ₹26k/month baseline). Receipt scan uses the same OCR pipeline as Document Intelligence to extract merchant + items + tax + total. Dashboard shows monthly spend by category, daily trend, recent transactions with anomaly flags. Budget tab tracks per-category budget vs actual with NEAR/OVER alerts. Reports show FY26 totals + a tax-deductible package (Section 80C/80D, business expenses, HRA) ready for ITR filing.

## Personas & permissions
- `citizen`: full CRUD on own expenses, receipts, budgets; export reports
- No gov access. Citizens own all their data — explicit cross-module sharing required (and not enabled in v1).

## Endpoints

### Expenses (CRUD)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/expenses` | `expenses:write` | Add a single expense (manual entry) |
| `GET` | `/expenses` | `expenses:read` | List, filter `?category=&from=&to=&min_amt=&anomaly=true&q=` |
| `GET` | `/expenses/{exp_id}` | `expenses:read` | Detail (linked receipt, anomaly reason if flagged) |
| `PATCH` | `/expenses/{exp_id}` | `expenses:write` | Edit description / amount / category / tax_deductible flag |
| `DELETE` | `/expenses/{exp_id}` | `expenses:write` | Soft delete |
| `POST` | `/expenses/categorize` | `expenses:write` | Predict category for a description (no save) — used by Add form live |

### Receipts (OCR)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/receipts/upload` | `expenses:upload` | Multipart receipt image → 202 + job_id; OCR + parse |
| `GET` | `/receipts/jobs/{job_id}` | `expenses:read` | OCR job status + extracted fields |
| `GET` | `/receipts` | `expenses:read` | List receipts, filter `?cat=&tax_deductible=&from=&to=` |
| `GET` | `/receipts/{rcpt_id}` | `expenses:read` | Detail (full extracted fields) |
| `POST` | `/receipts/{rcpt_id}/confirm` | `expenses:write` | Confirm OCR extraction → creates linked expense |
| `POST` | `/receipts/{rcpt_id}/edit` | `expenses:write` | Manual correction of OCR fields |
| `GET` | `/receipts/{rcpt_id}/image` | `expenses:read` | Pre-signed receipt image download (5min TTL) |

### Imports (bank / UPI / card)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/imports/csv` | `expenses:upload` | Bank/card CSV upload (configurable column map) → batch_id |
| `POST` | `/imports/pdf` | `expenses:upload` | Bank PDF statement → OCR + parse → batch_id |
| `GET` | `/imports/{batch_id}` | `expenses:read` | Import status + per-row classification + duplicate flags |
| `POST` | `/imports/{batch_id}/confirm` | `expenses:write` | Commit selected rows to expenses |
| `POST` | `/imports/upi/link` | `expenses:write` | (v2) Link UPI app via account aggregator API |
| `POST` | `/imports/card/link` | `expenses:write` | (v2) Link credit card via card-issuer API |

### Dashboard
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/dashboard/kpis` | `expenses:read` | Total this month, avg daily, txn count, anomaly count |
| `GET` | `/dashboard/by-category` | `expenses:read` | Donut data for current month |
| `GET` | `/dashboard/daily-trend` | `expenses:read` | Last 30 days spend per day |
| `GET` | `/dashboard/recent` | `expenses:read` | Last N transactions with anomaly flags |
| `GET` | `/dashboard/anomalies` | `expenses:read` | Flagged expenses with reason text |

### Budgets
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/budgets` | `expenses:read` | All budgets with spent/budget/percentage |
| `POST` | `/budgets` | `expenses:write` | Create per-category monthly budget |
| `PATCH` | `/budgets/{budget_id}` | `expenses:write` | Update amount, period, alert threshold |
| `DELETE` | `/budgets/{budget_id}` | `expenses:write` | Remove |

### Reports
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/reports/fy-summary` | `expenses:read` | FY26 spend, tax deductible, savings, net worth Δ |
| `GET` | `/reports/monthly-trend` | `expenses:read` | 12-month trend |
| `GET` | `/reports/tax-summary` | `expenses:read` | Section 80C/80D/business/HRA breakdown |
| `POST` | `/reports/export` | `expenses:read` | Generate export `format=csv,xlsx,pdf,tax_package` → 202 + job |
| `GET` | `/reports/exports/{export_id}` | `expenses:read` | Pre-signed download URL |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + classifier model load status |

## Schemas (key shapes)

### Expense
```python
class ExpenseOut(BaseModel):
    id: UUID
    citizen_id: UUID
    description: str
    merchant: str | None
    amount_inr: int                            # paise stored, ₹ displayed
    category: Literal["Food_Dining","Transport","Utilities","Healthcare","Shopping",
                      "Education","Entertainment","Housing","Insurance","Other"]
    category_was_auto: bool
    category_confidence: float                 # 0..1
    spent_at: date
    tax_deductible: bool
    tax_section: Literal["80C","80D","HRA","BUSINESS","NONE"] | None
    is_anomaly: bool
    anomaly_reason: str | None                 # "₹45k Shopping vs ₹6.8k 30-day avg"
    source: Literal["manual","receipt_ocr","bank_csv","bank_pdf","upi","card"]
    receipt_id: UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
```

### Add expense
```python
class ExpenseCreateIn(BaseModel):
    description: str = Field(..., max_length=255)
    merchant: str | None = Field(None, max_length=128)
    amount_inr: int = Field(..., gt=0)         # paise
    category: str | None = None                # null → AI auto-detect
    spent_at: date
    tax_deductible: bool = False
    notes: str | None = Field(None, max_length=500)
```

### Categorize (predict)
```python
class CategorizeIn(BaseModel):
    description: str
    merchant: str | None = None
    amount_inr: int | None = None

class CategorizeOut(BaseModel):
    category: str
    confidence: float                          # 0..1
    alternates: list[tuple[str, float]]        # top-3 candidates
```

### Receipt (OCR)
```python
class ReceiptOut(BaseModel):
    id: UUID
    citizen_id: UUID
    storage_path: str                          # internal — never returned
    image_url: str | None                      # pre-signed
    status: Literal["queued","processing","review","confirmed","rejected"]
    merchant: str | None
    items: list[ReceiptItem]
    subtotal_inr: int | None
    tax_inr: int | None                        # GST
    total_inr: int | None
    purchase_date: date | None
    predicted_category: str | None
    confidence: float | None
    created_at: datetime
    expense_id: UUID | None                    # linked once confirmed

class ReceiptItem(BaseModel):
    name: str
    qty: int
    unit_price_inr: int
    line_total_inr: int
```

### Budget
```python
class BudgetOut(BaseModel):
    id: UUID
    citizen_id: UUID
    category: str
    amount_inr: int
    period: Literal["monthly","weekly","yearly"]
    spent_inr: int                             # current period
    pct_used: float
    status: Literal["under","near","over"]     # near=>80%, over>100%
    alert_threshold_pct: int                   # default 80
    created_at: datetime
```

### Tax summary
```python
class TaxSummaryOut(BaseModel):
    fy: str                                    # "FY26"
    section_80c: int                           # investments
    section_80d: int                           # health insurance
    business: int
    hra: int
    total_deductible: int
    breakdown_by_month: dict[str, int]
```

## Data model
```sql
expenses (
  id UUID PK,
  citizen_id UUID NOT NULL,
  description VARCHAR(255),
  merchant VARCHAR(128) NULL,
  amount_paise BIGINT NOT NULL,               -- store paise (int), display ₹
  category VARCHAR(24),
  category_was_auto BOOLEAN DEFAULT TRUE,
  category_confidence FLOAT,
  spent_at DATE NOT NULL,
  tax_deductible BOOLEAN DEFAULT FALSE,
  tax_section VARCHAR(16) NULL,
  is_anomaly BOOLEAN DEFAULT FALSE,
  anomaly_reason TEXT NULL,
  source VARCHAR(16) DEFAULT 'manual',
  receipt_id UUID NULL FK -> receipts.id,
  import_batch_id UUID NULL,
  notes TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_expenses_citizen ON expenses(citizen_id, spent_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_expenses_category ON expenses(citizen_id, category, spent_at DESC);
CREATE INDEX ix_expenses_anomaly ON expenses(citizen_id) WHERE is_anomaly = TRUE;

receipts (
  id UUID PK,
  citizen_id UUID NOT NULL,
  storage_path TEXT NOT NULL,
  status VARCHAR(16) DEFAULT 'queued',
  merchant VARCHAR(128) NULL,
  subtotal_paise BIGINT NULL,
  tax_paise BIGINT NULL,
  total_paise BIGINT NULL,
  purchase_date DATE NULL,
  predicted_category VARCHAR(24) NULL,
  confidence FLOAT NULL,
  ocr_raw_text TEXT NULL,                     -- for debugging; pruned after 30 days
  expense_id UUID NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  confirmed_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_receipts_citizen ON receipts(citizen_id, created_at DESC);
CREATE INDEX ix_receipts_status ON receipts(status);

receipt_items (
  id UUID PK,
  receipt_id UUID FK -> receipts.id ON DELETE CASCADE,
  name VARCHAR(255),
  qty INT,
  unit_price_paise BIGINT,
  line_total_paise BIGINT
);

budgets (
  id UUID PK,
  citizen_id UUID NOT NULL,
  category VARCHAR(24),
  amount_paise BIGINT NOT NULL,
  period VARCHAR(8) DEFAULT 'monthly',
  alert_threshold_pct INT DEFAULT 80,
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX ux_budgets_citizen_cat ON budgets(citizen_id, category, period) WHERE active;

import_batches (
  id UUID PK,
  citizen_id UUID NOT NULL,
  source VARCHAR(16),                         -- 'bank_csv','bank_pdf','upi','card'
  source_label VARCHAR(64),                   -- 'HDFC May Statement', 'GPay April'
  total_rows INT,
  parsed_rows INT,
  duplicate_rows INT,
  committed_rows INT,
  status VARCHAR(16) DEFAULT 'pending',
  uploaded_at TIMESTAMPTZ DEFAULT NOW(),
  committed_at TIMESTAMPTZ NULL
);

import_rows (
  id UUID PK,
  batch_id UUID FK -> import_batches.id ON DELETE CASCADE,
  raw JSONB,                                   -- original row
  parsed_description VARCHAR(255),
  parsed_merchant VARCHAR(128),
  parsed_amount_paise BIGINT,
  parsed_date DATE,
  predicted_category VARCHAR(24),
  predicted_confidence FLOAT,
  is_duplicate_of UUID NULL,                  -- existing expense id
  selected_for_commit BOOLEAN DEFAULT FALSE,
  expense_id UUID NULL                        -- once committed
);
CREATE INDEX ix_import_rows_batch ON import_rows(batch_id);

exports (
  id UUID PK,
  citizen_id UUID NOT NULL,
  format VARCHAR(16),                         -- csv/xlsx/pdf/tax_package
  status VARCHAR(16) DEFAULT 'queued',
  storage_path TEXT NULL,
  expires_at TIMESTAMPTZ,                     -- 7d TTL
  created_at TIMESTAMPTZ DEFAULT NOW(),
  ready_at TIMESTAMPTZ NULL
);
```

**Retention**: expenses indefinite while account active; receipts indefinite (citizen-owned tax record); receipt OCR raw text 30 days; import_rows 90 days post-commit; exports 7 days. On account delete, all rows hard-deleted (citizen erasure right per `data-handling.md`).

## ML Pipeline
- **Categorization (primary)**: `TF-IDF` (1-2 grams over description+merchant, lowercase, remove digits/punct) → `LinearSVC` (multi-class, 10 categories). Trained on ~50k labeled Indian merchant entries (Swiggy/Zomato/Uber/Ola/BESCOM/Croma/Apollo/etc.) + custom labels from import flow user corrections.
- **Categorization (UPI VPA path)**: rule-based dictionary mapping common VPAs (`*@swiggy → Food_Dining`, `*@uber → Transport`, `*@hdfcbank → Utilities/Card`).
- **Anomaly detection**: per-citizen `IsolationForest` per category (contamination=0.05). Refit weekly with last 90 days. Flags transactions with `decision_function < threshold` AND amount > 2× category 30d avg.
- **Receipt OCR**: shared pipeline with Document Intelligence (PaddleOCR + LayoutLMv3 for line-item extraction). Output: merchant, items, subtotal, tax, total, date.
- **Tax classification**: keyword + merchant-pattern rules → maps to Section 80C / 80D / business / HRA / NONE.
- **Bank statement parsing**: per-bank PDF templates (HDFC, ICICI, SBI, Axis) using Camelot/Tabula; CSV path uses configurable column mapping.
- **Duplicate detection on import**: hash `(merchant, amount_paise, spent_at)` → match against last 90 days of expenses.

**Latency budget**: <50ms per categorization per `ml-conventions.md`.
**Confidence threshold for auto-apply**: ≥0.75 (per `ml-conventions.md` defaults). Below → category set as predicted but flagged for review.

## Background jobs
- `categorize_expense(exp_id)` — usually inline; async fallback if model loading.
- `process_receipt_ocr(receipt_id)` — async, OCR + line item extraction.
- `process_import(batch_id)` — async, parse + classify all rows.
- `compute_anomalies(citizen_id)` — nightly per active citizen.
- `recompute_budgets(citizen_id)` — on every expense write (lightweight).
- `send_budget_alert(budget_id)` — when crosses 80% / 100% threshold (push + optional email).
- `generate_export(export_id)` — async, builds CSV/XLSX/PDF/tax-package zip.
- `purge_ocr_raw_text()` — daily, 30-day retention.
- `purge_old_exports()` — daily, 7-day TTL.

## Real-time
None for v1. Budget alerts go via push notification, not WebSocket.

## Frontend mock cross-reference
- Search `pages.jsx` for `ExpenseCategorizer` component (line 2235).
- Sub-components: `ExpenseAdd`, `ExpenseDashboard`, `ExpenseBudget`, `ExpenseReceipts`, `ExpenseReports`.
- Inline mocks to extract: `MOCK_PREDICT_RULES` (the keyword-based `predict()` in `ExpenseAdd`), `MOCK_OCR_PREVIEW` (the Croma receipt mock in `ExpenseAdd`), `MOCK_SPEND_BY_CAT` and `MOCK_RECENT_EXPENSES` (in `ExpenseDashboard`), `MOCK_BUDGETS` (in `ExpenseBudget`), `MOCK_RECEIPTS` (in `ExpenseReceipts`), `MOCK_TAX_ROWS` and `MOCK_FY_KPIS` (in `ExpenseReports`).

## Non-functional
- p50 categorize: <50ms
- p50 add expense end-to-end: <200ms
- p95 receipt OCR: <8s
- p95 CSV import (1000 rows): <30s
- Throughput: 200 categorizations/sec per node
- Availability: 99.0% (citizen surface)
- Storage per citizen: ~10 MB per active year (receipts dominate)
- Citizen quota: unlimited expenses, but receipt OCR rate-limited at 100/day per `api-conventions.md` ML limits

## Open questions for user
- [ ] Bank/UPI integration — v1 is CSV upload only. For v2, do we go through RBI Account Aggregator framework, or per-bank API?
- [ ] Tax sections — current sketch covers 80C, 80D, HRA, business. Are 80E (education loan), 80G (donations), 80EEA (home loan) also needed for FY26?
- [ ] Receipt OCR — share infrastructure with Document Intelligence module, or separate models trained specifically for retail receipts (different layout than gov forms)?
- [ ] Anomaly threshold — current 2× category avg. Should this be configurable per citizen (some have lumpy income), or globally tuned?
