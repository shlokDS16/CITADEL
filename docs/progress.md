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

---

## Module: Fake News Detector (Citizen M2)
### Status: 🟡 IN PROGRESS — Phase 0 (Foundation) shipped & verified

Plan: `tasks/todo.md` (9 phases). Contract: `docs/module-specs/06-fake-news-detector.md` (honored + extended). Architecture: 5-layer waterfall (heuristics → fast transformers → RAG/NLI → LLM rationale) + multi-modal forensics + ingest-fed CIB + HITL + drift.

### Phase 0 — Foundation (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `backend/requirements.txt` | +torch/transformers/hf_hub/scipy/sklearn/tldextract/readability-lxml (production ML, declared for deploy) | OK |
| `backend/app/config.py` | +`GOOGLE_FACTCHECK_API_KEY` + `FN_*` settings (model pins, thresholds, feeds) | OK |
| `.gitignore` | +`backend/models/` + `.fn_*` runtime artifacts | OK |
| `backend/sql/fake_news_schema.sql` | 11-table DDL (spec-06 + `fn_*` extensions), idempotent — **user runs in Supabase** | OK |
| `backend/app/modules/fake_news/__init__.py` | Router export | OK |
| `backend/app/modules/fake_news/router.py` | Thin HTTP layer; `/api/v1/fake-news/health` | OK |
| `backend/app/modules/fake_news/schemas.py` | `HealthResponse` (full analysis schemas → Phase 1) | OK |
| `backend/app/modules/fake_news/service.py` | Real readiness probe (ML runtime / models dir / Supabase tables / keys) | OK |
| `backend/app/main.py` | Mounted `fake_news_router` under `/api` | OK |

**Verified:** `GET /api/v1/fake-news/health` → 200. torch 2.11.0 / transformers 5.3.0 / onnxruntime 1.26.0 / hf_hub 1.5.0 / sklearn 1.8.0 on Python 3.14.3. Groq + Google Fact Check keys detected. Tables correctly reported missing until user runs the DDL (graceful degrade confirmed).

**Pending user action:** run `backend/sql/fake_news_schema.sql` in Supabase SQL editor (not blocking Phase 1, needed by Phase 4 persistence).

**Env note:** torch IS used here (verified working on Py 3.14.3) — supersedes the "no torch" note in requirements.txt which was Doc-Intel-era.

### Phase 1 — Layer 1 (heuristics + adversarial + schemas) (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/adversarial.py` | Homoglyph/leetspeak/zero-width/letter-spacing normalizer → match-variant + evasion signals (zero-width built from codepoints; interior-only de-leet) | OK |
| `modules/fake_news/heuristics.py` | L1: clickbait/urgency/authority/emotional/conspiracy lexicons, caps/exclamation metrics, financial-lure + phishing, keyless RDAP domain age, suspicious-TLD, sha256 + 64-bit SimHash + `fn_debunked` near-dup match, peak-driven risk + scam-triad boost | OK |
| `modules/fake_news/schemas.py` | Full spec-06 shapes (AnalyzeIn/Options, AnalysisOut, ClaimAnalysis, SourceCredibility, Bias/Sentiment/Manipulation, RelatedFactCheck, Bulk*) + additive prod fields (risk_score/needs_review/quota_exhausted/nli_label/layers/reasoning); input sanitation | OK |
| `modules/fake_news/service.py` | L1 waterfall orchestrator: URL fetch + readability extract, normalize → heuristics → honest preliminary verdict (`_verdict_from_l1`), credibility-from-domain, best-effort persist to `analyses` | OK |
| `modules/fake_news/router.py` | `POST /api/v1/fake-news/analyze` (run_in_threadpool; 422 on bad input) | OK |

