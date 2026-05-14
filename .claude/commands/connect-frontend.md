---
description: Wire a backend endpoint into its frontend module behind a ?live=1 flag — keep the mock as default
argument-hint: <module-name>  e.g. doc-intel | resume | traffic | anomaly | chatbot | fake-news | tickets | expenses
---

You are wiring the backend for **`$ARGUMENTS`** into the matching frontend page, **without breaking the mock**.

## Hard rules
- **The mock data path stays the default.** Live calls are gated by `?live=1` (or a tweaks-panel toggle if we have one).
- **Never alter the neo-brutalist visual language.** Add no new CSS unless adding a new state (loading / error).
- **Never add a build step.** No `import`/`export`. New helpers attach to `window`.

## Pre-flight
1. Read `docs/module-specs/<index>-<module>.md` for the endpoint list and shapes.
2. Read `.claude/rules/frontend-conventions.md`.
3. Confirm the contract has been verified via `/contract-check $ARGUMENTS` (run it now if unsure).
4. Hit the live endpoint locally with `curl` to confirm the response shape.

## Plan
Outline:
- Which mock data arrays/objects in `pages.jsx` you'll replace with `fetch` calls
- The loading state, error state, and success state UI you'll add (use existing Skeleton + EmptyState primitives)
- The flag check (e.g. `const useLive = new URLSearchParams(location.search).get('live') === '1';`)
- Any new helpers (e.g. `apiFetch(path, opts)` in `components.jsx`)

## Implement
1. Add a generic `apiFetch` helper to `components.jsx` if one doesn't exist:
   - Reads `API_BASE` from a `<meta name="citadel-api-base">` tag in `CITADEL.html` (default `http://127.0.0.1:8000`).
   - Adds `Authorization: Bearer <token>` from `localStorage.getItem('citadel_token')`.
   - Adds `Idempotency-Key: crypto.randomUUID()` for mutating requests.
   - Returns parsed JSON or throws a typed error.
2. In the relevant module component in `pages.jsx`:
   - Add `const useLive = ...` flag.
   - Replace mock initialisation with `React.useEffect(() => { if (useLive) apiFetch(...).then(setX).catch(setErr); else setX(MOCK_X); }, []);`
   - Surface loading via existing `<Skeleton />`, error via `<EmptyState icon="⚠" title="Couldn't load" />`.
   - Mutating actions: same flag — call `apiFetch` when live, otherwise update local state as the mock did.
3. Add a small tweaks-panel toggle (optional) for "Live API" so the user can flip without editing the URL.

## Verify
- With server NOT running and no `?live=1`: page loads as before with mock data. Smoke-test every tab.
- With server running and `?live=1`: page loads from API. Smoke-test every tab. Confirm the network tab shows real calls.
- Trigger a forced 500 and confirm the error UI shows correctly.
- Confirm the visual diff vs. main is **only** the new loading/error states.

## Document
- Append `## Review — Connect <module>` to `tasks/todo.md` with:
  - Files touched (line counts)
  - The flag toggle method (URL param + tweaks-panel?)
  - Any contract drifts you found (and how you resolved them — usually with a backend update, not a frontend hack)
- If you found a backend bug, file a `[ ]` task in `tasks/todo.md` for the fix. Do not patch the frontend to compensate.
