# Module Spec — 01 · Document Intelligence

> **STATUS:** ✅ Implemented and integration-tested 2026-05-02. See `docs/progress.md` for build state.
> **Frontend:** `DocumentIntelligence` in `pages.jsx`. Tabs: Upload · Queue · Library · Templates · Analytics.
> **Backend:** `backend/app/modules/document_intelligence/`. URL prefix: `/api/documents`, `/api/templates`, `/api/dashboard`, `/api/v1/doc-intel/health`.
> **Audience:** gov officers (passport key as second-factor for system templates + urgent archived doc edits).
> **Stack actually built (replaces some earlier ML choices in this spec):**
> - **OCR**: OCR.space API (1MB request limit handled by per-page splitting via PyMuPDF)
> - **Digital text**: PyMuPDF (`fitz`) for PDF, `python-docx` for DOCX
> - **Classification**: **Groq** `llama-3.3-70b-versatile` (15ms tested) — replaces the originally-spec'd OpenRouter `qwen/qwen3-plus:free` (which doesn't exist)
> - **PII**: regex (Aadhaar/PAN/phone/GST/email/bank w/ context check) + spaCy `en_core_web_sm` (PERSON/ORG/GPE)
> - **Signature**: OpenCV contour analysis (aspect ratio + area + height filters)
> - **Embeddings**: `BAAI/bge-small-en-v1.5` via fastembed when available; deterministic blake2b hash-stub fallback when fastembed isn't installable (e.g. Py3.14). Same 384-dim schema. Swap by `pip install fastembed && reindex_document(...)`.
> - **DB / Storage / Auth**: Supabase (Postgres 14 + pgvector + Storage)
> - **Background work**: FastAPI `BackgroundTasks` (no Celery/Redis)

## Outcome
Officers upload civic documents (forms, contracts, IDs, permits), the system OCRs + classifies + extracts entities + flags PII + routes to an approval queue. Library lets officers search and re-use. Templates let admins teach the system new layouts.

## Personas & permissions
- `gov_officer`: upload, review queue, search library
- `gov_analyst`: read-only on library + analytics
- `gov_admin`: manage templates + manage retention

## Endpoints

### Upload & processing
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/upload` | `doc-intel:upload` | Multipart upload + processing config; returns job id |
| `POST` | `/batch` | `doc-intel:upload` | Batch upload (≤50 files); returns batch id |
| `GET` | `/jobs/{job_id}` | `doc-intel:read` | Job status + result |
| `GET` | `/batches/{batch_id}` | `doc-intel:read` | Batch status, per-file states |

### Queue
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/queue` | `doc-intel:read` | Pending review items, filterable + paginated |
| `POST` | `/queue/{doc_id}/approve` | `doc-intel:approve` | Approve extraction |
| `POST` | `/queue/{doc_id}/reject` | `doc-intel:approve` | Reject with reason |
| `POST` | `/queue/{doc_id}/edit` | `doc-intel:approve` | Manual edit of extracted fields |
| `POST` | `/queue/bulk-approve` | `doc-intel:approve` | Approve a list of doc ids |

### Library
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/library` | `doc-intel:read` | Search + filter approved docs |
| `GET` | `/library/{doc_id}` | `doc-intel:read` | Full doc detail + extracted entities |
| `GET` | `/library/{doc_id}/download` | `doc-intel:read` | Pre-signed download (5min TTL) |
| `DELETE` | `/library/{doc_id}` | `doc-intel:delete` | Soft delete (archives) |

### Templates
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/templates` | `doc-intel:read` | List built-in + custom templates |
| `POST` | `/templates` | `doc-intel:admin` | Create custom template |
| `PUT` | `/templates/{tpl_id}` | `doc-intel:admin` | Update |
| `DELETE` | `/templates/{tpl_id}` | `doc-intel:admin` | Remove |

### Analytics
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/analytics/volume` | `doc-intel:read` | Daily processing volume + trend |
| `GET` | `/analytics/sla` | `doc-intel:read` | SLA performance by document type |
| `GET` | `/analytics/quality` | `doc-intel:read` | Confidence histogram + manual edit rate |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + model load status |

## Schemas (key shapes)

### Document object
```python
class DocumentOut(BaseModel):
    id: UUID
    filename_original: str            # user-provided filename
    document_type: Literal["invoice","contract","id","form","permit","other"]
    status: Literal["queued","processing","review","approved","rejected","archived"]
    confidence: float                 # 0..1
    page_count: int
    language_detected: str            # ISO 639-1 ("en", "hi", "ta", ...)
    extracted_at: datetime
    approved_at: datetime | None
    approved_by: UUID | None
    template_id: UUID | None
    pii_detected: list[PIIEntity]
    entities: list[ExtractedEntity]
    tags: list[str]
    storage_path: str                 # internal — never exposed to frontend
    download_url: str | None          # pre-signed, 5 min TTL