**Verified (live HTTP):** scam text → LIKELY_FAKE conf 0.56 risk 0.74 + scam-triad + 6 red flags + needs_review; clean → LIKELY_REAL risk 0.0; obfuscated → leetspeak captured, L1 stays conservative (L2's job); `https://www.bbc.com/news` → article text extracted + RDAP credibility (36 yr, score 95 HIGH); missing text → 422; IMAGE → graceful "Phase 5" notice. No mock values — every field computed.

### Phase 2 — Layer 2 (transformer classifiers + VADER) (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/pipeline.py` | Lazy `@lru_cache` HF singletons; **self-calibration** (each binary head auto-detects its risk label by scoring canonical pos/neg) + discrimination guard (`_CAL_MIN_GAP=0.10`) + architecture guard; VADER sentiment; `warmup()` | OK |
| `modules/fake_news/service.py` | L2 fused into waterfall (`_l2_run`, `_combine_verdict`): peak L1 + classifier + propaganda, agreement boost; clickbait→manipulation via max(); honest reasoning of which heads are live | OK |
| `modules/fake_news/router.py` | `POST /api/v1/fake-news/warmup` (prod readiness, threadpool) | OK |
| `backend/requirements.txt` | + vaderSentiment | OK |

**Model probe outcome (verified, not assumed — HF label conventions/quality differ):**
- `vikram71198` fake-news: opaque `LABEL_0/1`; **discriminative with the canonical calibration pair** (gap 0.9998 — clean→0.0001, scam→0.9998). Self-calibration adapted; kept & contributing.
- `valurank` clickbait: loads but near-flat (gap 0.008) → **auto-excluded**; L1 lexical clickbait carries it (manip.clickbait 78 on clickbait sample).
- `QCRI` propaganda: custom `BertForTokenAndSequenceJointClassification` (not pipeline-safe) → **arch-guarded, excluded** with clear reason.
- `d4data` bias: repo has **no PyTorch/safetensors weights** → load-fails gracefully, honest reason.

**Verified (live HTTP):** warmup 200 (fake_news+sentiment up, others honestly false); scam → LIKELY_FAKE conf 0.80 risk 0.85 (fake 0.9998 + L1 0.74 + agreement); clean → LIKELY_REAL conf 0.66 risk 0.0 (fake 0.0001); clickbait → UNCERTAIN (manip.clickbait 78, VADER −0.78); per-head exclusion reasons surfaced in `layers`; latency ~450 ms warm. Production safeguard: the waterfall **never emits noise from a bad model** — the spec's "classifier = weak signal, RAG/NLI verifies" thesis.

**Follow-up (tracked):** replace bias model with a safetensors-loadable one + add a political-lean model so `bias_profile` (L/C/R) is real (currently honestly `null`); evaluate a stronger propaganda model. Targeted for Phase 3 (credibility/bias) / Phase 8 polish — not blocking.

### Phase 3 — Layer 3 (RAG fact verification + NLI + credibility) (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/credibility.py` | `source_credibility_db` KB — 29-row curated seed (PIB/Boom/AltNews/Factly allowlist, wire/quality, satire blocklist), `lookup`/`score_for`/`upsert`, 5-min cache, degrades if absent | OK |
| `modules/fake_news/fact_check.py` | spaCy claim extraction (checkworthiness) → evidence (Google Fact Check API → fact_check_feed → keyless web reuse of citizen web_search → Wikipedia REST) → DeBERTa-v3 NLI stance → per-claim verdict + supporting/contradicting sources; `search()` | OK |
| `modules/fake_news/pipeline.py` | + `nli()` (DeBERTa-v3-base-mnli-fever-anli, name-mapped labels) | OK |
| `modules/fake_news/service.py` | L3 fused via `_final_verdict` (only path besides debunk-hash to high-confidence REAL/FAKE — verified, not style); KB credibility replaces Phase-1 guess; fact-check feed refresh loop (<=6h) + credibility seed (lifespan); dead `_credibility_from_domain` removed | OK |
| `modules/fake_news/router.py` | `GET /sources`, `GET /sources/{domain}`, `PUT /sources/{domain}` (officer-editable), `GET /related-fact-checks?q=` | OK |
| `app/main.py` | lifespan: start/stop `start_background_feed_refresh` | OK |
| `backend/requirements.txt` | + sentencepiece (DeBERTa-v3 tokenizer) | OK |

**NLI probe-verified:** id2label entailment/neutral/contradiction; supports→entail 0.99, refutes→contradict 0.99.
**Verified (live HTTP):** "COVID-19 vaccines contain microchips" → **FAKE 0.93 / risk 0.95** via 4 retrieved fact-check contradictions + NLI (L1 risk was 0.01 — L1/L2 alone *missed* it; Layer 3 caught it, proving the multi-layer thesis); scam → FAKE 0.93; true statement → LIKELY_REAL risk 0.32 (honest — won't assert REAL without corroboration; live retrieval is non-deterministic); `/sources` → 29 seeded rows; `/sources/altnews.in` → HIGH allowlist; `PUT /sources/{d}` officer-edit OK; `/related-fact-checks?q=covid vaccine microchip` → real FactCheck.org URLs. Calibration tuned: 2+-source corroboration 0.82, noisy fake-head down-weighted (L1 0.50 / fake 0.30). Zero LLM tokens used. ~4–7 s/analysis (async lands Phase 7).

### Phase 4 — LLM rationale + persistence + HITL + feedback loop (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/llm_rationale.py` | Layer 4: Groq llama-3.3-70b via LiteLLM provider-chain (citizen pattern), `_QuotaExhausted`; JSON rationale (central_claim/rationale/recommendation); never raises | OK |
| `modules/fake_news/repo.py` | Persist analyses + claim_analyses; history (paged/filtered) + stats; soft-delete; HITL review queue; feedback ground-truth; refittable logistic meta-classifier (no-op < 30 samples) | OK |
| `modules/fake_news/service.py` | Layer 4 wired behind token-frugal gate (risk≥threshold OR UNCERTAIN — NOT needs_review); `repo.persist_analysis` replaces inline; signed-bigint simhash; removed dead `_persist` + stale reasoning line | OK |
| `modules/fake_news/heuristics.py` | `to_signed64`/`to_unsigned64` — SimHash↔Postgres bigint lossless mapping | OK |
| `modules/fake_news/router.py` | `GET /analyses/{id}`, `GET /history`, `GET /history/stats`, `DELETE /history/{id}`, `GET /review-queue`, `POST /review/{id}/decide`, `POST /feedback`, `POST /meta/refit`, `GET /meta/status` | OK |
| `modules/fake_news/schemas.py` | `ReviewDecision`, `FeedbackIn` | OK |

**Bug found+fixed during verify:** unsigned 64-bit SimHash overflowed Postgres `bigint` → every persist silently failed; signed two's-complement mapping at the DB boundary fixes it losslessly. Token-frugal gate was firing on clean content (needs_review ≈ always true pre-fact-check) → dropped `needs_review` from the gate.
**Verified (live HTTP):** scam → FAKE + Layer-4 Groq rationale ("central_claim", reasoning, "Recommendation: Remove…"); clean → Layer-4 **skipped** (no tokens burned); history total + real stats (checks 2 / fake 1 / real 1); `GET /analyses/{id}` returns verdict + 2 claim rows + signed simhash; review-queue→decide (verdict corrected, feedback recorded); direct feedback OK; soft-delete removes from history; `meta/refit` honestly no-ops < 30 samples.

### Phase 5 — Multi-modal forensics (deepfake / AI-image / video) (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/media_forensics.py` | EXIF inspection (missing camera / AI-tool software strings), image verdict from fabricated prob, video = OpenCV 8-frame sample + aggregate (mean/max/frac), type sniffing; never raises | OK |
| `modules/fake_news/pipeline.py` | `image_forensics()` — SigLIP2 3-class (AI/Deepfake/Real) primary + ViT binary fallback; label-name normalization to {real, ai_generated, deepfake, fabricated} | OK |
| `modules/fake_news/service.py` | `analyze_media_content()` — forensics + optional caption merged worst-case through the text waterfall (out-of-context image + misleading caption); IMAGE/VIDEO `analyze()` branch fetches from URL else points to upload route; persisted | OK |
| `modules/fake_news/router.py` | `POST /api/v1/fake-news/analyze/media` (multipart, size-capped) | OK |

**Probe-verified:** primary `prithivMLmods/AI-vs-Deepfake-vs-Real-Siglip2` (SiglipForImageClassification, AI/Deepfake/Real); fallback `dima806/deepfake_vs_real_image_detection` (ViT, Real/Fake) — both load, label mapping robust.
**Verified (live HTTP):** synthetic PNG → FAKE 0.9992 (SigLIP2 AI 0.993) + "No EXIF metadata" flag; image+scam caption → FAKE with caption run through full text waterfall & merged ("worst-case of media vs text"); 15-frame video → 8 frames sampled+aggregated, verdict produced; empty file → 422. Persisted; no mocks; no 5xx.

### Phase 6 — CIB / propagation (ingest-fed) (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/propagation.py` | Parse uploaded share-graph (CSV/JSON, flexible column names); 4 signals — burst (peak-window rate + relative concentration), coordination (≥3 accounts, same content, ≤90s → clusters), bot-likeness (mass-created/low-follower/hyperactive), structural (union-find fragmentation vs connected cascade); CIB verdict ORGANIC/SUSPICIOUS/COORDINATED. Honest: GNN-*inspired* heuristics, clear error if input lacks fields (no fabricated metrics) | OK |
| `modules/fake_news/repo.py` | `save_propagation_run` / `list_propagation_runs` → `fn_propagation_runs` | OK |
| `modules/fake_news/router.py` | `POST /api/v1/fake-news/propagation/analyze` (multipart, size-capped), `GET /propagation/runs` | OK |

**Bug found+fixed in verify:** `_burst` degenerated (0.0 then 1.0 false-positive) when total span < window / lone-event window — now requires a real ≥3-event cluster for the density term.
**Verified (live HTTP):** coordinated graph (12 mass-created low-follower bots, same content in a 55 s burst) → **COORDINATED cib 0.95** (burst 1.0 / coord 1.0 / bot 0.8 / struct 1.0, 1 cluster); organic graph (varied ages, 3-day spread, connected reshare chain) → **ORGANIC cib 0.068** (all signals low); malformed input → 422 with actionable message; runs persisted + listable.

### Phase 7 — drift + bulk + exports + report-to-PIB + share (2026-05-18)
| File | Purpose | Status |
|------|---------|--------|
| `modules/fake_news/drift.py` | Jensen-Shannon divergence (scipy) of recent vs reference window over risk/confidence/verdict-mix; `fn_drift_snapshots`; honest "insufficient data" | OK |
| `modules/fake_news/service.py` | Bulk (≤50, async in-memory batch + worker); `report_html`/`report_pdf` (fpdf2); `report_to_pib` (logs + Telegram); HMAC signed share token (7-day); drift snapshot folded into the feed loop | OK |
| `modules/fake_news/router.py` | `GET /drift`, `POST /bulk` (202), `GET /bulk/{id}`, `POST /bulk/upload-csv`, `GET /analyses/{id}/report.html|.pdf`, `POST /analyses/{id}/report`, `POST /analyses/{id}/share`, `GET /shared/{token}` | OK |

**Bug found+fixed in verify:** `report_pdf` 500 — fpdf2 2.8.7 cursor trap mixing deprecated `cell(ln=1)` with `multi_cell(0,...)`; rewrote with `multi_cell(epw, …, new_x/new_y)` + `set_x(l_margin)`.
**Verified (live HTTP):** bulk → 202 + async worker, 2/2 done, per-item verdict+analysis_id, CSV variant 202; `report.html` 200 (self-contained); `report.pdf` 200 valid `%PDF` + attachment header; **report→PIB logged + Telegram actually sent**; share → signed token → `/shared/{token}` resolves, bad token → 404; drift honest "insufficient reference data" (correct — needs history accrual).

### Phase 8 — Frontend revamp (live-wired, brutalist) (2026-05-18)
Driven by `ui-ux-pro-max` (Data-Dense Dashboard pattern; brutalist visual language kept per hard-rule). `pages.jsx` `FakeNewsDetector` + sub-components fully rewritten — **no mocks, every value from `/api/v1/fake-news/*`** via `apiFetch` (+ stable `x-user-id`).
| Piece | What | Status |
|------|------|--------|
| `FakeNewsStatusStrip` | live `/health` + `/drift` (replaces fake "BERT 92.3%") | OK |
| `FakeNewsWaterfall` | the signature 4-node L1→L4 pipeline viz from `layers` | OK |
| `FakeNewsAnalyze` | TEXT/URL/IMAGE/VIDEO, live analyze + `/analyze/media`, verdict slab, claim cards w/ NLI supporting/contradicting evidence, credibility ring, manipulation, sentiment, red flags, related fact-checks, reasoning trace, report.html/pdf + share + report-to-PIB; reopen-from-history | OK |
| `FakeNewsBulk` | live `/bulk` (202) + poll progress + per-item links; CSV upload | OK |
| `FakeNewsHistory` | live `/history/stats` KPIs + paged/searchable `/history` table + reopen + soft-delete | OK |
| `FakeNewsReview` | NEW HITL tab: `/review-queue` → decide → `/review/{id}/decide`; meta-classifier status + refit | OK |
| `FakeNewsLearn` | live trusted sources from `/sources` allowlist + red-flag guide + 5-step | OK |
| `styles.css` | `=== FAKE NEWS DETECTOR ===` brutalist section (theme-independent explicit colours; reduced-motion) | OK |

**Verified in-browser (preview tools, :8080 → :8000):** app compiles clean in-browser Babel (`FakeNewsDetector` is a valid fn, **no JSX/runtime errors**); status strip shows real `torch 2.11.0 · transformers 5.3.0 · GROQ KEYED · FACT-CHECK GOOGLE · DRIFT BASELINE`; scam → **FAKE 93% / risk 95%**, 4-layer waterfall all "on" with live values (L1 0.40 / L2 100% / L3 2 claims / L4 reasoned), 5 red flags, **real RELATED FACT-CHECKS** (Newschecker/Factly with working links); HISTORY KPIs+table live (the run persisted); REVIEW queue + meta status live; LEARN trusted sources live from the credibility KB; BULK renders. Only console output = benign in-browser-Babel notice. Brutalist language fully preserved (screenshot).
