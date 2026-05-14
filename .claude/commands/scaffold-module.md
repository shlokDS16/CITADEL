---
description: Scaffold a backend module from its frontend mock (router + schemas + service + repo + pipeline + tests)
argument-hint: <module-name>  e.g. doc-intel | resume | traffic | anomaly | chatbot | fake-news | tickets | expenses
---

You are scaffolding a new backend module called **`$ARGUMENTS`** for the CITADEL project.

## Pre-flight (do these first, in parallel)
1. Read `docs/module-specs/<index>-<module>.md` for the contract this module must honour.
2. Read `.claude/rules/backend-conventions.md`, `api-conventions.md`, `ml-conventions.md`, `security-baseline.md`.
3. Grep `pages.jsx` for the matching React component to confirm the response shapes the frontend already expects.
4. Read `tasks/lessons.md` for any prior gotchas on this module.

## Plan (write to `tasks/todo.md` before coding)
Outline the files you will create, the endpoints, the schemas, and the test list. Wait for user confirmation if the plan exceeds 8 items.

## Generate
Create under `backend/app/modules/<module>/`:
- `__init__.py`
- `router.py` — APIRouter with all endpoints from the spec, **thin** — only parse/dispatch/format
- `schemas.py` — Pydantic v2 request and response models, separated, with `Field(... description=..., examples=...)`
- `service.py` — business logic, fully testable, no FastAPI imports
- `repo.py` — async SQLAlchemy queries, no business logic
- `pipeline.py` — ML inference (lazy-loaded model, deterministic where possible)
- `tests/conftest.py` — module-scoped fixtures
- `tests/test_router.py` — happy path + 401/403/422 per endpoint
- `tests/test_service.py` — business logic edge cases
- `tests/test_pipeline.py` — at least one inference smoke test on a fixture input

## Wire it up
- Mount the router in `backend/app/main.py` under `/api/v1/<module>`.
- Add module-specific config keys to `app/core/config.py` (with sensible defaults and `.env.example` entries).
- Add any new dependencies to `pyproject.toml`.

## Verify
- Run `pytest backend/app/modules/<module> -q` — all green.
- Run `ruff check backend/app/modules/<module>` — no lint errors.
- Run `mypy backend/app/modules/<module>` — no type errors.
- Hit each endpoint with `curl` or `httpx` from a quick repl and paste the responses into the review.

## Document
- Append a `## Review — Scaffold <module>` section to `tasks/todo.md` with:
  - File list
  - Endpoint list (with sample curl commands)
  - Test count + coverage % on the new module
  - Any deviations from the spec (with justification)
  - Open questions for the user

Do NOT wire the frontend to this backend yet — that's `/connect-frontend` after the contract is verified.
