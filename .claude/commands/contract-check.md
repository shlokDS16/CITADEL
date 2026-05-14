---
description: Diff the frontend mock shapes against the backend response schemas — fail loudly on drift
argument-hint: <module-name>  e.g. doc-intel | resume | traffic | anomaly | chatbot | fake-news | tickets | expenses
---

You are validating the contract between frontend mock and backend schema for **`$ARGUMENTS`**.

## Pre-flight
1. Read `docs/module-specs/<index>-<module>.md` — the source of truth for the contract.
2. Read the matching React component in `pages.jsx` and capture every mock data shape it renders.
3. Read `backend/app/modules/<module>/schemas.py` and capture every Pydantic model.

## Compare
For each endpoint in the spec:
- Build a JSON Schema from the Pydantic `Out` model (`Model.model_json_schema()`).
- Build a JSON Schema (or just a sample) from the frontend mock object.
- Diff them field by field. Flag:
  - Fields present in mock but missing from backend response → backend gap (frontend will render undefined)
  - Fields present in backend but unused by frontend → either OK (forward-compat) or wasted bandwidth
  - Type mismatches (string vs number, ISO date vs unix epoch) → must fix
  - Optional vs required mismatches → must fix
  - Enum value drift → must fix

## Output
Write a `## Contract Check — <module> — <date>` section under `docs/api-contracts/<module>.md` with:
- ✅ Endpoints with full parity
- ⚠️ Endpoints with mismatches (table: field, mock type, backend type, severity, recommended fix)
- ❌ Endpoints in spec but missing on either side
- A copy-pasteable list of recommended changes (which file, which line)

## Action
- If the drift is in the **backend**: file a `[ ]` in `tasks/todo.md` (preferred — backend should match the spec).
- If the drift is in the **frontend mock**: update the mock to match. The mock is supposed to mirror the contract.
- If the drift is in the **spec itself**: ask the user before touching the spec.

Never silently "fix" by patching the side that's easiest. The spec is the contract.
