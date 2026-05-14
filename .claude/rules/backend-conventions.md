# Rule: Backend Conventions (FastAPI)

> Applies to anything under `backend/`. Authoritative once backend rebuild begins.

## Stack (planned)
- **FastAPI** for HTTP. **Uvicorn** for the dev server. **Gunicorn + UvicornWorker** for prod.
- **Pydantic v2** for schemas — `BaseModel` for both request/response and DB DTOs.
- **SQLAlchemy 2.0 (async)** + **Alembic** for migrations. Default to **SQLite** for dev, **Postgres** for prod.
- **Redis** for cache, queues, and Celery broker (only when needed — start without it).
- **Loguru** or stdlib `logging` with structured JSON output.
- **pytest** + **httpx.AsyncClient** for tests. Coverage target: 80%.

## Module layout
```
backend/
├── app/
│   ├── main.py                 # FastAPI() app, mounts routers, middleware, lifespan
│   ├── core/
│   │   ├── config.py           # Pydantic Settings — env-driven
│   │   ├── security.py         # JWT issue/verify, password hashing
│   │   ├── deps.py             # Reusable dependencies (current_user, db_session, role_guard)
│   │   ├── errors.py           # Standard error shape + handlers
│   │   └── logging.py          # Structured logger setup
│   ├── db/
│   │   ├── base.py             # Declarative base + async engine
│   │   ├── session.py          # Async session factory
│   │   └── models/             # One file per domain (user.py, document.py, …)
│   ├── modules/                # ONE folder per ML module (mirrors frontend)
│   │   ├── doc_intel/
│   │   │   ├── router.py       # APIRouter — HTTP only, thin
│   │   │   ├── schemas.py      # Pydantic request/response models
│   │   │   ├── service.py      # Business logic — pure, testable
│   │   │   ├── pipeline.py     # ML inference (OCR + NER + layout)
│   │   │   ├── repo.py         # DB access (async SQLAlchemy)
│   │   │   └── tests/
│   │   ├── resume/
│   │   ├── traffic/
│   │   ├── anomaly/
│   │   ├── chatbot/
│   │   ├── fake_news/
│   │   ├── tickets/
│   │   └── expenses/
│   └── shared/
│       ├── pagination.py
│       ├── filters.py
│       └── audit.py            # gov-side audit logger
├── alembic/                    # migrations
├── tests/                      # cross-module integration tests
├── pyproject.toml
└── .env.example
```

## API conventions
- All routes prefixed with `/api/v1`.
- Module routers mounted as `/api/v1/<module>`. e.g. `/api/v1/doc-intel/upload`.
- Response shape standard: `{ "data": ..., "meta": { ... } }` for success, `{ "error": { "code": "...", "message": "...", "details": ... } }` for failure.
- HTTP status codes used semantically: 200 OK, 201 Created, 202 Accepted (for async ML jobs), 204 No Content, 400 Validation, 401 Auth, 403 Forbidden (RBAC), 404 Not Found, 409 Conflict, 422 Unprocessable, 429 Rate Limit, 500 Server.
- All list endpoints support `?page=`, `?page_size=` (default 25, max 100), `?sort=` (e.g. `-created_at`), `?q=` for search.
- All mutating endpoints require `Idempotency-Key` header for safe retries.

## Schema discipline
- Request and response models are **separate** classes (no shared Base for both).
- Naming: `<Resource>Create`, `<Resource>Update`, `<Resource>Out`, `<Resource>InDB`.
- Use `Field(..., description="...", examples=["..."])` so the OpenAPI docs are useful.
- Datetime fields are always **UTC ISO 8601** with `Z` suffix.
- IDs are UUIDv4 strings (not integers) to allow distributed generation.

## Service layer
- Routers do: parse → call service → format response. **No business logic in routers.**
- Services do: orchestration, validation, calls to repos / pipelines / external APIs.
- Repos do: SQLAlchemy queries only. No business logic.
- Pipelines do: ML inference. Stateless functions or thin classes.

## Async everywhere
- Default to `async def` for all router handlers.
- Use `httpx.AsyncClient` (not `requests`).
- ML inference that's CPU-bound runs in a thread pool (`asyncio.to_thread`) or a separate worker.

## Error handling
- Raise typed exceptions from `app.core.errors` (e.g. `NotFoundError`, `ValidationError`, `RateLimitError`).
- Global exception handler converts them to the standard error shape.
- Never expose raw stack traces to clients. Log them, return a `request_id`.

## Background work
- Quick (< 5s) → handle in-request.
- Medium (5–60s) → return 202 + job id, poll endpoint for status.
- Long (> 60s) → Celery + Redis, status endpoint, optional WebSocket push.

## Dev workflow
- `pip install -e ".[dev]"` to install in editable mode with dev extras.
- `uvicorn app.main:app --reload --port 8000` to run.
- `pytest -q` to test. `pytest --cov=app` for coverage.
- `alembic revision --autogenerate -m "add table x"` for migrations.

## Anti-patterns
- ❌ Sync DB calls in async handlers.
- ❌ Business logic in routers.
- ❌ Catching `Exception` and swallowing it.
- ❌ Returning raw SQLAlchemy models — always go through Pydantic `Out` schemas.
- ❌ Hardcoded secrets, URLs, model paths — everything via `core/config.py`.
