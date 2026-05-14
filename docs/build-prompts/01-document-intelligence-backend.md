# Build Prompt — Document Intelligence Backend (preserved verbatim)

> Captured 2026-05-02. Source of truth for the Document Intelligence module backend build.
> Execute phase by phase. Improvise where it improves the build, but do not deviate from the contract surface (endpoints, schemas, status flow, access control).

---

## CONTEXT & EXISTING FILES

You have already created the full `.claude/` directory structure for this project including:
- `CLAUDE.md` (operating manual with workflow orchestration, task management, core principles)
- `.claude/settings.json` (team permissions, env vars including `CITADEL_MODE=frontend-mock`)
- `.claude/rules/` (8 modular guardrails: frontend-conventions, backend-conventions, api-conventions, ml-conventions, security-baseline, data-handling, testing, code-style)
- `.claude/commands/` (6 slash commands: scaffold-module, connect-frontend, contract-check, seed-mocks, module-status, pre-backend-checklist)
- `.claude/agents/` (6 specialist personas: backend-architect, ml-pipeline-engineer, api-contract-validator, security-auditor, frontend-mock-curator, code-reviewer)
- `.claude/skills/` (README pointing to master-backend-builder, ui-ux-pro-max base skills)
- `tasks/todo.md` + `tasks/lessons.md`
- `docs/architecture.md` + `docs/backend-blueprint.md` + `docs/api-contracts/README.md` + 8 module specs

**USE these existing files.** Read `docs/api-contracts/` for the document intelligence spec if it exists. Read `CLAUDE.md` for workflow rules. Adapt and improve any existing specs based on the requirements below. Do NOT create conflicting or duplicate files — extend what's already there.

The frontend for Document Intelligence is already built. You cannot see it. Build the backend to serve it. The frontend will connect via API endpoints. Default mode is `frontend-mock` — the backend should work with `?live=1` to opt into live mode.

---

## FIRST STEP — CREATE `docs/progress.md`

Before writing any code, create `docs/progress.md` with this structure:

```markdown
# CITADEL Build Progress Tracker

## Module: Document Intelligence
### Status: IN PROGRESS

### Files Created
| File | Purpose | Date | Status |
|------|---------|------|--------|

### Dependencies Installed
| Package | Version | Purpose | Date |
|---------|---------|---------|------|

### Database Tables Created
| Table | Columns Summary | Date |
|-------|----------------|------|

### API Endpoints Implemented
| Method | Path | Status |
|--------|------|--------|

### Environment Variables Required
| Key | Purpose | Set? |
|-----|---------|------|

### Cross-Module Notes
| Module | Shared Data/Dependency | Notes |
|--------|----------------------|-------|

### Known Issues / TODOs
- [ ] ...
```

**Update this file after EVERY significant action** — file creation, dependency install, table migration, endpoint completion. This is mandatory. When we build the next module, this file prevents cross-module conflicts.

---

## ENVIRONMENT VARIABLES

The following must be present in `.env` at project root. Create `.env.example` with placeholder values:

```
SUPABASE_URL=https://xsioedgaczvzizatxteg.supabase.co
SUPABASE_ANON_KEY=<provided>
SUPABASE_SERVICE_ROLE_KEY=<provided>
OCR_SPACE_API_KEY=K88280486288957
OPENROUTER_API_KEY=<provided>
```

These are the ONLY credentials needed for this module. Do NOT add any others.

---

## TECH STACK DECISIONS (NON-NEGOTIABLE)

- **Backend framework:** FastAPI
- **Database + Auth + Storage:** Supabase (PostgreSQL via Supabase client)
- **File storage:** Supabase Storage (bucket: `documents` for originals, bucket: `processed` for extracted/redacted outputs)
- **OCR:** OCR Space API (for scanned PDFs and images). API key provided in env.
- **Text extraction (digital PDFs):** PyMuPDF (`fitz`) — no API call needed
- **Text extraction (DOCX):** `python-docx` — no API call needed
- **Document type classification:** OpenRouter API (model TBD — original spec named `qwen/qwen3-plus:free` which does not exist; user to choose alternative)
- **PII detection:** Regex patterns (Indian PII) + spaCy NER (`en_core_web_sm`)
- **Signature detection:** OpenCV contour analysis
- **Vector indexing (for future RAG):** Supabase pgvector extension with `BAAI/bge-small-en-v1.5` embeddings via `sentence-transformers`
- **Background task processing:** FastAPI `BackgroundTasks` (no Celery/Redis — keep it simple)

