# CITADEL — Backend Blueprint

> Reference target structure for the FastAPI rebuild. Treat as a guide; final shape evolves with the modules.

## Top-level layout
```
backend/
├── pyproject.toml                 # deps, tool config (ruff, mypy, pytest)
├── README.md
├── .env.example                   # all env keys, placeholder values
├── .gitignore                     # storage/, models/, *.sqlite3, .env
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI() — lifespan, middleware, mount routers
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (env-driven)
│   │   ├── security.py            # JWT issue/verify, argon2, MFA
│   │   ├── deps.py                # current_user, db_session, role_guard, scope_guard
│   │   ├── errors.py              # typed exceptions + handlers
│   │   ├── logging.py             # structured logger + PII redaction filter
│   │   ├── ratelimit.py           # per-user / per-IP / per-endpoint
│   │   ├── audit.py               # gov-side audit log writer
│   │   └── encryption.py          # fernet helpers for sensitive columns
│   ├── db/
│   │   ├── base.py                # AsyncEngine, Base = DeclarativeBase
│   │   ├── session.py             # async_sessionmaker
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── user.py
│   │       ├── audit_log.py
│   │       ├── document.py
│   │       ├── resume.py
│   │       ├── traffic.py
│   │       ├── anomaly.py
│   │       ├── chatbot.py
│   │       ├── fake_news.py
│   │       ├── ticket.py
│   │       └── expense.py
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── auth/                  # login, refresh, MFA, password reset
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── tests/
│   │   ├── doc_intel/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   ├── repo.py
│   │   │   ├── pipeline.py
│   │   │   └── tests/
│   │   ├── resume/
│   │   ├── traffic/
│   │   ├── anomaly/
│   │   ├── chatbot/
│   │   ├── fake_news/
│   │   ├── tickets/
│   │   └── expenses/
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── pagination.py          # PageParams, Page[T]
│   │   ├── filters.py             # FilterParams base
│   │   ├── pii.py                 # PII detection helpers reused across modules
│   │   ├── ocr.py                 # shared OCR wrapper (doc-intel + expense receipts)
│   │   └── storage.py             # local fs / S3 abstraction with presigned URLs
│   └── ws/
│       ├── __init__.py
│       ├── manager.py             # connection registry
│       └── auth.py                # JWT-on-first-message handshake
├── scripts/
│   ├── download_models.py         # pulls PaddleOCR, BGE, YOLOv8, etc.
│   ├── seed_dev.py                # dev users + sample data
│   ├── seed_<module>.py           # per-module seeds (called by /seed-mocks)
│   └── rebuild_indexes.py         # rebuild FAISS indexes from sources
├── storage/                       # gitignored — uploaded files (local dev)
│   ├── doc_intel/
│   ├── resume/
│   ├── traffic/
│   ├── tickets/
│   └── expenses/
├── models/                        # gitignored — model artifacts
│   ├── paddle_ocr/
│   ├── yolov8n.pt
│   ├── bge_base/
│   ├── deberta_v3/
│   └── faiss_indexes/
└── tests/
    ├── conftest.py                # cross-module fixtures
    ├── test_health.py
    └── test_auth_e2e.py
```

## pyproject.toml skeleton
```toml
[project]
name = "citadel-backend"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "pydantic-settings>=2.6",
  "sqlalchemy[asyncio]>=2.0",
  "alembic>=1.13",
  "asyncpg>=0.30",                 # postgres async
  "aiosqlite>=0.20",               # sqlite async (dev)
  "argon2-cffi>=23.1",
  "pyjwt[crypto]>=2.9",
  "pyotp>=2.9",
  "cryptography>=43",
  "httpx>=0.27",
  "redis>=5.1",
  "loguru>=0.7",
  "python-multipart>=0.0.12",
  "python-magic-bin>=0.4 ; sys_platform == 'win32'",
  "python-magic>=0.4 ; sys_platform != 'win32'",
  "bleach>=6.1",
]

[project.optional-dependencies]
ml = [
  "transformers>=4.45",
  "sentence-transformers>=3.2",
  "scikit-learn>=1.5",
  "fairlearn>=0.11",
  "ultralytics>=8.3",
  "easyocr>=1.7",
  "paddleocr>=2.8",
  "spacy>=3.7",
  "vaderSentiment>=3.3",
  "faiss-cpu>=1.9",
  "statsmodels>=0.14",
  "ollama>=0.4",
  "faster-whisper>=1.1",
]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-cov>=5.0",
  "respx>=0.21",
  "freezegun>=1.5",
  "ruff>=0.7",
  "mypy>=1.13",
  "pip-audit>=2.7",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E","F","I","B","UP","N","SIM","RUF","ASYNC","S","A","COM"]
ignore = ["S101"]  # allow assert in tests

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["app", "tests"]
markers = [
  "slow: tests that take >1s",
  "integration: require DB",
  "gpu: require GPU",
  "eval: ML evaluation",
]
```