```

### PII Entity
```python
class PIIEntity(BaseModel):
    type: Literal["aadhaar","pan","phone","email","address","dob","name"]
    value: str                        # redacted by default; raw only if requester has scope
    page: int
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2 normalized 0..1
    confidence: float
```

### Extracted Entity (NER)
```python
class ExtractedEntity(BaseModel):
    type: str                         # template-defined: "invoice_number", "vendor_name", etc.
    value: str
    page: int
    confidence: float
    bbox: tuple[float, float, float, float] | None
    edited: bool                      # true if officer manually corrected
```

### Job status
```python
class JobStatus(BaseModel):
    job_id: UUID
    status: Literal["queued","running","succeeded","failed"]
    progress: float                   # 0..1
    result: DocumentOut | None
    error: ErrorDetail | None
    started_at: datetime
    finished_at: datetime | None
```

## Data model
```sql
documents (
  id UUID PK,
  owner_role VARCHAR(16) NOT NULL,    -- always 'gov'
  owner_id UUID NOT NULL,             -- uploading officer
  filename_original VARCHAR(255),
  storage_path TEXT NOT NULL,
  mime_type VARCHAR(64),
  size_bytes BIGINT,
  document_type VARCHAR(32),
  status VARCHAR(16) DEFAULT 'queued',
  confidence FLOAT,
  page_count INT,
  language_detected VARCHAR(8),
  template_id UUID FK -> templates.id NULL,
  approved_at TIMESTAMPTZ NULL,
  approved_by UUID NULL,
  rejected_at TIMESTAMPTZ NULL,
  rejection_reason TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_documents_status ON documents(status);
CREATE INDEX ix_documents_owner_id ON documents(owner_id);
CREATE INDEX ix_documents_created_at ON documents(created_at DESC);

document_entities (
  id UUID PK,
  document_id UUID FK -> documents.id ON DELETE CASCADE,
  entity_type VARCHAR(64),
  entity_value TEXT ENCRYPTED,        -- pii-class fields encrypted
  page INT,
  bbox JSONB,
  confidence FLOAT,
  edited BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_doc_entities_doc ON document_entities(document_id);
CREATE INDEX ix_doc_entities_type ON document_entities(entity_type);

document_pii (
  id UUID PK,
  document_id UUID FK -> documents.id ON DELETE CASCADE,
  pii_type VARCHAR(16),
  value_encrypted TEXT,               -- fernet
  page INT,
  bbox JSONB,
  confidence FLOAT
);

templates (
  id UUID PK,
  name VARCHAR(128),
  document_type VARCHAR(32),
  fields JSONB,                       -- list of {name, type, required, regex}
  is_builtin BOOLEAN DEFAULT FALSE,
  created_by UUID NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Retention**: documents 7 years (gov audit), document_pii 1 year, audit_log indefinite.

## ML Pipeline
- **OCR**: PaddleOCR (Apache 2.0, multilingual including Hindi/Tamil/Telugu/Bengali).
- **Layout**: LayoutLMv3 (CC BY-NC for the v3-base — confirm acceptable licensing or use LayoutXLM).
- **NER (general)**: spaCy `en_core_web_trf` + `xx_sent_ud_sm` for multilingual.
- **NER (PII Indian)**: custom spaCy pipeline trained on Aadhaar/PAN/phone/address patterns + regex fallback.
- **Document classification**: zero-shot via `bart-large-mnli` (or fine-tuned DistilBERT once we have data).

**Latency budget**: <2s per page (single doc), batch path target 1s/page amortized.
**Confidence threshold for auto-approve**: ≥0.92 (else routes to review queue).

## Background jobs
- `process_document(doc_id)` — full OCR+NER+PII+classification pipeline. Triggered on upload.
- `process_batch(batch_id)` — fan out to per-doc jobs, aggregate status.
- `purge_expired()` — daily, removes docs past retention.

## Real-time
None for v1. Polling job status is fine. WebSocket in v2 if needed.

## Frontend mock cross-reference
- Search `pages.jsx` for `DocumentIntelligence` component.
- Mock arrays: `MOCK_QUEUE`, `MOCK_LIBRARY`, `MOCK_TEMPLATES` (rename to match this convention if not already).
- Sub-components: `DocIntelUpload`, `DocIntelQueue`, `DocIntelLibrary`, `DocIntelTemplates`, `DocIntelAnalytics`.

## Non-functional
- p50 upload-to-queue: <2s for single page, <8s for 10-page doc
- p95 search latency: <300ms
- Throughput: 100 concurrent uploads
- Availability: 99.5% (gov SLA)

## Open questions for user
- [ ] Is on-prem deploy required, or is cloud OK? (affects model choice — some HF models can't be self-hosted commercially)
- [ ] Multi-language priority list — confirm Hindi + Tamil + Telugu + English sufficient for v1?
- [ ] Retention 7 years — is this the gov mandate or a guess?
