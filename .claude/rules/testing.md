# Rule: Testing

> Verification standard. Owner: anyone shipping code. Reviewer: `code-reviewer` agent.

## Pyramid (target distribution)
- **Unit** (≈70%): pure functions in `service.py`, `pipeline.py`, helpers.
- **Integration** (≈25%): router + service + repo + real DB (SQLite in-memory or test schema).
- **End-to-end smoke** (≈5%): full backend + a headless frontend interaction.
- **ML evaluation** (separate): per-module accuracy/F1 against fixed dataset, gated in CI.

## Tools
- `pytest` + `pytest-asyncio` + `httpx.AsyncClient`.
- `pytest-cov` for coverage. Threshold: **80% on changed lines** (not whole repo).
- `factory-boy` or `pydantic-factories` for test data.
- `respx` for mocking outbound HTTP.
- `freezegun` for time-sensitive logic.

## Test layout
```
backend/app/modules/<module>/tests/
├── conftest.py             # module-scoped fixtures
├── test_router.py          # HTTP layer (uses AsyncClient)
├── test_service.py         # business logic, mocked repo + pipeline
├── test_pipeline.py        # ML inference, real model on fixture inputs
├── test_repo.py            # DB queries against real SQLite
└── eval_<task>.py          # accuracy/F1 evaluation, run in CI nightly
```

## Naming
- File: `test_<thing>.py` for behavior, `eval_<task>.py` for ML metrics.
- Function: `test_<scenario>__<expected>` — e.g. `test_upload_oversized_pdf__returns_413`.
- Markers: `@pytest.mark.slow` for >1s tests, `@pytest.mark.integration`, `@pytest.mark.gpu`.

## What to test (mandatory)
- Every router endpoint: happy path + 4xx auth/validation + 5xx graceful failure.
- Every service method: positive case + at least one error path.
- Every Pydantic schema: a roundtrip case + a validation-failure case.
- Every RBAC dependency: citizen-tries-gov returns 403, gov-without-scope returns 403.
- Every ML pipeline: confidence thresholds, batch behavior, partial-failure handling.

## What NOT to test
- Pydantic library internals.
- SQLAlchemy library internals.
- Third-party SDK functionality (mock the boundary instead).

## Fixtures
- Database fixture provides a clean async SQLite per test (transaction rollback, not full recreate).
- `auth_client(role="gov_officer")` factory returns an `AsyncClient` with a valid JWT for that role.
- ML model fixtures: lazy-loaded, session-scoped (loading is expensive).

## Running tests
- All: `pytest -q`
- One module: `pytest backend/app/modules/doc_intel -q`
- With coverage: `pytest --cov=app --cov-report=term-missing --cov-report=html`
- Skip slow/GPU: `pytest -m "not slow and not gpu"`
- ML evals only: `pytest -m eval`

## Frontend tests
- No bundler → no Jest by default.
- For now: manual smoke via `python -m http.server 8080` and click-through.
- Future: Playwright headless against the served HTML, run in CI.

## CI gates
- Unit + integration tests: must pass on every PR.
- ML evals: nightly on `main`. PR fails only if regression > 2% on key metric.
- Coverage on changed lines: must be ≥ 80% (configurable in `pyproject.toml`).
- Lint (`ruff`) and type check (`mypy --strict` on `app/`): must pass.

## Anti-patterns
- ❌ Testing implementation details (private methods).
- ❌ Sleep-based waits — use `pytest-asyncio` and explicit awaits.
- ❌ Tests that depend on each other's order.
- ❌ Real network calls in unit/integration tests — always mock.
- ❌ Skipping a flaky test instead of fixing it.