---

## MODULE ARCHITECTURE — DOCUMENT INTELLIGENCE

This module has 5 sub-sections, each with its own set of API endpoints. Build them in this order:

### SUB-SECTION 1: UPLOAD & ANALYZE

#### 1.1 File Upload Endpoint

`POST /api/documents/upload`

- Accept multiple files in a single request (multipart/form-data)
- Supported formats: PDF, DOCX, JPEG, JPG, PNG
- Validate file type and size (max 10MB per file, max 10 files per batch)
- Store original files in Supabase Storage bucket `documents`
- For each file, create a row in `documents` table with status `PROCESSING`
- Return batch ID and list of document IDs

Request body fields:
- `files`: multiple file uploads
- `document_type`: one of `invoice`, `contract`, `id_document`, `government_permit`, `tender_notice`, `permit`, `report`, `receipt`, `affidavit`, `certificate`, `auto_detect` — default is `auto_detect`
- `language`: one of `en`, `hi`, `en+hi` — default is `en`. **Only these three options.** Do NOT include any other languages.
- `priority`: one of `low`, `normal`, `high`, `urgent` — default is `normal`
- `detect_redact_pii`: boolean, default `false`
- `signature_validation`: boolean, default `false`

#### 1.2 Text Extraction Pipeline (Background Task)

For each document:

**Step 1 — Extract text based on file type:**
- **DOCX:** Use `python-docx` to extract all paragraphs, tables, headers. No API call. Confidence = 99%.
- **PDF:** First try `PyMuPDF (fitz)`. If extracted text < 20 chars (scanned PDF), fall back to OCR Space API.
- **JPEG/PNG:** Send directly to OCR Space API.

**OCR Space API integration details:**
- Endpoint: `https://api.ocr.space/parse/image`
- Send file as multipart upload
- `language` param: `eng` for English, `hin` for Hindi, `eng+hin` for bilingual
- `isOverlayRequired=true` for word positions
- `scale=true` for better accuracy
- **IMPORTANT:** OCR Space free tier has 1MB limit per request. If PDF > 1MB, split page-by-page using PyMuPDF, send each page, merge results.
- Parse response: extract text + per-word confidence from `ParsedResults`
- Document-level confidence = weighted average of word confidences

**Step 2 — Auto-detect document type (if `auto_detect`):**
- Take first 500 words of extracted text
- Send to OpenRouter API with system prompt:
  > "You are a document classifier. Classify the following document text into exactly one of these categories: invoice, contract, id_document, government_permit, tender_notice, permit, report, receipt, affidavit, certificate. Return ONLY the category name, nothing else."
- Keyword fallback if OpenRouter fails:
  - "invoice"/"bill"/"total amount"/"GST" → invoice
  - "agreement"/"party"/"whereas"/"hereinafter" → contract
  - "aadhaar"/"PAN"/"voter"/"passport" → id_document
  - "tender"/"bid"/"procurement" → tender_notice
  - "permit"/"permission"/"authorized" → permit
  - "receipt"/"received"/"payment" → receipt
  - "affidavit"/"sworn"/"deponent" → affidavit
  - "certificate"/"certify"/"awarded" → certificate
  - default → report

**Step 3 — PII Detection (if `detect_redact_pii`):**

Layer 1 — Regex (Indian PII):
- Aadhaar: `\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b` — "Aadhaar Fragment"
- PAN: `\b[A-Z]{5}\d{4}[A-Z]\b` — "PAN Number"
- Phone: `\b(?:\+91[\s-]?)?[6-9]\d{9}\b` — "Phone Number"
- GST: `\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b` — "GST Number"
- Email: standard regex — "Email Address"
- Bank Account: `\b\d{9,18}\b` with context check (near "account", "A/C", "bank") — "Bank Account"

Layer 2 — spaCy NER (`en_core_web_sm`):
- Entities with labels PERSON, ORG, GPE
- Confidence from spaCy

