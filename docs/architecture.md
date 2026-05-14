# CITADEL — System Architecture

## What this is
A dual-portal civic intelligence platform for Indian context. **Government** portal for officials (4 modules) and **Citizen** portal for residents (4 modules). Each module is an AI-assisted workflow over real civic data.

## Modules at a glance

### Government (clearance: Alpha)
| # | Module | Page component | Primary AI capability |
|---|---|---|---|
| 1 | Document Intelligence | `DocumentIntelligence` | OCR + NER + Layout extraction → structured data + PII detection |
| 2 | Resume Screening | `ResumeScreening` | Embedding-based ranking + skill extraction + bias check |
| 3 | Traffic Violations | `TrafficViolations` | YOLOv8 detection + DeepSort tracking + plate OCR |
| 4 | Anomaly Monitoring | `AnomalyMonitoring` | IoT sensor fusion + IsolationForest + temporal anomaly |

### Citizen (service portal)
| # | Module | Page component | Primary AI capability |
|---|---|---|---|
| 5 | RAG Chatbot | `RAGChatbot` | Llama-3.2 + FAISS retrieval over civic knowledge base |
| 6 | Fake News Detector | `FakeNewsDetector` | DeBERTa ensemble + source credibility + bias profile |
| 7 | Support Tickets | `SupportTickets` | DistilBERT classification + VADER sentiment + auto-routing |
| 8 | Expense Categorizer | `ExpenseCategorizer` | TF-IDF + LinearSVC + IsolationForest for anomalies |

## Logical architecture
```
┌─────────────────────────────────────────────────────────────┐
│                         BROWSER                              │
│   CITADEL.html (App shell, routing, auth state)             │
│   ├── components.jsx  (primitives: KPI, Donut, Kanban, ...) │
│   ├── pages.jsx       (8 module pages with sub-tabs)         │
│   └── tweaks-panel.jsx (runtime theme tweaks)                │
└─────────────────────────────────────────────────────────────┘
                        │ HTTPS + JWT
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI BACKEND                         │
│   /api/v1/<module>/*   — module routers                      │
│   /api/v1/auth/*       — auth (gov + citizen issuers)        │
│   /ws/<module>/*       — WebSocket channels                  │
│                                                              │
│   app/                                                       │
│   ├── core/    (config, security, deps, errors, logging)    │
│   ├── db/      (async SA + Alembic, models per domain)      │
│   ├── modules/ (one folder per ML module — mirrors frontend) │
│   └── shared/  (pagination, audit, filters)                  │
└─────────────────────────────────────────────────────────────┘
                  │           │              │
        ┌─────────┘           ▼              └────────┐
        ▼                ┌─────────┐                  ▼
   ┌─────────┐           │  Redis  │             ┌─────────┐
   │Postgres │           │ (cache, │             │ Storage │
   │  (prod) │           │  queue) │             │ (files, │
   │ SQLite  │           └─────────┘             │ models) │
   │  (dev)  │                                   └─────────┘
   └─────────┘
                                                  ┌─────────┐
                                                  │  FAISS  │
                                                  │ (vectors│
                                                  │ for RAG)│
                                                  └─────────┘
```

## Module ↔ Frontend mapping
Each module's page component in `pages.jsx` corresponds to one FastAPI router in `backend/app/modules/<module>/`. The mapping is:

| Frontend page | Frontend page-id | Backend module dir | URL prefix |
|---|---|---|---|
| `DocumentIntelligence` | `doc-intel` | `backend/app/modules/doc_intel/` | `/api/v1/doc-intel` |
| `ResumeScreening` | `resume` | `backend/app/modules/resume/` | `/api/v1/resume` |
| `TrafficViolations` | `traffic` | `backend/app/modules/traffic/` | `/api/v1/traffic` |
| `AnomalyMonitoring` | `anomaly` | `backend/app/modules/anomaly/` | `/api/v1/anomaly` |
| `RAGChatbot` | `chatbot` | `backend/app/modules/chatbot/` | `/api/v1/chatbot` |
| `FakeNewsDetector` | `fake-news` | `backend/app/modules/fake_news/` | `/api/v1/fake-news` |
| `SupportTickets` | `tickets` | `backend/app/modules/tickets/` | `/api/v1/tickets` |
| `ExpenseCategorizer` | `expenses` | `backend/app/modules/expenses/` | `/api/v1/expenses` |

