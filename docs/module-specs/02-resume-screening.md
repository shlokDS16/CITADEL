# Module Spec — 02 · Resume Screening

> Frontend: `ResumeScreening` in `pages.jsx`. Tabs: Active Jobs · Pipeline · Candidates · Analytics · Settings.
> Backend: `backend/app/modules/resume/`. Prefix: `/api/v1/resume`.
> Audience: gov officers (`gov_officer`, `gov_analyst`, `gov_admin`) — HR / hiring teams across departments (PWD, Revenue, IT, City Planning, Traffic Mgmt).

## Outcome
Officers post requisitions for civic roles, upload candidate CVs (single + bulk), and watch the system score each CV against the job description, extract skills, surface a bias panel, and route candidates through a kanban pipeline (sourced → screened → shortlisted → interview → offer → hired). Analytics shows funnel, source mix, time-to-hire, and diversity. Settings controls scoring weights and which protected attributes are redacted before scoring.

## Personas & permissions
- `gov_officer`: post jobs, upload resumes, move candidates through stages, leave notes
- `gov_analyst`: read-only on candidates + analytics + bias dashboards
- `gov_admin`: manage scoring weights, manage bias-redaction config, archive jobs

## Endpoints

### Jobs (Requisitions)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/jobs` | `resume:read` | List jobs, filter `?status=open,closed&dept=&urgency=` |
| `POST` | `/jobs` | `resume:write` | Create new requisition (returns 201 + JobOut) |
| `GET` | `/jobs/{job_id}` | `resume:read` | Job detail + funnel snapshot |
| `PATCH` | `/jobs/{job_id}` | `resume:write` | Update title, dept, openings, urgency, status |
| `DELETE` | `/jobs/{job_id}` | `resume:admin` | Soft-archive (no hard delete — audit) |
| `POST` | `/jobs/{job_id}/close` | `resume:write` | Close requisition, freeze pipeline |

### Candidates & Uploads
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/candidates/upload` | `resume:upload` | Single CV upload (multipart) → 202 + job id |
| `POST` | `/candidates/bulk` | `resume:upload` | Bulk upload (≤100 CVs as zip or multi-file) → batch id |
| `GET` | `/candidates` | `resume:read` | Search + filter (`?job=&min_score=&status=&q=`) |
| `GET` | `/candidates/{cand_id}` | `resume:read` | Full profile, skill radar, bias panel, history |
| `PATCH` | `/candidates/{cand_id}` | `resume:write` | Manual edits to extracted fields (skills, exp years) |
| `POST` | `/candidates/{cand_id}/notes` | `resume:write` | Add note to candidate timeline |
| `POST` | `/candidates/compare` | `resume:read` | Compare ≤3 candidates side-by-side |
| `GET` | `/candidates/{cand_id}/cv` | `resume:read` | Pre-signed CV download (5min TTL) |

### Pipeline (Kanban)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/pipeline/{job_id}` | `resume:read` | All candidates grouped by stage |
| `POST` | `/candidates/{cand_id}/move-stage` | `resume:write` | Move candidate (sourced → screened → shortlisted → interview → offer → hired/rejected) |
| `POST` | `/candidates/bulk-move` | `resume:write` | Move multiple candidates in one action |
| `POST` | `/candidates/{cand_id}/reject` | `resume:write` | Reject with required reason code |

### Jobs status (async)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/jobs-async/{task_id}` | `resume:read` | Poll status of upload/parse task |
| `GET` | `/batches/{batch_id}` | `resume:read` | Batch upload progress + per-CV state |

### Analytics
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/analytics/funnel` | `resume:read` | Applied → Screened → Shortlisted → Interviewed → Offered → Hired counts |
| `GET` | `/analytics/sources` | `resume:read` | Source effectiveness donut data |
| `GET` | `/analytics/diversity` | `resume:read` | Gender/experience mix by stage (post-redaction aggregate only) |
| `GET` | `/analytics/kpis` | `resume:read` | Time-to-hire, offer-accept, cost-per-hire, active screens |
| `GET` | `/analytics/applications-trend` | `resume:read` | Per-week applications |

### Settings
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/settings/weights` | `resume:read` | Current scoring weights (skills/exp/edu/loc/culture) |
| `PUT` | `/settings/weights` | `resume:admin` | Update weights (must sum to 100) |
| `GET` | `/settings/bias-flags` | `resume:read` | Which attributes are redacted from scoring |
| `PUT` | `/settings/bias-flags` | `resume:admin` | Toggle redaction for gender/age/location/name |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + embedding model load status |

## Schemas (key shapes)

### Job
```python
class JobOut(BaseModel):
    id: UUID
    code: str                                 # e.g. "JOB-2026-041"
    title: str
    department: str                           # "IT / Smart City", "PWD", ...
    openings: int
    urgency: Literal["LOW","NORMAL","HIGH"]
    status: Literal["draft","open","closed","archived"]
    description: str                          # JD text used for embedding
    required_skills: list[str]
    nice_to_have_skills: list[str]
    min_experience_years: int
    posted_at: datetime
    days_open: int
    applicants: int
    shortlisted: int
    posted_by: UUID
```