For each PII: type, count, confidence (regex=100%, spaCy=model conf), positions (char offsets).

Redaction: replace with `[REDACTED]`. Store both original (encrypted/secure) and redacted version.

Low confidence flag: any match with confidence <70% → note: "Low confidence on {type} format — recommend manual verify"

**Step 4 — Signature Detection (if `signature_validation`):**
- PDF/image only (skip DOCX)
- Convert last page (or bottom 25% of single-page) to image via PyMuPDF
- Grayscale → binary threshold → OpenCV contours
- Filter: aspect ratio 2:1 to 8:1, area > 500px, not a straight line
- Result: `detected`, `not_found`, `unclear`

**Step 5 — Generate tags:**
- Auto-tag from: document type, department keywords, date references, key spaCy entities
- Store as array on document row
- Display in Library when archived

**Step 6 — Update document status:**
- Status → `PENDING_REVIEW`
- Set `confidence`, `pii_results` JSON, `signature_status`, `processed_at`

**Step 7 — Vector indexing for future RAG:**
- Chunk extracted text (~500 tokens, 50-token overlap)
- Embed with `sentence-transformers` `BAAI/bge-small-en-v1.5` (local)
- Store in `document_chunks` with pgvector column
- Metadata: document_id, chunk_index, document_type, tags, department
- Used later by RAG chat — do NOT build RAG chat now. Just ensure indexing pipeline exists and runs on every processed doc.

#### 1.3 Analysis Results Endpoint

`GET /api/documents/batch/{batch_id}/results`

Returns per-document results: doc_id, filename, document_type, confidence, status, pii_results, signature_status, tags, extracted_text_preview.

#### 1.4 Export Endpoints

- `GET /api/documents/batch/{batch_id}/export?format=csv`
- `GET /api/documents/batch/{batch_id}/export?format=json`

#### 1.5 Audit Log Endpoint

`GET /api/documents/{doc_id}/audit` — timestamped log of all actions on this document. Every state change must be logged.

#### 1.6 Document Actions

- `POST /api/documents/{doc_id}/approve` → status `APPROVED`, updates dashboard stats
- `POST /api/documents/{doc_id}/archive` → status `ARCHIVED`, visible in Library
- `POST /api/documents/{doc_id}/reject` → status `REJECTED`
- `POST /api/documents/{doc_id}/reassign` → status back to `PROCESSING`, re-runs analysis pipeline

**CRITICAL STATUS FLOW RULES:**
- `APPROVED` documents reflect in **Dashboard** and **Templates** only
- `ARCHIVED` documents reflect in **Library** only
- `REJECTED` documents are removed from Templates and Library
- `REASSIGN` re-runs the analyze pipeline

---

### SUB-SECTION 2: QUEUE

#### 2.1 Queue List Endpoint

`GET /api/documents/queue`

Query params: `search`, `status`, `type`, `priority`, `sort_by`, `sort_order`, `page`, `per_page`. Defaults: `created_at desc`, page 1, per_page 20.

Response per doc: doc_id, document_type, uploaded_by, priority, confidence, status, time_ago, created_at, filename.

#### 2.2 Bulk Actions

`POST /api/documents/bulk-action` with `{doc_ids: [...], action: approve|reject|archive|reassign}`. Same rules as individual actions. Log each.

#### 2.3 Priority Processing Order

URGENT → HIGH → NORMAL → LOW. FIFO within priority.

SLA thresholds:
- URGENT: 15 min
- HIGH: 1 hour
- NORMAL: 4 hours
- LOW: 24 hours

If exceeded without approve/archive → `sla_breached: true`.

---

### SUB-SECTION 3: LIBRARY

**Library shows ONLY archived documents.**

#### 3.1 Library List Endpoint

`GET /api/documents/library`

Query params: `search`, `type`, `tag`, `department`, `view` (grid|list).

Response per doc: doc_id, document_type, title, filename, file_size, file_size_bytes, tags, department, archived_at, storage_url, mime_type.

#### 3.2 Export Archive (ZIP Download)

`POST /api/documents/library/export` with `{doc_ids: [...]}`.

