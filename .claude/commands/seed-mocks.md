---
description: Generate realistic seed data for a module (frontend mock array OR backend DB seed) matched to its contract
argument-hint: <module-name> [count]  e.g. doc-intel 50
---

You are generating realistic mock / seed data for **`$ARGUMENTS`**.

## Pre-flight
1. Read `docs/module-specs/<index>-<module>.md` — every field with realistic value ranges.
2. Read the existing mock in `pages.jsx` for the module (the shape you must match).
3. Read `backend/app/modules/<module>/schemas.py` if it exists.

## Decide target
- **Frontend** (default): generate a JS array literal to paste into `pages.jsx`.
- **Backend**: generate a Python script under `backend/scripts/seed_<module>.py` that inserts via the repo layer.
- If unsure, ask the user.

## Generation rules
- **Realistic** — Indian context (names, addresses, INR amounts, IST timestamps, NH-44 etc.).
- **Varied** — distribute across all status/severity/category enum values (don't put 90% in one bucket).
- **Plausible distributions** — most expenses are small, a few are large; most tickets are open, a few resolved; most documents OCR clean, a few have low confidence.
- **Time-spread** — timestamps spread across the last 90 days, recent records weighted higher.
- **Consistent IDs** — UUIDv4. Reference IDs (e.g. ticket assigned to officer) must point to existing IDs.
- **Privacy** — fake but realistic. Never use real Aadhaar / PAN / phone numbers. Use the documented fake number ranges (Aadhaar starts with 1234-5678-..., PAN starts with `XXXPC1234X`, phone starts with `9876xxx...`).

## Volume
- Default: 50 records.
- If `[count]` argument provided, honour it (cap at 1000 to keep `pages.jsx` parseable).
- For backend seeding, no upper cap.

## Output
- Frontend: a single `const MOCK_<MODULE> = [ ... ];` array, or update the existing one. Show the diff.
- Backend: a script file with a clear `python backend/scripts/seed_<module>.py --count 50` invocation.
- Both: print a summary table — "50 records: 60% open, 30% resolved, 10% archived; 12% high priority…".

## Don't
- ❌ Use `Lorem ipsum` for free-text fields. Use a realistic phrase generator (or a fixed pool of plausible Indian civic phrases).
- ❌ Use `1, 2, 3` for IDs. UUIDs only.
- ❌ Hardcode tomorrow's date — use relative offsets so seeds stay valid as time passes.
