# Resume Screening — Frontend Context

> Captured 2026-05-02 before backend build. Single source of truth for what the frontend expects from `/api/resume/*`. Read this before scaffolding the backend.

---

## Module shell

- **Component**: `ResumeScreening({ onBack })` at `pages.jsx:1281–1308`
- **URL location**: Government portal → click "Resume Screening" gateway card → `subPages['resume']` in `CITADEL.html`
- **Header**: "RESUME SCREENING" · `GATEWAY_02` · subtitle "BERT + TF-IDF · SKILL MATCHING · BIAS DETECTION · 127 ACTIVE CANDIDATES" · accent `var(--red)`
- **Header action**: `+ NEW REQUISITION` button (currently inert; should open a job-create modal)
- **5 tabs**:
  | Key | Label | Badge |
  |---|---|---|
  | `jobs` | ACTIVE JOBS | 6 |
  | `pipeline` | PIPELINE | – |
  | `candidates` | CANDIDATES | 127 |
  | `analytics` | ANALYTICS | – |
  | `settings` | SETTINGS | – |
- All tabs render under the same `Tabs` primitive (accent red).

---

## Tab 1 — `ResumeJobs` (Active Jobs)

**File location**: `pages.jsx:1310–1350`. **Layout**: `.jobs-grid` (responsive grid of cards).

**Mock data shape** (`jobs` array, 6 entries):
```js
{ id: 'JOB-2026-041', title: 'Senior ML Engineer', dept: 'IT / Smart City',
  applicants: 47, shortlisted: 8, open: 12, days: 14, urgency: 'HIGH' }
```
Departments seen: `IT / Smart City`, `City Planning`, `Traffic Management`, `Revenue`, `PWD`, `IT / InfoSec`.
Urgency enum: `HIGH` | `NORMAL` | `LOW`.

**Per-card UI**:
- Header row: title + `id · dept` + urgency Badge (red/gold/default)
- 3 stat columns: `applicants`, `shortlisted` (green), `days+'d'` open
- Progress bar = shortlisted / applicants × 100
- "Conversion: N%" small caption
- 3 action buttons: `VIEW PIPELINE`, `BULK SCREEN`, `+ UPLOAD`

**Backend needed**:
- `GET /api/resume/jobs` returning the array (filterable by dept/urgency/status)
- `POST /api/resume/jobs` for "+ NEW REQUISITION"
- `PATCH /api/resume/jobs/{id}` for inline edits
- Wire `VIEW PIPELINE` → set tab=pipeline and filter by job
- Wire `BULK SCREEN` → bulk upload modal scoped to job
- Wire `+ UPLOAD` → single CV upload modal scoped to job

---

## Tab 2 — `ResumePipeline` (Kanban)

**File location**: `pages.jsx:1352–1412`. **Layout**: `.pipeline-toolbar` (FilterBar + SegmentedControl) above `KanbanBoard`.

**Toolbar**:
- `FilterBar` filters: `Job` (string list), `Min Score` ('90+', '80+', '70+', '60+')
- `SegmentedControl` — `KANBAN` / `TABLE` toggle (TABLE view not yet built)

**Columns** (6, fixed):
```js
[{key:'sourced',     label:'SOURCED',     color:'var(--cyan)'},
 {key:'screened',    label:'AI-SCREENED', color:'var(--gold)'},
 {key:'shortlisted', label:'SHORTLISTED', color:'var(--green)'},
 {key:'interview',   label:'INTERVIEW',   color:'#d946ef'},
 {key:'offer',       label:'OFFER',       color:'var(--red)'},
 {key:'hired',       label:'HIRED',       color:'#000'}]
```

**Card mock shape** (13 entries, distributed across all 6 columns):
```js
{ name: 'Priya Sharma', score: 94, exp: '5 yrs',
  skills: ['Python','ML','TF'], status: 'shortlisted' }
```

**Per-card render** (custom via `renderCard` prop):
- `.kanban-card-header`: Avatar (size 28) + name + exp + colored score badge (≥90 green, ≥75 gold, else cyan)
- `.kanban-skills`: first 3 skills as Chips

**Backend needed**:
- `GET /api/resume/pipeline?job_id=&min_score=` → grouped-by-stage payload
- `POST /api/resume/candidates/{id}/move-stage` (drag-and-drop or button)
- `POST /api/resume/candidates/bulk-move`
- (Future) Drag-and-drop wiring on `KanbanBoard` primitive

---