- Fetch from Supabase Storage
- Build ZIP in memory (Python `zipfile`)
- Stream as `Content-Disposition: attachment; filename="citadel_archive_{timestamp}.zip"`
- Include original + extracted text per doc
- If no `doc_ids`, export ALL archived (cap 100)

---

### SUB-SECTION 4: TEMPLATES

#### 4.1 Default System Templates (seed on first run)

| Type | Fields | System? |
|------|--------|---------|
| Invoice | vendor_name, invoice_number, date, due_date, line_items, subtotal, tax, total, payment_terms, bank_details, gst_number, currency | NO |
| Contract | party_a, party_b, effective_date, expiry_date, terms, clauses, signatures, witness, jurisdiction, contract_value, penalty_clause, renewal_terms, governing_law, dispute_resolution, confidentiality, termination, obligations_a, obligations_b | NO |
| Permit | permit_number, issued_to, issued_by, valid_from, valid_until, permit_type, conditions, authority_seal, jurisdiction | NO |
| ID Document | full_name, id_number, date_of_birth, address, photo_present, issue_date, expiry_date | YES (locked) |
| Receipt | receipt_number, date, received_from, amount, payment_method, purpose, received_by, signature | NO |
| Affidavit | deponent_name, date, court, case_number, sworn_before, notary, content_summary, witness_1, witness_2, stamp_value, jurisdiction | NO |
| Tender | tender_number, issuing_authority, title, submission_deadline, earnest_money, eligibility, scope, contact_person, published_date | NO |
| Certificate | certificate_type, issued_to, issued_by, date, registration_number, valid_until, purpose | NO |
| Government Permit | permit_id, department, applicant, approved_by, conditions, valid_from, valid_until, zone | NO |
| Report | title, author, department, date, summary, findings, recommendations, attachments_count | NO |

#### 4.2 Template CRUD Endpoints

- `GET /api/templates` — list with field count, avg accuracy
- `GET /api/templates/{template_id}` — single template + fields
- `POST /api/templates` — create custom
- `PUT /api/templates/{template_id}` — edit (see access rules)
- `POST /api/templates/{template_id}/clone` — clone

**Avg accuracy** = mean confidence of processed docs of that type. Updated after each processed doc.

#### 4.3 Access Control — Passport Key System

- On signup/login: generate unique 6-char alphanumeric (uppercase + digits). Store bcrypt-hashed in `users.passport_key_hash`. Show ONCE on first login.
- Templates with `is_system: true` (ID Document) require passport key to edit/clone.
- Additionally: any archived doc with `URGENT` priority gets passport protection for template edit/clone.

`POST /api/templates/{template_id}/verify-access` with `{passport_key: "A3X9K2"}` → `{access_granted: true|false}`.

#### 4.4 Template-Based Document Editing

- `GET /api/documents/{doc_id}/edit-view` — extracted fields mapped to template, editable
- `PUT /api/documents/{doc_id}/edit-save` with `{passport_key?, fields: {...}}`

For editing flow:
- **PDF:** PyMuPDF text → frontend rich-text editor → save regenerates PDF via `fpdf2`, replaces in storage
- **DOCX:** `python-docx` extract → structured JSON → save modifies via `python-docx`, re-upload
- **Images:** metadata only (filename, tags, department, title)

Re-run vector indexing after any edit.

---

### SUB-SECTION 5: DASHBOARD

All computed from real DB records. No hardcoded values.

#### 5.1 Stats — `GET /api/dashboard/stats?period=30d`
- `docs_processed`: count + change% + trend
- `avg_confidence`: value + change% + trend
- `pii_redactions`: count + change% + trend
- `avg_time_to_approve`: hours + change% + trend

#### 5.2 Volume — `GET /api/dashboard/volume?period=14d`
Daily counts + today_count.

#### 5.3 By Type — `GET /api/dashboard/by-type?period=30d`
total + breakdown (top 3 + "other").

#### 5.4 Top Uploaders — `GET /api/dashboard/top-uploaders?period=30d&limit=5`
Group by uploaded_by/department.

#### 5.5 SLA Distribution — `GET /api/dashboard/sla-distribution?period=30d`
under_1h / 1_to_4h / 4_to_24h / over_24h, count + percent each.

---

## DATABASE SCHEMA