### Candidate
```python
class CandidateOut(BaseModel):
    id: UUID
    job_id: UUID
    name: str                                 # may be redacted in scoring path
    email: str                                # PII, encrypted at rest
    phone: str | None                         # PII
    location: str
    role_applied: str
    score: float                              # 0..100, weighted composite
    confidence: float                         # 0..1, model confidence
    skills_extracted: list[str]
    skills_matched: list[str]
    skills_missing: list[str]
    experience_years: float
    education: str
    source: Literal["Referral","LinkedIn","Naukri","Direct","Other"]
    status: Literal["sourced","screened","shortlisted","interview","offer","hired","rejected"]
    bias_panel: BiasPanel | None              # nullable until scoring complete
    rejection_reason: str | None
    cv_storage_path: str                      # internal — never exposed
    created_at: datetime
    updated_at: datetime
```

### Bias panel
```python
class BiasPanel(BaseModel):
    predicted_gender: Literal["male","female","unknown"]
    predicted_gender_confidence: float
    predicted_age_band: Literal["<25","25-34","35-44","45+","unknown"]
    school_tier_estimate: Literal["tier1","tier2","tier3","unknown"]
    fairness_diff_pct: float                  # composite score delta vs baseline
    auto_action_blocked: bool                 # true if predicted attr conf > 0.85
    redacted_attributes: list[str]            # what was hidden during scoring
```

### Skill profile (for radar chart)
```python
class SkillProfile(BaseModel):
    candidate_id: UUID
    technical_skills: float                   # 0..100
    experience_depth: float
    communication: float
    leadership: float
    culture_fit: float
    problem_solving: float
```

### Pipeline move
```python
class PipelineMoveIn(BaseModel):
    new_stage: Literal["sourced","screened","shortlisted","interview","offer","hired","rejected"]
    note: str | None = None
    rejection_reason: Literal["skills_gap","experience_gap","location","compensation","cultural_fit","other"] | None
```

### Settings
```python
class ScoringWeights(BaseModel):
    skills: int                               # default 40
    experience: int                           # default 25
    education: int                            # default 15
    location: int                             # default 10
    culture_fit: int                          # default 10

    @model_validator(mode="after")
    def sum_to_100(self): ...

class BiasFlags(BaseModel):
    redact_gender: bool = True
    redact_age: bool = True
    redact_location: bool = False
    redact_name: bool = True
```

