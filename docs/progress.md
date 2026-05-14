# CITADEL Build Progress Tracker

> Updated continuously by Claude during backend builds. Single source of truth for what's wired across modules.

---

## Module: Document Intelligence
### Status: ✅ COMPLETE — all 6 phases shipped, integration tested end-to-end

### Files Created
| File | Purpose | Date | Status |
|------|---------|------|--------|
| `backend/.env.example` | Placeholder env vars (committed) | 2026-05-02 | OK |
| `backend/.env` | Real credentials (gitignored) | 2026-05-02 | OK |
| `backend/requirements.txt` | All Python deps (FastAPI, supabase, PyMuPDF, spaCy, sentence-transformers, etc.) | 2026-05-02 | OK |
| `backend/app/__init__.py` | Package marker, version | 2026-05-02 | OK |
| `backend/app/config.py` | Pydantic Settings — env-driven config singleton | 2026-05-02 | OK |
| `backend/app/database.py` | Supabase client singletons (service-role + anon) | 2026-05-02 | OK |
| `backend/app/main.py` | FastAPI app + CORS + lifespan + /api/v1/health | 2026-05-02 | OK |
| `backend/app/modules/__init__.py` | Module package marker | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/__init__.py` | Re-exports `router` | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/router.py` | All HTTP endpoints (stubbed in Phase 1, filled in Phase 3) | 2026-05-02 | STUB |
| `backend/app/utils/__init__.py` | Utils package marker | 2026-05-02 | OK |
| `backend/migrations/001_document_intelligence.sql` | Tables, indexes, `next_doc_id()`, 10 seed templates | 2026-05-02 | OK |
| `backend/scripts/verify_creds.py` | Smoke-test all 4 external services | 2026-05-02 | OK |
| `backend/scripts/init_db.py` | Verify tables + create storage buckets + check seed | 2026-05-02 | OK |
| `backend/app/utils/doc_id.py` | Sequential DOC-XXXX via Postgres RPC | 2026-05-02 | OK |
| `backend/app/utils/audit.py` | Audit log helper + action vocabulary | 2026-05-02 | OK |
| `backend/app/utils/storage.py` | Supabase Storage upload/download/signed-url | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/extractor.py` | PyMuPDF + python-docx text extraction + page split | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/ocr.py` | OCR.space integration with 1MB page-split fallback | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/classifier.py` | Groq Llama-3.3-70B classification + keyword fallback | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/pii.py` | Regex (Aadhaar/PAN/phone/GST/email/bank) + spaCy NER | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/signature.py` | OpenCV contour-based signature detection | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/indexer.py` | Embeddings + pgvector upsert (fastembed when available, hash-stub fallback for Py3.14) | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/schemas.py` | Pydantic v2 request/response models — frontend contract | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/service.py` | Business logic (upload, processing, queue, library, actions) | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/templates.py` | Template CRUD + bcrypt passport key system | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/dashboard.py` | Stats, volume, by-type, top-uploaders, SLA distribution | 2026-05-02 | OK |
| `backend/app/modules/document_intelligence/router.py` | All 25 module endpoints — thin parse/dispatch/format | 2026-05-02 | OK |
| `docs/build-prompts/01-document-intelligence-backend.md` | Preserved verbatim build prompt | 2026-05-02 | OK |
| `docs/progress.md` | This file | 2026-05-02 | OK |

### Dependencies Installed (Python 3.14.3)
| Package | Version | Purpose | Date |
|---------|---------|---------|------|
| fastapi | 0.115+ | Web framework | 2026-05-02 |
| uvicorn[standard] | 0.32+ | ASGI server | 2026-05-02 |
| pydantic, pydantic-settings | 2.9+, 2.6+ | Schemas + env config | 2026-05-02 |
| supabase | 2.9+ | DB + auth + storage client | 2026-05-02 |
| httpx | 0.27+ | OCR.space + Groq calls | 2026-05-02 |
| PyMuPDF, python-docx, fpdf2 | 1.24, 1.1, 2.7 | File extraction + PDF rebuild | 2026-05-02 |
| opencv-python-headless, Pillow, numpy | 4.10, 10.4, 1.26 | Signature contour detection | 2026-05-02 |
| spacy + en_core_web_sm | 3.7+ | NER for PII (PERSON, ORG, GPE) | 2026-05-02 |
| bcrypt | 4.2+ | Passport key hashing | 2026-05-02 |
| **fastembed** | (not installable on Py3.14) | Was target for vector embeddings | 2026-05-02 |
| _hash-stub embedder_ | inline | Active fallback — produces real 384-dim vectors via blake2b token hashing. Schema-correct; semantic quality limited. RAG module will swap when py-rust-stemmers wheels exist for Py3.14. | 2026-05-02 |

