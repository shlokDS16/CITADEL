# Rule: ML / Pipeline Conventions

> Applies to anything that loads a model or runs inference. Owner: `ml-pipeline-engineer` agent.

## Module-to-stack map

| Module | Frontend page | Primary stack | Inference latency target |
|---|---|---|---|
| Document Intelligence | `DocumentIntelligence` | Tesseract / PaddleOCR + spaCy NER + LayoutLMv3 | <2s per page |
| Resume Screening | `ResumeScreening` | Sentence-Transformers (BGE-base) + scikit-learn TF-IDF | <500ms per CV |
| Traffic Violations | `TrafficViolations` | YOLOv8n + DeepSort + EasyOCR (plate) | <80ms per frame |
| Anomaly Monitoring | `AnomalyMonitoring` | scikit-learn IsolationForest + statsmodels | <100ms per check |
| RAG Chatbot | `RAGChatbot` | Ollama Llama-3.2-3B + FAISS (BGE embeddings) | <3s p50, <10s p99 |
| Fake News Detector | `FakeNewsDetector` | DeBERTa-v3 + ensemble + source credibility heuristics | <1.5s per claim |
| Support Tickets | `SupportTickets` | DistilBERT (zero-shot) + VADER + rule router | <300ms per ticket |
| Expense Categorizer | `ExpenseCategorizer` | TF-IDF + LinearSVC + IsolationForest | <50ms per txn |

## Where models live
- All model artifacts under `backend/models/` (gitignored — pulled by `scripts/download_models.py`).
- Each module's `pipeline.py` declares paths via constants (no hardcoded absolute paths).
- Model versions pinned in `pyproject.toml` extras: `transformers==4.45.*`, `ultralytics==8.3.*`, etc.

## Loading
- **Lazy load on first use**, not at app startup (faster boot, smaller memory if module unused).
- Cache loaded models on the module (`@functools.lru_cache(maxsize=1)` for singleton).
- For multi-worker setups, prefer pre-warming via a startup job rather than loading inside request path.

## Inference functions
- Pure functions: input → output. No side effects (no DB writes, no logging beyond debug).
- Type-hinted with Pydantic models or `dataclasses.dataclass`.
- Always return a confidence score (0..1) when applicable. Frontend shows it.
- Always return a `model_version` string so we can A/B test and audit.

## Threading
- CPU-bound inference inside an async handler → wrap in `asyncio.to_thread(...)`.
- GPU inference → batch requests via a queue + worker (single-process FastAPI can't share GPU memory cleanly).
- Long-running inference (>5s) → return 202 + job id (see `api-conventions.md`).

## Batching
- For OCR, embedding, and classification, accept batch endpoints (`/documents/batch`, `/resumes/batch`).
- Internal batch size capped (default 32) to avoid OOM.
- Per-item failures don't fail the whole batch — return partial results with per-item status.

## Vector store
- Start with **FAISS local file** (one index per RAG module). Easy to ship.
- Index files versioned alongside the data they were built from.
- Embedding model and FAISS index version stored in metadata next to the index file.
- Migration to **Qdrant** when we need multi-tenant isolation or live updates.

## Confidence and uncertainty
- Every classifier surfaces a confidence score in the response.
- Below a per-module threshold (configurable), route to **human review** queue instead of auto-decide.
- Default thresholds:
  - Resume auto-shortlist: ≥0.85
  - Fake news verdict shown without warning: ≥0.80
  - Traffic violation auto-issue challan: ≥0.92
  - Expense category auto-apply: ≥0.75

## Bias & fairness (Resume + Tickets)
- Hiring decisions surface a bias check panel: predicted gender / age proxy / school tier confidence + fairness diff.
- Block auto-actions when predicted attribute confidence is high (system shouldn't be the one with strong demographic signals).
- Ticket priority must not learn from sender name — strip PII before classification.

## PII handling in pipelines
- Document Intelligence: detect PII (Aadhaar, PAN, phone, email, address) and surface as `pii: [{...}]` in response.
- Frontend shows redaction toggle. Backend can return both `text_raw` and `text_redacted`.
- PII never logged. Requests with PII tagged for short retention (24h, not 30d).

## Reproducibility
- Random seeds set per pipeline in config (`MODEL_SEED=42`).
- Inference is deterministic where supported; non-determinism (LLM temperature) documented in module spec.

## Evaluation
- Each pipeline ships with `tests/eval_<task>.py` that runs against a frozen test set in `backend/tests/fixtures/`.
- CI runs eval and compares against baseline metrics — fails if regression > 2% on key metric.

## Anti-patterns
- ❌ Loading models inside `if __name__ == "__main__"` and assuming it runs.
- ❌ Sync `requests.get()` inside an async handler.
- ❌ Mutating shared model state across requests (some HuggingFace models do this — wrap them).
- ❌ Returning a verdict without a confidence — frontend has no way to grade trust.
- ❌ Logging full document text or PII to stdout.