## Tab 3 — `ResumeCandidates` (Split list + detail)

**File location**: `pages.jsx:1414–1480` (list) + `1482–1555` (detail). **Layout**: `.candidate-split` (left list pane / right detail pane).

**State**: `selected` (id), `compareMode`, `compare[]`, `search`.

**Toolbar**:
- `SearchBar` placeholder "Search by name or skill..."
- `Toggle` "Compare mode"
- `COMPARE (n)` button when `compareMode && compare.length ≥ 2`

**Mock candidate shape** (6 entries):
```js
{ id: 1, name: 'Priya Sharma', role: 'ML Engineer', score: 94,
  skills: ['Python','ML','TensorFlow','Docker','AWS'],
  exp: '5 yrs', edu: 'M.Tech CS', loc: 'Bengaluru',
  email: 'priya.s@mail', source: 'Referral',
  status: 'SHORTLISTED', bias: { gender: 'female', age: 28 } }
```
Status enum (uppercase in mock): `SHORTLISTED` | `REVIEW` | `REJECTED`.
Source enum: `Referral` | `LinkedIn` | `Naukri` | `Direct`.

**Per-card render** (`.candidate-card-enhanced`):
- Top row: optional checkbox (compare mode) + Avatar (40) + name + role+exp + colored score badge
- Skills row: first 4 chips + `+N` chip if more
- Footer: `📍 loc`, `📥 source`, status pill

**Detail pane** (`CandidateDetail`):
- **Header**: Avatar(64) + name (Chakra Petch 22pt) + role + meta row (📍 location, 🎓 education, 💼 experience, ✉ email) + `ProgressRing` (size 80, value=score, label MATCH SCORE)
- **Section 1 — SKILL PROFILE**: `RadarChart` + 6 skill bars
  - Skills (hardcoded keys): `Technical Skills`, `Experience Depth`, `Communication`, `Leadership`, `Culture Fit`, `Problem Solving` — each 0..100
- **Section 2 — AI ANALYSIS**: 4 `.analysis-card`s with icons + headlines:
  - ✓ Strong match (skills coverage)
  - ⚠ Experience gap (years short)
  - ✓ Location match
  - ! Bias check — gender balanced
- **Section 3 — DECISION HISTORY**: `StatusTimeline` with steps Applied → AI Screened → Shortlisted → Interview → Offer (current=2)
- **Action row**: 📅 Schedule Interview, 📝 Add Note, ✉ Send Email, ✕ Reject (red), ✓ Advance Stage (green)

**Backend needed**:
- `GET /api/resume/candidates?job=&min_score=&status=&q=&page=` (paginated)
- `GET /api/resume/candidates/{id}` (full profile incl. skill_profile, bias_panel, history)
- `POST /api/resume/candidates/upload` (single CV multipart)
- `POST /api/resume/candidates/bulk` (bulk CVs zip or multi-file)
- `PATCH /api/resume/candidates/{id}` (manual field edits)
- `POST /api/resume/candidates/{id}/notes` (timeline notes)
- `POST /api/resume/candidates/compare` (≤3 ids)
- `GET /api/resume/candidates/{id}/cv` (signed URL)
- `POST /api/resume/candidates/{id}/move-stage` (advance/reject)
- `POST /api/resume/candidates/{id}/schedule-interview` (Calendar.googleapis hook later)

---

## Tab 4 — `ResumeAnalytics`

**File location**: `pages.jsx:1557–1629`.

**KPI grid (4 cards)**:
| Label | Value | Trend dir | Source endpoint |
|---|---|---|---|
| TIME TO HIRE | "24d" | down (good) | `GET /analytics/kpis` |
| OFFER ACCEPT | "82%" | up | `GET /analytics/kpis` |
| COST PER HIRE | "₹18k" | down (good) | `GET /analytics/kpis` |
| ACTIVE SCREENS | "127" | up | `GET /analytics/kpis` |

**Funnel chart (6 stages)**:
```js
[{label:'Applied',     value:342, dropRate:0},
 {label:'AI Screened', value:284, dropRate:17},
 {label:'Shortlisted', value:87,  dropRate:69},
 {label:'Interviewed', value:42,  dropRate:52},
 {label:'Offered',     value:18,  dropRate:57},
 {label:'Hired',       value:12,  dropRate:33}]
```
Endpoint: `GET /analytics/funnel?period=30d`.