## Auth model
- Two JWT issuers: `citadel-gov` and `citadel-citizen`. Same shape, different audience.
- Roles: `gov_admin`, `gov_officer`, `gov_analyst`, `citizen`. Plus per-module scopes (`doc-intel:approve`, `traffic:issue-challan`, etc.).
- MFA mandatory for gov accounts (TOTP + backup codes).
- Citizen JWTs cannot reach `/api/v1/<gov-module>/*`. Server enforced.
- See `.claude/rules/security-baseline.md`.

## Data model strategy
- **Tenancy**: every domain table has `owner_role` (`gov` | `citizen`) + `owner_id`. Service layer base query filters automatically.
- **Audit log**: gov-side mutations always write `audit_log`. Append-only. FOIA-grade.
- **PII**: tagged at schema level (`pii_class: personal | sensitive | restricted`). Encryption at column level for `sensitive`.
- **Retention**: per-table `RETENTION_DAYS`. Daily soft-delete job, 30-day grace, then hard delete.
- See `.claude/rules/data-handling.md`.

## ML serving
- Models lazy-loaded per module on first inference, cached with `lru_cache(1)`.
- CPU inference inside async handlers wraps in `asyncio.to_thread`.
- Long inference (>5s) returns `202 Accepted` + job id, polled or pushed via WS.
- Vector store: FAISS local files for v1. Migrate to Qdrant when multi-tenancy demands isolation.
- See `.claude/rules/ml-conventions.md`.

## Real-time channels
| Channel | Producer | Consumer | Purpose |
|---|---|---|---|
| `/ws/traffic/live-feed` | Traffic worker | TrafficViolations live tab | Streaming detections |
| `/ws/anomaly/alerts` | Anomaly job | AnomalyMonitoring alerts tab | New severity-coded alerts |
| `/ws/tickets/inbox` | Ticket router | SupportTickets gov inbox | Newly-routed tickets |
| `/ws/<module>/jobs/<job_id>` | Job runner | Job submitter UI | Progress for long ML jobs |

## Deployment topology (planned)
- **Dev**: single uvicorn process + SQLite + local FAISS file. Frontend served by `python -m http.server`.
- **Staging**: gunicorn + uvicorn workers + Postgres + Redis. Frontend on Netlify/Vercel.
- **Prod**: same as staging but +Celery worker pool + S3-compatible storage + Vault for secrets.

## Cross-cutting concerns
- **Logging**: structured JSON, `request_id` correlation, PII redaction filter.
- **Tracing**: OpenTelemetry spans per request, exported to whatever backend (Jaeger/Honeycomb) prod uses.
- **Metrics**: Prometheus middleware. Dashboards for: request rate, p50/p95/p99 latency, error rate per module, ML inference latency per module.
- **Health**: `GET /api/v1/<module>/health` per module. Aggregate `GET /api/v1/health` for the whole app.
- **Background jobs**: APScheduler for v1 (in-process). Celery+Redis when we need to scale workers separately.
- **Feature flags**: env-driven for v1 (`FEATURE_<NAME>=true`). Migrate to LaunchDarkly / Unleash / GrowthBook when we need user-targeted rollouts.

## What's intentionally not in scope (yet)
- Multi-region deployment
- Mobile native app (frontend is responsive web first)
- Offline / PWA mode
- Federated learning / on-device inference
- Government federation across states (each state would be a tenant in a multi-tenant deploy later)
