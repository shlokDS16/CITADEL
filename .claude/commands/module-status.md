---
description: Show the integration status of all 8 CITADEL modules — what's mock-only, what has a contract, what's wired
---

You are reporting the integration status of all 8 CITADEL modules. Output a clean ASCII table to the chat.

## For each of the 8 modules
Government: `doc-intel`, `resume`, `traffic`, `anomaly`
Citizen: `chatbot`, `fake-news`, `tickets`, `expenses`

Check:
1. **Frontend mock present?** Grep `pages.jsx` for the component name (`DocumentIntelligence`, `ResumeScreening`, etc.).
2. **Module spec written?** `docs/module-specs/<n>-<module>.md` exists?
3. **Backend module scaffolded?** `backend/app/modules/<module>/router.py` exists?
4. **Backend tests passing?** Run `pytest backend/app/modules/<module> -q --co` to count, `--tb=no` to run.
5. **Contract verified?** `docs/api-contracts/<module>.md` has a passing check newer than the latest spec change?
6. **Frontend wired (live mode)?** Grep `pages.jsx` for `apiFetch` calls in the module's component.
7. **Lines of frontend code** vs **lines of backend code** (rough effort indicator).

## Output table

```
MODULE          MOCK   SPEC   BACKEND   TESTS    CONTRACT   WIRED   FE LOC   BE LOC
─────────────   ────   ────   ───────   ──────   ────────   ─────   ──────   ──────
doc-intel        ✓      ✓      ✓        42/42     ✓ 04-30    ✗        ~480     ~620
resume           ✓      ✓      ✗         —          —        ✗        ~520      —
traffic          ✓      ✓      ✗         —          —        ✗        ~410      —
anomaly          ✓      ✓      ✗         —          —        ✗        ~380      —
chatbot          ✓      ✓      ✗         —          —        ✗        ~340      —
fake-news        ✓      ✓      ✗         —          —        ✗        ~360      —
tickets          ✓      ✓      ✗         —          —        ✗        ~390      —
expenses         ✓      ✓      ✗         —          —        ✗        ~310      —
```

## After the table
- Summary line: `<n>/8 mocked, <n>/8 with contract, <n>/8 with backend, <n>/8 wired live`.
- Suggested next module to tackle (cite the rationale: simplest data flow, blocks others, user explicitly asked).
- Any blockers from `tasks/todo.md` that affect more than one module.