**Source donut** (4 segments):
```js
[{label:'Referral', value:42, color:'var(--green)'},
 {label:'LinkedIn', value:28, color:'var(--cyan)'},
 {label:'Naukri',   value:18, color:'var(--gold)'},
 {label:'Direct',   value:12, color:'var(--red)'}]
```
Center: 342 APPLICATIONS. Endpoint: `GET /analytics/sources?period=30d`.

**Diversity widget** (3 horizontal bars):
- Gender (applied): 42% F · 58% M (red / cyan split)
- Gender (hired): 50% F · 50% M (red / cyan split)
- Experience mix: 20% (<2y green), 35% (2-5y gold), 30% (5-10y cyan), 15% (10y+ red)

Endpoint: `GET /analytics/diversity?period=30d`.

**Applications per week**: `MiniChart` red, data `[45, 62, 58, 74, 82, 69, 88, 94]`. Endpoint: `GET /analytics/applications-trend?period=8w`.

---

## Tab 5 — `ResumeSettings`

**File location**: `pages.jsx:1631–1668`.

**Scoring Weights widget**:
- 5 sliders (`brutal-slider` range 0..60):
  ```js
  { skills: 40, experience: 25, education: 15, location: 10, cultureFit: 10 }
  ```
- Live "TOTAL: N%" with red badge "⚠ MUST EQUAL 100" if sum ≠ 100
- Endpoints: `GET /settings/weights`, `PUT /settings/weights` (validate sum=100)

**Bias Detection widget**:
- 4 toggles (defaults shown):
  ```js
  { gender: true, age: true, location: false, name: true }
  ```
  All redaction labels: "Redact gender", "Redact age", etc.
- Info banner: "All screening decisions are logged with the current config for auditability."
- Endpoints: `GET /settings/bias-flags`, `PUT /settings/bias-flags`

---

## Cross-cutting state the backend must own

| Data | Source-of-truth table | API surface |
|---|---|---|
| Jobs (requisitions) | `jobs` | `/jobs`, `/jobs/{id}`, `/jobs/{id}/close` |
| Candidates | `candidates` (PII encrypted) | `/candidates`, `/candidates/{id}`, `/candidates/{id}/cv` |
| Skills (per candidate) | `candidate_skills` | embedded in `CandidateOut` |
| Bias panel (per candidate) | `candidate_bias_panel` | embedded in `CandidateOut` |
| Pipeline transitions | `pipeline_history` | `/candidates/{id}/move-stage`, `/pipeline/{job_id}` |
| Skill profile (radar 6 axes) | `candidate_skill_profile` | embedded in detail call |
| Scoring weights | `scoring_config.weights` | `/settings/weights` |
| Bias redaction flags | `scoring_config.bias_flags` | `/settings/bias-flags` |
| Analytics aggregates | computed from `candidates` + `pipeline_history` | `/analytics/*` |

---

## Frontend primitives consumed (all already in `components.jsx`)

`SubPageHeader`, `Tabs`, `Badge`, `Chip`, `Avatar`, `Toggle`, `SearchBar`, `FilterBar`, `SegmentedControl`, `KPICard`, `MiniChart`, `Donut`, `RadarChart`, `FunnelChart`, `KanbanBoard`, `ProgressRing`, `StatusTimeline`, `EmptyState`, `Modal`, `apiFetch`, `useToast`, `RichEditor` (potentially for JD editor in `+ NEW REQUISITION`).

---

## CSS classes the backend rebuild must keep working

`.jobs-grid`, `.job-card`, `.job-header`, `.job-title`, `.job-meta`, `.job-stats`, `.job-stat-v`, `.job-stat-l`, `.job-progress`, `.job-actions`,
`.pipeline-toolbar`, `.kanban-card-header`, `.kanban-name`, `.kanban-meta`, `.kanban-score`, `.kanban-skills`,
`.candidate-split`, `.candidate-list-pane`, `.candidate-detail-pane`, `.candidate-card-enhanced`, `.candidate-card-top`, `.candidate-name`, `.candidate-role`, `.candidate-skills`, `.candidate-footer`, `.candidate-status`,
`.candidate-detail`, `.detail-header`, `.detail-role`, `.detail-meta-row`, `.detail-section`, `.detail-section-title`,
`.analysis-cards`, `.analysis-card`, `.ac-icon`,
`.skill-row`, `.weight-row`, `.weight-label`, `.weight-val`, `.weight-total`,
`.candidate-score-big`.

---

## Known frontend bugs / inert buttons (will be fixed during backend wiring)

