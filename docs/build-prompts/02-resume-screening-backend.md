# Resume Screening — Restructured Build Spec

> Captured 2026-05-04 from the user's prompt + 4 reference screenshots. Grounds the entire build.
> Rule of thumb: every visible UI element resolves to a real backend call. Zero hardcoded mocks.

---

## 1) Tech-stack decisions (locked)

| Concern | Decision |
|---|---|
| LLM for parsing + culture-fit | **Groq** `llama-3.3-70b-versatile` (already in use, 15ms tested) |
| OCR for scanned resumes | OCR.space (reuse `app/modules/document_intelligence/ocr.py`) |
| PDF text | PyMuPDF (`fitz`) |
| DOCX text | `python-docx` |
| Embeddings | `BAAI/bge-small-en-v1.5` via `indexer.py` (hash-stub fallback OK for now; semantic similarity remains stable) |
| PII redaction primitives | regex + spaCy NER (reuse `app/modules/document_intelligence/pii.py`) |
| Database / storage / auth | Supabase (new bucket `resumes`) |
| Async work | FastAPI `BackgroundTasks` |
| Telegram | Bot API direct via `httpx` (`https://api.telegram.org/bot{TOKEN}/...`) |
| Bot token | `YOUR_TELEGRAM_BOT_TOKEN` (env `TELEGRAM_BOT_TOKEN`) |

---

## 2) Per-job settings (decided based on user clarification)

Drop the global `scoring_config` table. Instead, add JSONB columns directly to `jobs`:
- `scoring_weights` JSONB — `{skills:40, experience:25, education:15, location:10, culture_fit:10}`
- `bias_flags` JSONB — `{redact_gender:true, redact_age:true, redact_location:false, redact_name:true}`
- `auto_shortlist_threshold` FLOAT — score above this → auto-Shortlisted; below → Rejected (default 70)

Defaults are written when a job is created; can be edited any time. Editing triggers re-scoring of all candidates for that job.

---

## 3) Pipeline stages (5, per user spec)

Per the user, 5 columns:
1. **Shortlisted** — auto when `final_score >= auto_shortlist_threshold`
2. **Rejected** — auto when `final_score < auto_shortlist_threshold`, or manual
3. **Interview** — manual move (after schedule)
4. **Offer** — manual move
5. **Recruited** — final stage (manual)

Ingestion path: upload → parse → score → auto-route to Shortlisted or Rejected. There is NO "sourced/screened" intermediate column — those are internal statuses surfaced via the audit log.

---

## 4) Telegram integration (decided)

We have a token; we don't have any chat IDs yet. Plan:
- **Connect flow**: Settings panel shows a "Connect Telegram" widget. Click → backend hits `getMe` to get bot username → frontend shows `https://t.me/{username}` link → user sends `/start` to the bot → frontend hits `/telegram/discover` which calls `getUpdates` and stores any new chat IDs in `telegram_chats` table.
- **Send flow**: schedule-interview / reject-with-note send to ALL stored chat IDs (that's the HR team's chat). Per-candidate chat IDs are a future feature.
- **AI cheer-up message** for rejection uses Groq with a short prompt: "Write a 3-sentence kind, encouraging rejection message for a candidate named X who applied for role Y."

---

## 5) Candidate detail view actions (per user spec)

| Action | Behaviour |
|---|---|
| Schedule Interview | Date picker + auto-generated message → Telegram → status moves to Interview, timeline updated |
| Add Note | Free-text note saved to candidate notes |
| Reject | Modal: "Custom note" or "Generate AI cheer-up" → optional Telegram → status → Rejected, timeline stops at Rejected |
| Advance Stage | Move to next stage in the pipeline |
| Send Email | **REMOVED** per user request |
| Compare | Toggle compare mode → pick ≤3 → opens dedicated Compare board with similarity-driven analysis |

The "Decision History" timeline always shows: Applied → AI Screened → [current stage]. If rejected, timeline stops at Rejected and shows previous stages.

---

## 6) Candidates section restructure (per user spec)

Replace the flat "all candidates" view with a job-scoped flow:
1. List of job cards (compact)
2. Click a job → shows candidates for that job, grouped by stage (or filterable)
3. Search by name/skill (real backend filter)
4. Filter by stage / score / source
5. Click candidate → detail modal (radar + AI cards + timeline + actions)

---

## 7) Analytics (real-time, enterprise-grade)

Replace mock numbers with computed aggregates. Required widgets:

**KPIs (4)**:
- Time to hire (avg days from `applied_at` to `hired_at`)
- Offer accept rate (% of offers that became hires)
- Cost per hire (placeholder ₹/job, can stay if no real cost data)
- Active screens (candidates currently in pipeline, not Rejected/Recruited)

**Funnel** (6 stages, drop% computed from real counts):
Applied → AI Screened → Shortlisted → Interviewed → Offered → Recruited

**Source effectiveness donut**: count by `source` field

**Diversity** (post-redaction aggregate only):
- Gender mix at applied vs hired (from bias_panel.predicted_gender)
- Experience mix bands (<2y / 2-5y / 5-10y / 10y+)

**Trends**:
- Applications per week (last 8 weeks)
- Top 5 most-recruited skills
- Avg score per job (top 5 jobs)
- Bias-redaction config in use across jobs (audit summary)

All endpoints take `?period=7d|14d|30d|90d` and return computed values from real tables.

---

## 8) Frontend gorgeous-presentation requirements (per user)

- Job detail modal: **NOT a wall of text**. Structured presentation with:
  - Role title hero + Department + Urgency pill
  - 4 KPI strips: Openings · Min Years · Min Match % · Auto-shortlist threshold
  - Skills section: must-have chips (red border) + nice-to-have chips (gold border)
  - Experience block: years range + preferred titles + preferred industries
  - Education block: minimum level + preferred fields
  - Location block: cities + remote/relocation badges
  - Culture-fit block: keyword chips + values chips
  - Original JD text (collapsible accordion, kept for reference)

- Pipeline: per-job kanban modal (no global pipeline view).

- Compare board: side-by-side matrix with:
  - Header row: each candidate's avatar/name/score
  - Skill overlap (Venn-style or bars)
  - Per-dimension comparison (skills, exp, edu, loc, culture)
  - Strengths/Weaknesses callouts (Groq-generated for the trio)

---

## 9) Build order

1. **Migration + seed** — schema + 5 detailed jobs + a hand-curated JD JSON each
2. **Backend services** — parser, redactor, scorer, analyzer, comparator, telegram
3. **Backend endpoints** — jobs, candidates, pipeline, settings, analytics, telegram, compare
4. **Frontend rewrite** — full ResumeScreening overhaul, all 5 tabs
5. **Playwright integration test** — end-to-end with a fixture resume

---

## 10) Open assumptions (stated upfront, no clarification needed)

- `chat_id` for Telegram is discovered automatically via `getUpdates` after the user clicks "Connect" and sends `/start`. If the user prefers a fixed chat, they can set `TELEGRAM_DEFAULT_CHAT_ID` in `.env`.
- "Live AI interview" for the Offer stage is **deferred** — the column exists, but auto-promotion based on AI interview score is a follow-up build.
- "Cost per hire" without source data stays as a configurable env value (`COST_PER_HIRE_RUPEES`, default 18000) — replaced with real data when integrated with HRMS.
- Bias panel is shown to all gov officers (OK in this jurisdiction). If legal feedback says aggregate-only, we toggle a single env flag.
- Pre-seeded jobs: 5 detailed (Senior ML Engineer, Urban Planner, Data Analyst, Civil Engineer, Security Architect) — same titles as the original mock so the demo flow lands familiar.