(See full SQL in the original prompt — preserved here.)

### Tables: `documents`, `document_chunks`, `audit_log`, `templates`, `doc_id_counter` + `next_doc_id()` function

Indexes on: status, type, priority, batch_id, doc_id; document_chunks(document_id), document_chunks(embedding ivfflat).

---

## DEPENDENCIES

```
pip install fastapi uvicorn python-multipart supabase
pip install PyMuPDF python-docx fpdf2
pip install opencv-python-headless numpy Pillow
pip install spacy httpx
pip install sentence-transformers
python -m spacy download en_core_web_sm
```

Do NOT install easyocr, tesseract, celery, redis, or docker dependencies.

---

## FOLDER STRUCTURE

```
backend/
├── app/
│   ├── main.py                # FastAPI app, CORS, startup events
│   ├── config.py              # env vars, settings
│   ├── database.py            # Supabase client init
│   ├── modules/
│   │   └── document_intelligence/
│   │       ├── __init__.py
│   │       ├── router.py      # all endpoints
│   │       ├── schemas.py     # pydantic models
│   │       ├── service.py     # business logic
│   │       ├── ocr.py         # OCR Space integration
│   │       ├── extractor.py   # PyMuPDF + python-docx
│   │       ├── classifier.py  # OpenRouter doc-type classification
│   │       ├── pii.py         # regex + spaCy PII detection
│   │       ├── signature.py   # OpenCV signature detection
│   │       ├── indexer.py     # vector embedding + pgvector
│   │       └── templates.py   # template CRUD + access control
│   └── utils/
│       ├── storage.py         # Supabase storage helpers
│       ├── audit.py           # audit log helper
│       └── doc_id.py          # sequential DOC-ID generator
├── migrations/
│   └── 001_document_intelligence.sql
├── .env.example
└── requirements.txt
```

---

## BUILD SEQUENCE

**Phase 1: Foundation**
1. Folder structure
2. `config.py` env loading
3. `database.py` Supabase client
4. `main.py` FastAPI + CORS + router include
5. Run migration SQL in Supabase
6. Seed default templates
7. Update `docs/progress.md`

**Phase 2: Extraction Pipeline**
1. `extractor.py` — PyMuPDF + python-docx
2. `ocr.py` — OCR Space + page-split for >1MB
3. `classifier.py` — OpenRouter + keyword fallback
4. `pii.py` — regex + spaCy
5. `signature.py` — OpenCV
6. `indexer.py` — sentence-transformers + pgvector upsert
7. Test each individually
8. Update progress.md

**Phase 3: Core Endpoints**
1. Upload + background task orchestration
2. Analysis results
3. Export (CSV, JSON)
4. Audit log
5. Document actions
6. Update progress.md

**Phase 4: Queue & Library**
1. Queue list (filters, sort, pagination)
2. Bulk actions
3. Library list
4. Library ZIP export
5. Update progress.md

**Phase 5: Templates & Dashboard**
1. Template CRUD
2. Passport key verification
3. Document edit view/save
4. All dashboard stat endpoints
5. Update progress.md

**Phase 6: Integration & Testing**
1. Full flow: upload → process → queue → approve → archive → library
2. Verify dashboard stats from real data
3. Verify vector indexing
4. Manual endpoint tests
5. Final progress.md update

---

## CROSS-MODULE AWARENESS

- **RAG Chat (Citizen):** will pgvector-query `document_chunks`. Re-index on edit/re-process.
- **Other modules** may query document metadata. Keep API clean enough for internal calls.
- Re-indexing on edit handled in this module.

---

## CRITICAL RULES

1. No hardcoded mock data in backend.
2. Every state change → `audit_log`.
3. OCR Space 1MB limit → page split.
4. Language dropdown ONLY: English, Hindi, English+Hindi.
5. Library shows ONLY archived.
6. Approved → Dashboard + Templates only.
7. Rejected → removed from Templates and Library.
8. Reassign → back to PROCESSING + re-run pipeline.
9. Update `docs/progress.md` after every phase.
10. Don't conflict with existing `.claude/`, `CLAUDE.md`, `docs/` specs. Read first, extend.
11. Use `.claude/rules/backend-conventions` and `.claude/rules/api-conventions`.