## main.py skeleton
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.ratelimit import RateLimitMiddleware
from app.modules.auth import router as auth_router
from app.modules.doc_intel import router as doc_intel_router
# ... other modules

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # warm any always-on resources
    yield
    # graceful shutdown

app = FastAPI(
    title="CITADEL API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs" if settings.ENV != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
)
app.add_middleware(RateLimitMiddleware)

register_exception_handlers(app)

app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(doc_intel_router.router, prefix="/api/v1/doc-intel", tags=["doc-intel"])
# ... other modules
```

## .env.example skeleton
```bash
# Core
ENV=development                          # development | staging | production
DATABASE_URL=sqlite+aiosqlite:///./citadel.sqlite3
REDIS_URL=redis://localhost:6379/0
CORS_ORIGINS=http://127.0.0.1:8080,http://localhost:8080

# JWT
JWT_SECRET=change-me-32+chars-of-random-bytes
JWT_ALG=HS256                            # HS256 dev, RS256 prod
JWT_ACCESS_TTL_MIN=30
JWT_REFRESH_TTL_DAYS=14

# Encryption (fernet)
FERNET_KEY=                              # base64 32-byte key, generate via: cryptography.fernet.Fernet.generate_key()

# Storage
STORAGE_BACKEND=local                    # local | s3
STORAGE_LOCAL_DIR=./storage
STORAGE_S3_BUCKET=
STORAGE_S3_REGION=

# ML
MODEL_DIR=./models
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5

# Feature flags (env-driven for v1)
FEATURE_LIVE_TRAFFIC_FEED=false
FEATURE_BIAS_PANEL=true
```

## Migration order (Alembic)
1. `users`, `roles`, `scopes`, `audit_log`
2. `templates`, `documents`, `document_entities`, `document_pii`
3. `jobs`, `candidates`, `candidate_skills`, `pipeline_stages`
4. `cameras`, `traffic_incidents`, `challans`, `offenders`
5. `sensors`, `sensor_readings`, `alerts`, `work_orders`
6. `chat_sessions`, `chat_messages`, `kb_documents`, `services_catalog`
7. `claims`, `verdicts`, `sources`
8. `tickets`, `ticket_updates`, `ticket_attachments`
9. `expenses`, `categories`, `budgets`, `receipts`, `imports`

## Build & run cheatsheet
```bash
# install
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -e ".[ml,dev]"

# init db
alembic upgrade head

# seed dev
python scripts/seed_dev.py

# pull models (one-time, slow)
python scripts/download_models.py

# run
uvicorn app.main:app --reload --port 8000

# test
pytest -q
pytest --cov=app --cov-report=term-missing
```

## Decision log (referenced by ADRs)
- **DB**: SQLite for dev, Postgres for staging+prod. Single async stack via SQLAlchemy 2.0.
- **ORM vs raw**: ORM. The performance savings of raw SQL aren't worth the lost type safety and auto-migrations.
- **Sync vs async**: async throughout. CPU-heavy ML wraps in `asyncio.to_thread`.
- **Job queue**: APScheduler in-process for v1. Celery+Redis when we need to scale workers separately.
- **WebSockets**: FastAPI-native (`starlette` based). Not switching to ASGI alternatives.
- **Vector store**: FAISS local file for v1. Qdrant when we need multi-tenant isolation.
- **Auth lib**: hand-rolled (JWT + argon2 + pyotp). Avoid `fastapi-users` — too opinionated for our two-issuer model.
