---
description: Run the readiness checklist before starting backend work on a module — catches gaps early
argument-hint: <module-name>  (optional — runs for all 8 if omitted)
---

You are validating that the CITADEL repo is ready to start backend work on **`$ARGUMENTS`** (or all modules if no argument).

## For each module in scope, verify all of:

### 1. Frontend artifacts
- [ ] Component exists in `pages.jsx` and is exported on `window`.
- [ ] Component is registered in `CITADEL.html`'s `subPages` map.
- [ ] All sub-tabs render without console errors at `http://127.0.0.1:8080/CITADEL.html`.
- [ ] Mock data inside the component is a single named const (e.g. `const MOCK_DOCS = [...]`) — easy to find and replace.

### 2. Spec
- [ ] `docs/module-specs/<n>-<module>.md` exists and is non-stub.
- [ ] Spec lists every endpoint with method, path, request shape, response shape, error codes.
- [ ] Spec lists every WebSocket channel (if applicable).
- [ ] Spec lists every background job and its trigger.
- [ ] Spec lists every external dependency (model files, third-party APIs, vector store).
- [ ] Spec has a "non-functional" section: latency target, throughput, retention.

### 3. Rules cross-check
- [ ] `.claude/rules/` covers the relevant areas (api, ml, security, data, code-style, testing, frontend, backend).
- [ ] No conflicts between the spec and the rules. Flag any.

### 4. Auth model
- [ ] Spec declares which roles can hit each endpoint.
- [ ] Spec marks which endpoints are gov-only vs citizen-only vs both.
- [ ] Spec lists the scopes required (e.g. `doc-intel:approve`).

### 5. Data model
- [ ] Spec lists every DB table to create with column types and indexes.
- [ ] Spec marks PII columns with their PII class (per `data-handling.md`).
- [ ] Spec declares retention period per table.
- [ ] Spec declares migration ordering vs other modules.

### 6. ML readiness
- [ ] Spec names the exact model(s) and version pin.
- [ ] Spec lists model file paths and download script entry.
- [ ] Spec declares the latency budget and the batching strategy.
- [ ] Spec lists the evaluation dataset and the baseline metric.

### 7. Backend prerequisites
- [ ] `backend/pyproject.toml` exists or there's a plan to create it.
- [ ] Python version pinned (`>=3.11,<3.13`).
- [ ] Database URL strategy decided (SQLite for dev, Postgres for prod).
- [ ] `backend/.env.example` has all the keys this module will need.
- [ ] Repo has `.gitignore` rules for `backend/storage/`, `backend/models/`, `*.sqlite3`, `.env`.

### 8. Operational
- [ ] Health check endpoint planned (`GET /api/v1/<module>/health`).
- [ ] Metrics endpoint planned or covered by global Prometheus middleware.
- [ ] Logging structured + redacted per security baseline.

## Output
A checklist table to the chat:

```
                       FRONT  SPEC  RULES  AUTH  DATA  ML   PREREQ  OPS
doc-intel               ✓      ✓     ✓      ✓     ✓    ✓    ✗       ✗
resume                  ✓      ✓     ✓      ✓     ✓    ✓    ✗       ✗
...
```

For each ✗, list the specific gap and a one-line action item. File any actionable gaps as `[ ]` items in `tasks/todo.md` under a `## Pre-Backend Gaps` section.

## Don't
- ❌ Mark a module ✓ if any sub-item is missing — be strict.
- ❌ Auto-fix the gaps — surface them and let the user decide.
- ❌ Spend time scaffolding backend code in this command — that's `/scaffold-module`.