## Data model
```sql
jobs (
  id UUID PK,
  code VARCHAR(32) UNIQUE,                 -- "JOB-2026-041"
  title VARCHAR(255),
  department VARCHAR(128),
  openings INT,
  urgency VARCHAR(8),                       -- LOW/NORMAL/HIGH
  status VARCHAR(16) DEFAULT 'open',
  description TEXT,
  description_embedding VECTOR(768),        -- pgvector or stored as bytea blob
  required_skills JSONB,
  nice_to_have_skills JSONB,
  min_experience_years INT DEFAULT 0,
  posted_by UUID NOT NULL,
  posted_at TIMESTAMPTZ DEFAULT NOW(),
  closed_at TIMESTAMPTZ NULL,
  archived_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_jobs_status ON jobs(status);
CREATE INDEX ix_jobs_dept ON jobs(department);

candidates (
  id UUID PK,
  job_id UUID FK -> jobs.id,
  name VARCHAR(255),
  email_encrypted TEXT,                     -- fernet (PII personal)
  email_hash CHAR(64),                      -- hmac, for de-dup lookup
  phone_encrypted TEXT NULL,
  location VARCHAR(128),
  role_applied VARCHAR(255),
  score FLOAT,
  confidence FLOAT,
  experience_years FLOAT,
  education VARCHAR(255),
  source VARCHAR(32),
  status VARCHAR(16) DEFAULT 'sourced',
  cv_storage_path TEXT NOT NULL,
  cv_text_redacted TEXT,                    -- name/email/phone stripped, used for scoring
  rejection_reason VARCHAR(32) NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_candidates_job ON candidates(job_id);
CREATE INDEX ix_candidates_status ON candidates(status);
CREATE INDEX ix_candidates_score ON candidates(score DESC);
CREATE UNIQUE INDEX ux_candidates_email_job ON candidates(email_hash, job_id);

candidate_skills (
  id UUID PK,
  candidate_id UUID FK -> candidates.id ON DELETE CASCADE,
  skill VARCHAR(64),
  source VARCHAR(16),                       -- 'extracted' | 'manual'
  matched BOOLEAN DEFAULT FALSE,
  confidence FLOAT
);
CREATE INDEX ix_candidate_skills_cand ON candidate_skills(candidate_id);

candidate_bias_panel (
  candidate_id UUID PK FK -> candidates.id ON DELETE CASCADE,
  predicted_gender VARCHAR(8),
  predicted_gender_conf FLOAT,
  predicted_age_band VARCHAR(8),
  school_tier_estimate VARCHAR(8),
  fairness_diff_pct FLOAT,
  auto_action_blocked BOOLEAN,
  redacted_attributes JSONB,
  computed_at TIMESTAMPTZ
);

pipeline_history (
  id UUID PK,
  candidate_id UUID FK -> candidates.id ON DELETE CASCADE,
  from_stage VARCHAR(16),
  to_stage VARCHAR(16),
  actor_id UUID,
  note TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_pipeline_history_cand ON pipeline_history(candidate_id, created_at DESC);

scoring_config (
  id UUID PK,
  org_id UUID,                              -- single-tenant for now; future-proof
  weights JSONB,                            -- {skills:40, experience:25, ...}
  bias_flags JSONB,                         -- {redact_gender:true, ...}
  active BOOLEAN DEFAULT TRUE,
  updated_by UUID,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Retention**: candidate CVs 2 years post-decision (rejection or hire), then anonymized. PII columns 1 year. Aggregate analytics indefinitely. Pipeline history indefinitely (audit).

## ML Pipeline
- **CV parsing**: PyPDF + python-docx → plain text. PaddleOCR fallback for scanned PDFs.
- **PII redaction**: regex (Indian phone, email, Aadhaar pattern) + spaCy NER for names → produce `cv_text_redacted` used for downstream scoring.
- **Skill extraction**: custom skill taxonomy (~2000 tech + civic skills) + spaCy `EntityRuler` + LLM fallback for novel terms.
- **Embeddings**: `sentence-transformers/BGE-base-en-v1.5` (768-dim) for both JD and CV.
- **Match score**: cosine similarity (BGE) × 0.6 + TF-IDF keyword overlap × 0.3 + skill set Jaccard × 0.1, then rescaled to 0..100 with weighted dimension overlay (skills/exp/edu/loc/culture from `scoring_config`).
- **Bias panel**: `fairlearn` MetricFrame across predicted gender/age band → fairness diff. Predicted attributes from name/photo never feed the score; surfaced only for review.
- **Auto-shortlist threshold**: ≥0.85 (per `ml-conventions.md`); below → routes to "screened" for human review; auto-action blocked if any predicted-attribute confidence > 0.85.

**Latency budget**: <500ms per CV (single). Bulk path: 100 CVs in ≤30s amortized via batch embeddings.
**Confidence threshold for auto-action**: ≥0.85 advance, ≥0.92 auto-shortlist suggestion.

## Background jobs
- `parse_resume(cv_id)` — PDF→text→redact→extract skills→embed→score. Triggered on upload.
- `score_against_job(cv_id, job_id)` — re-score when JD changes or weights change.
- `bulk_parse(batch_id)` — fan out per CV, aggregate.
- `recompute_bias_panel(cv_id)` — runs after parsing, before scoring.
- `purge_anonymize_old_candidates()` — daily, 2-year retention rule.

## Real-time
None for v1. Polling job status is fine. Future: WebSocket push for "new candidate scored" notifications.

## Frontend mock cross-reference
- Search `pages.jsx` for `ResumeScreening` component (line 426).
- Sub-components: `ResumeJobs`, `ResumePipeline`, `ResumeCandidates`, `CandidateDetail`, `ResumeAnalytics`, `ResumeSettings`.
- Inline mock arrays to extract: `MOCK_JOBS` (in `ResumeJobs`), `MOCK_PIPELINE_CARDS` and `MOCK_PIPELINE_COLUMNS` (in `ResumePipeline`), `MOCK_CANDIDATES` (in `ResumeCandidates`), `MOCK_FUNNEL`, `MOCK_SOURCES`, `MOCK_DIVERSITY` (in `ResumeAnalytics`), `MOCK_WEIGHTS_DEFAULT`, `MOCK_BIAS_FLAGS_DEFAULT` (in `ResumeSettings`).

## Non-functional
- p50 single-CV upload-to-score: <2s
- p95 bulk batch (100 CVs): <60s
- p95 list/search latency: <300ms
- Throughput: 50 concurrent uploads
- Availability: 99.5% (gov SLA)
- Bias audit log: every score includes hash of weights+flags config used → reproducible

## Open questions for user
- [ ] Are candidate emails / phones to be retrieved from the CV automatically, or also entered manually by the recruiter? (Affects PII handling path.)
- [ ] What rejection reason codes are required by gov HR policy? Current sketch is generic — may need dept-specific codes.
- [ ] For bias panel, is showing the predicted gender/age to officers acceptable, or must it stay aggregate-only? (Some jurisdictions disallow per-candidate disclosure.)
- [ ] Confirm storage residency: are candidate CVs allowed in cloud (S3 ap-south-1) or must they stay on-prem?