### Database Tables Created (in Supabase)
| Table | Columns Summary | Date |
|-------|----------------|------|
| `documents` | doc_id, batch_id, status, priority, confidence, extracted_text, pii_results, tags, storage_path, lifecycle timestamps | 2026-05-02 |
| `document_chunks` | document_id, chunk_index, chunk_text, embedding(vector(384)), tags | 2026-05-02 |
| `audit_log` | document_id, action, details, performed_by, created_at | 2026-05-02 |
| `templates` | name, document_type, fields(jsonb), is_system, avg_accuracy | 2026-05-02 |
| `users` | id, email, passport_key_hash, passport_key_shown | 2026-05-02 |
| `doc_id_counter` | + `next_doc_id()` plpgsql function | 2026-05-02 |
| `v_queue` | View with computed_sla_breached + seconds_in_queue | 2026-05-02 |
| 10 seed templates | invoice, contract, permit, id_document(SYSTEM), receipt, affidavit, tender_notice, certificate, government_permit, report | 2026-05-02 |
| Storage buckets | `documents` (10MB private) + `processed` (10MB private) | 2026-05-02 |

### API Endpoints Implemented (25 module endpoints + 4 FastAPI built-ins)
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/v1/health` | OK |
| GET | `/api/v1/doc-intel/health` | OK |
| **Upload & Analyze** | | |
| POST | `/api/documents/upload` | OK — 4s end-to-end on synthetic PDF |
| GET | `/api/documents/batch/{batch_id}/results` | OK |
| GET | `/api/documents/batch/{batch_id}/export?format=csv\|json` | OK |
| GET | `/api/documents/{doc_id}/audit` | OK |
| POST | `/api/documents/{doc_id}/approve\|reject\|archive\|reassign` | OK (4 endpoints) |
| **Queue** | | |
| GET | `/api/documents/queue?search=&status=&type=&priority=&sort_by=&page=&per_page=` | OK |
| POST | `/api/documents/bulk-action` | OK |
| **Library** | | |
| GET | `/api/documents/library?search=&type=&tag=&department=&view=` | OK |
| POST | `/api/documents/library/export` (ZIP stream) | OK — 1.6KB zip generated |
| **Templates** | | |
| GET | `/api/templates` | OK — returns 10 |
| GET\|POST\|PUT\|POST | `/api/templates/{id}` + `.../clone` + `.../verify-access` | OK (5 endpoints) |
| **Edit** | | |
| GET | `/api/documents/{doc_id}/edit-view` | OK |
| PUT | `/api/documents/{doc_id}/edit-save` | OK (re-indexes vectors) |
| **Dashboard** | | |
| GET | `/api/dashboard/stats?period=` | OK |
| GET | `/api/dashboard/volume?period=` | OK |
| GET | `/api/dashboard/by-type?period=` | OK |
| GET | `/api/dashboard/top-uploaders?period=&limit=` | OK |
| GET | `/api/dashboard/sla-distribution?period=` | OK |

### Integration Test Results (2026-05-02)
| Test | Outcome |
|------|---------|
| Generate synthetic invoice PDF + POST /upload | ✅ HTTP 200, doc_id DOC-2842 issued |
| Background processing | ✅ Completed in 4s (extract → classify → PII → signature → index) |
| Auto-classification (Groq) | ✅ Identified `invoice` (94% conf) and `tender_notice` (94% conf) on test docs |
| PII regex (Aadhaar/PAN/phone/GST/email/bank) | ✅ All 6 patterns matched |
| PII spaCy NER (PERSON/ORG/GPE) | ✅ All 3 entity types detected on test docs |
| Audit log | ✅ 5 entries written: uploaded → classified → pii_detected → processed → indexed |
| Queue endpoint | ✅ Pending docs returned with time_ago, sla_breached, pii_count |
| Approve → Archive transition | ✅ Status moved correctly, timestamps set |
| Library | ✅ Archived doc visible only in library, with signed URL (5-min TTL) |
| Library ZIP export | ✅ 1.6KB ZIP delivered as attachment |
| Dashboard endpoints (5) | ✅ All return computed values from real DB rows |
| pgvector chunks | ✅ 1 chunk indexed per doc with metadata, 384-dim vector |
| Templates verify-access | ✅ Rejects invalid passport key (403-equivalent) |

### Dependencies Installed
| Package | Version | Purpose | Date |
|---------|---------|---------|------|
| _Pending — run `pip install -r backend/requirements.txt`_ | — | — | — |

### Database Tables Created (in Supabase)
| Table | Columns Summary | Date |
|-------|----------------|------|
| _Pending — run `migrations/001_document_intelligence.sql` in Supabase SQL Editor_ | — | — |

### API Endpoints Implemented
| Method | Path | Status |
|--------|------|--------|
| GET | `/api/v1/health` | OK |
| _Stubbed only — Phase 3 fills in_ | — | — |

### Environment Variables Required
| Key | Purpose | Set? |
|-----|---------|------|
| `SUPABASE_URL` | Supabase project URL | YES |
| `SUPABASE_ANON_KEY` | Anon JWT (RLS-respecting client) | YES |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role JWT (server use) | YES |
| `OCR_SPACE_API_KEY` | OCR Space free-tier key | YES |
| `GROQ_API_KEY` | Groq inference API key | YES |
| `GROQ_CLASSIFIER_MODEL` | `llama-3.3-70b-versatile` | YES |

### Cross-Module Notes
| Module | Shared Data/Dependency | Notes |
|--------|----------------------|-------|
| RAG Chatbot (citizen) | `document_chunks` (pgvector) | Doc-Intel writes; Chatbot reads |
| Expense Categorizer | `ocr.py` pipeline | Will reuse for receipt OCR |
| Auth (cross-module) | `users.passport_key_hash` | Passport key shared across modules |

### Tech Stack Decisions (locked)
- **Framework**: FastAPI 0.115+
- **DB / Auth / Storage**: Supabase (Postgres 14 + pgvector + Storage + Auth)
- **OCR**: OCR Space API (1MB/request limit → page split via PyMuPDF)
- **Digital text**: PyMuPDF (`fitz`) for PDF, `python-docx` for DOCX
- **Classification**: **Groq** `llama-3.3-70b-versatile` (15ms latency tested) — replaces original OpenRouter spec
- **PII**: regex (Indian patterns) + spaCy `en_core_web_sm`
- **Signature**: OpenCV contour analysis
- **Embeddings**: `BAAI/bge-small-en-v1.5` (local, 384-dim)
- **Async**: FastAPI BackgroundTasks (no Celery/Redis)

### Known Issues / TODOs
- [x] ~~Migration SQL run in Supabase~~  (done 2026-05-02)
- [x] ~~Dependencies installed~~ (done 2026-05-02)
- [x] ~~Phases 1-6 complete~~ (done 2026-05-02)
- [ ] **Embedding model**: indexer falls back to a deterministic hash-stub on Python 3.14 because `fastembed`'s `py-rust-stemmers` dep has no Py3.14 wheel and torch+sentence-transformers stack has a `torchvision::nms` op-mismatch on 3.14. Action: when a Python 3.14 wheel ships for `py-rust-stemmers` (or torch/torchvision align), `pip install fastembed` and run `reindex_document(...)` over each existing chunk. The schema and pipeline are unchanged.
- [ ] **Frontend wiring** (next session): connect `pages.jsx → DocumentIntelligence` to these endpoints behind a `?live=1` flag — see `.claude/commands/connect-frontend.md`. Mock data stays default until contract parity is verified via `/contract-check doc-intel`.
- [ ] **Cross-module reuse**: `app/utils/storage.py`, `app/utils/audit.py`, `app/utils/doc_id.py`, `app/modules/document_intelligence/ocr.py` (Expense module reuses for receipts), and `app/modules/document_intelligence/indexer.py` (RAG chatbot reads from `document_chunks`) — keep these stable.

### How to bring up the backend (replicable from cold start)
```bash
cd backend

# 1. Install deps (skip torch/sentence-transformers; we use the hash-stub embedder for now)
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 2. Run migration in Supabase SQL Editor
#    URL: https://supabase.com/dashboard/project/xsioedgaczvzizatxteg/sql/new
#    Paste: migrations/001_document_intelligence.sql

# 3. Verify creds (4/4 should pass)
python -m scripts.verify_creds

# 4. Initialize DB (verifies tables + creates storage buckets + checks seed templates)
python -m scripts.init_db

# 5. Run server
uvicorn app.main:app --reload --port 8000

# 6. Smoke test
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/templates  # returns 10 seeded templates

# 7. OpenAPI docs
open http://127.0.0.1:8000/api/v1/docs
```