- `+ NEW REQUISITION` (header): no onClick — should open job-create modal
- `VIEW PIPELINE`, `BULK SCREEN`, `+ UPLOAD` per job card: inert — should jump tab or open modal
- `FilterBar` on Pipeline: `values={{}}, onChange={() => {}}` — does nothing
- `SegmentedControl KANBAN/TABLE`: TABLE view not implemented
- `COMPARE (n)` button: inert — should open compare modal showing N candidates side by side
- `📅 SCHEDULE INTERVIEW`, `📝 ADD NOTE`, `✉ SEND EMAIL`, `✕ REJECT`, `✓ ADVANCE STAGE`: all inert
- `compareMode` checkbox interactions: state managed but no submit path
- KanbanBoard cards: no drag-and-drop — clicks have no effect either
- `ResumeSettings` weights/flags: no save button — state local only

---

## Frontend ⇄ Backend field map (for the rewrite)

When I rewrite `ResumeScreening` to talk to the live backend, here's the renaming I'll apply:

| Frontend mock key | Backend field | Notes |
|---|---|---|
| `j.id` | `code` | "JOB-2026-041" string id |
| `j.dept` | `department` | full string |
| `j.days` | `days_open` | computed: NOW - posted_at |
| `j.applicants` | `applicants` (count from `candidates`) | aggregate |
| `j.shortlisted` | `shortlisted` (count where status='shortlisted') | aggregate |
| `c.score` | `score` | float 0..100 |
| `c.exp` | `experience_years` rendered as "Xyrs" | |
| `c.skills` | `skills_extracted` | |
| `c.loc` | `location` | |
| `c.edu` | `education` | |
| `c.bias` | `bias_panel.{predicted_gender, predicted_age_band}` | |
| skill profile axes | `skill_profile.{technical_skills, experience_depth, communication, leadership, culture_fit, problem_solving}` | |
| funnel `dropRate` | computed: `(prev - curr) / prev * 100` | |
| settings `cultureFit` | `culture_fit` | snake_case in API |

---

## Build sequence (suggested phases for backend)

1. **Phase 1 — Foundation**: migration SQL (jobs, candidates, candidate_skills, candidate_bias_panel, candidate_skill_profile, pipeline_history, scoring_config), seed default weights+flags, `/api/resume/health`.
2. **Phase 2 — Pipeline**: `extractor` (PDF/DOCX → text), `redactor` (PII strip for scoring path), `skill_extractor` (taxonomy + spaCy EntityRuler), `embedder` (BGE-base 768-dim), `scorer` (cosine + tfidf + jaccard composite), `bias_panel_builder`.
3. **Phase 3 — Jobs CRUD + Candidate CRUD + Upload**.
4. **Phase 4 — Pipeline endpoints + bulk move**.
5. **Phase 5 — Analytics (5 endpoints)**.
6. **Phase 6 — Settings (weights + bias flags)**.
7. **Phase 7 — Frontend rewrite**: replace all mock arrays with `apiFetch` calls, wire all inert buttons, open NewJob modal, wire upload modal, drag-and-drop on Kanban, schedule-interview / reject / advance flows.
8. **Phase 8 — Integration test via Playwright** with a real CV file.

---

## Credentials needed (already in `.env`)

- Supabase (DB + storage bucket `resumes`)
- Groq (`llama-3.3-70b-versatile`) for skill extraction fallback
- OCR.space for scanned PDFs (already wired in `app/modules/document_intelligence/ocr.py`, can be reused)
- No new keys required.

---

## Reusable from Doc Intel build

- `app/utils/storage.py` — same upload/signed-url pattern, just bucket name = `resumes`
- `app/utils/audit.py` — same audit helpers, new actions: `cv_uploaded`, `cv_parsed`, `score_computed`, `stage_moved`, `note_added`, `interview_scheduled`
- `app/utils/doc_id.py` pattern → new `app/utils/job_id.py` for "JOB-2026-NNN" sequential codes
- `app/modules/document_intelligence/ocr.py` — share for scanned-PDF resumes
- `app/modules/document_intelligence/extractor.py` — share for PDF/DOCX text extraction
- `app/modules/document_intelligence/pii.py` — share for redaction layer (regex + spaCy)
- `app/modules/document_intelligence/indexer.py` — pattern for embedding (will need to swap to 768-dim BGE-base for resumes since 384-dim hash-stub is too coarse for ranking; alternatively keep hash-stub then upgrade later)
