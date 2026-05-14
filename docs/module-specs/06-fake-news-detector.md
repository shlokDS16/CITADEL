# Module Spec — 06 · Fake News Detector

> Frontend: `FakeNewsDetector` in `pages.jsx`. Tabs: Analyze · Bulk Check · History · Learn.
> Backend: `backend/app/modules/fake_news/`. Prefix: `/api/v1/fake-news`.
> Audience: citizens (`citizen` — primary use case: WhatsApp-forward verification) AND gov officers (`gov_analyst` — election misinformation monitoring, PIB Fact Check workflow).

## Outcome
A user pastes article text, a URL, an image, or a video; the system extracts claims with DeBERTa-v3, scores each against an evidence corpus + cross-references known fact-check feeds, computes a publisher credibility score (domain age + WHOIS + known publisher allowlist/blocklist), profiles bias (left/center/right) and emotional manipulation, and returns a verdict (REAL / LIKELY FAKE / UNCERTAIN) with claim-by-claim breakdown and red flags. Bulk Check accepts up to 50 URLs at once. History tracks past checks. Learn is static educational content (red flags, trusted sources, 5-step verification guide).

## Personas & permissions
- `citizen`: analyze content, view own history, report to PIB
- `gov_analyst`: same as citizen + bulk check unlimited + access misinformation campaign dashboard (v2)
- `gov_admin` (v2): manage source credibility lists, manage manipulation rule weights

## Endpoints

### Analyze (single)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/analyze` | `fake-news:analyze` | Submit content for analysis → 202 + analysis id (sync if <2s) |
| `GET` | `/analyses/{analysis_id}` | `fake-news:read` | Full analysis result |
| `POST` | `/analyses/{analysis_id}/report` | `fake-news:write` | Forward to PIB Fact Check (logs intent + content hash) |
| `POST` | `/analyses/{analysis_id}/share` | `fake-news:read` | Generate shareable read-only link (signed token, 7-day TTL) |

### Bulk
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/bulk` | `fake-news:analyze` | Submit ≤50 URLs (or CSV upload) → batch_id |
| `GET` | `/bulk/{batch_id}` | `fake-news:read` | Batch status + per-URL verdicts |
| `POST` | `/bulk/upload-csv` | `fake-news:analyze` | Upload CSV with 1 URL/line |

### History
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/history` | `fake-news:read` | User's past checks with verdict, conf, date |
| `GET` | `/history/stats` | `fake-news:read` | KPIs: total checks, fake detected, real verified, reported to PIB |
| `DELETE` | `/history/{analysis_id}` | `fake-news:write` | Remove from own history (soft delete) |

### Learn (static content)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/learn/red-flags` | public | List of common red flags with descriptions |
| `GET` | `/learn/trusted-sources` | public | Allowlist of credible publishers (PIB, Boom, Alt News, Vishvas, etc.) |
| `GET` | `/learn/verification-guide` | public | 5-step guide content |

### Reference
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/sources/{domain}` | `fake-news:read` | Lookup credibility score for a domain |
| `GET` | `/related-fact-checks` | `fake-news:read` | Search fact-check feeds `?q=&from=` |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + DeBERTa load + fact-check feed freshness |

## Schemas (key shapes)

### Analysis request
```python
class AnalyzeIn(BaseModel):
    mode: Literal["TEXT","URL","IMAGE","VIDEO"]
    text: str | None = Field(None, max_length=20000)
    url: HttpUrl | None = None
    media_blob_id: UUID | None = None        # for image/video, uploaded separately
    options: AnalyzeOptions = AnalyzeOptions()

class AnalyzeOptions(BaseModel):
    source_credibility: bool = True
    claim_by_claim: bool = True
    bias_detection: bool = True
    deepfake_detection: bool = False         # only image/video
    cross_reference: bool = True             # search PIB / fact-check feeds
```

### Analysis result
```python
class AnalysisOut(BaseModel):
    id: UUID
    requester_id: UUID
    requester_role: Literal["citizen","gov_analyst","gov_admin"]
    submitted_at: datetime
    completed_at: datetime | None
    mode: str
    input_excerpt: str                        # first 200 chars for display
    verdict: Literal["REAL","LIKELY_REAL","UNCERTAIN","LIKELY_FAKE","FAKE"]
    confidence: float                         # 0..1
    claims: list[ClaimAnalysis]
    source_credibility: SourceCredibility | None
    bias_profile: BiasProfile | None
    sentiment: SentimentBreakdown | None
    red_flags: list[str]
    manipulation: ManipulationProfile | None
    related_fact_checks: list[RelatedFactCheck]
    model_version: str
    response_time_ms: int
```

### Claim
```python
class ClaimAnalysis(BaseModel):
    id: UUID
    text: str                                 # extracted claim sentence
    verdict: Literal["TRUE","FALSE","UNVERIFIED","SUSPICIOUS","MISLEADING"]
    confidence: float
    notes: str                                # reasoning summary
    supporting_evidence: list[Source]
    contradicting_evidence: list[Source]
```

### Source credibility
```python
class SourceCredibility(BaseModel):
    publisher: str                            # "unverified-news.info"
    publisher_known: bool                     # in allowlist/blocklist
    domain_age_days: int
    age_label: str                            # "Domain registered 14 days ago"
    score: int                                # 0..100
    trust_rating: Literal["LOW","MEDIUM","HIGH"]
    in_allowlist: bool
    in_blocklist: bool
```

### Bias / sentiment / manipulation
```python
class BiasProfile(BaseModel):
    left: int                                 # %
    center: int
    right: int
    confidence: float

class SentimentBreakdown(BaseModel):
    positive: int
    negative: int
    neutral: int

class ManipulationProfile(BaseModel):
    clickbait: int                            # 0..100
    urgency: int
    authority_claim: int
    emotional: int
```

### Related fact-check
```python
class RelatedFactCheck(BaseModel):
    title: str
    publisher: str                            # "PIB Fact Check"
    url: HttpUrl
    published_at: date
    matched_claim_ids: list[UUID]
```

### Bulk
```python
class BulkBatchOut(BaseModel):
    id: UUID
    submitted_at: datetime
    total: int
    completed: int
    items: list[BulkItem]

class BulkItem(BaseModel):
    url: HttpUrl
    verdict: Literal["REAL","LIKELY_FAKE","FAKE","UNCERTAIN","ERROR"]
    confidence: float
    analysis_id: UUID | None
    error: str | None
```

## Data model
```sql
analyses (
  id UUID PK,
  requester_id UUID NOT NULL,
  requester_role VARCHAR(16),
  mode VARCHAR(8),                            -- TEXT/URL/IMAGE/VIDEO
  input_text_hash CHAR(64),                   -- HMAC for de-dup; raw text in cold store
  input_url TEXT NULL,
  input_media_path TEXT NULL,
  input_excerpt VARCHAR(500),
  verdict VARCHAR(16),
  confidence FLOAT,
  source_credibility JSONB,
  bias_profile JSONB,
  sentiment JSONB,
  manipulation JSONB,
  red_flags JSONB,
  model_version VARCHAR(64),
  response_time_ms INT,
  submitted_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ NULL,
  reported_to_pib BOOLEAN DEFAULT FALSE,
  reported_at TIMESTAMPTZ NULL,
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_analyses_requester ON analyses(requester_id, submitted_at DESC);
CREATE INDEX ix_analyses_verdict ON analyses(verdict);
CREATE INDEX ix_analyses_url_hash ON analyses(input_text_hash);

claim_analyses (
  id UUID PK,
  analysis_id UUID FK -> analyses.id ON DELETE CASCADE,
  claim_text TEXT,
  verdict VARCHAR(16),
  confidence FLOAT,
  notes TEXT,
  supporting_evidence JSONB,                  -- list of Source
  contradicting_evidence JSONB
);
CREATE INDEX ix_claims_analysis ON claim_analyses(analysis_id);

source_credibility_db (
  domain VARCHAR(255) PK,
  publisher_name VARCHAR(255),
  trust_rating VARCHAR(8),                    -- LOW/MEDIUM/HIGH
  in_allowlist BOOLEAN DEFAULT FALSE,
  in_blocklist BOOLEAN DEFAULT FALSE,
  score INT,                                  -- 0..100
  bias_lean VARCHAR(8),                       -- left/center/right
  notes TEXT,
  reviewed_at TIMESTAMPTZ,
  reviewed_by UUID NULL
);
CREATE INDEX ix_creddb_trust ON source_credibility_db(trust_rating);

fact_check_feed (
  id UUID PK,
  publisher VARCHAR(64),                      -- 'PIB', 'BoomLive', 'AltNews', 'Vishvas'
  url TEXT,
  title TEXT,
  body_excerpt TEXT,
  embedding_local_path TEXT NULL,             -- FAISS pointer
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_factcheck_published ON fact_check_feed(published_at DESC);
CREATE INDEX ix_factcheck_publisher ON fact_check_feed(publisher);

learn_content (
  key VARCHAR(64) PK,                         -- 'red_flags', 'trusted_sources', 'verification_guide'
  body_json JSONB,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Retention**: analyses 1 year for citizens (then anonymize; keep verdict + hashes for stats), 7 years for gov_analyst path; raw uploaded media 30 days; fact-check feed indefinite (versioned).

## ML Pipeline
- **Claim extraction**: `DeBERTa-v3-base` fine-tuned for claim detection (sentence-level binary: claim vs non-claim).
- **Claim verification**: ensemble of:
  - `DeBERTa-v3-large-mnli` for textual entailment against retrieved evidence chunks.
  - Cross-reference search over `fact_check_feed` via FAISS embeddings (BGE-base).
  - Rule-based pattern matcher for known hoax templates (regex'd against historical false claims).
- **Source credibility heuristic**:
  - Allowlist (PIB, BoomLive, Alt News, Vishvas News, The Wire FactCheck) → score boost +30.
  - Blocklist (known disinfo domains) → cap at 20.
  - Domain age (<30 days → penalty -20).
  - TLD weights (.gov.in → +20; .info on suspect domains → -10).
  - WHOIS privacy proxy / no contact info → -10.
- **Bias profile**: `political-bias-classifier` fine-tuned on Indian news corpus (left/center/right).
- **Sentiment**: stdlib `vader` + custom Hindi/regional lexicon.
- **Manipulation detector**: keyword + structural rules (ALL CAPS density, exclamation count, urgency phrases, emotional polarity, named-authority-without-quote).
- **Deepfake detection** (image/video): `EfficientNet-B0` trained on FaceForensics++ / DFDC; flag-only, not in primary verdict for v1.
- **Verdict aggregation**: weighted vote (claim verdicts 0.5, source cred 0.2, manipulation 0.15, bias asymmetry 0.05, fact-check overlap 0.10).

**Latency budget**: <1.5s per claim per `ml-conventions.md`; full analysis (5 claims) target <5s sync; deepfake adds 5–10s → async.
**Confidence threshold to show verdict without warning**: ≥0.80 (per `ml-conventions.md`).

## Background jobs
- `analyze_async(analysis_id)` — for video/long content (>5 claims).
- `bulk_run(batch_id)` — fan out to per-URL analyses.
- `refresh_fact_check_feeds()` — every 6 hours, pull from PIB/Boom/Alt News/Vishvas RSS.
- `recompute_source_credibility()` — daily, refresh WHOIS + domain age.
- `report_to_pib(analysis_id)` — async, posts to PIB Fact Check submission API.
- `purge_old_analyses()` — daily, retention rules.

## Real-time
None for v1. Streaming the verdict as it's computed is nice-to-have v2.

## Frontend mock cross-reference
- Search `pages.jsx` for `FakeNewsDetector` component (line 1612).
- Sub-components: `FakeNewsAnalyze`, `FakeNewsBulk`, `FakeNewsHistory`, `FakeNewsLearn`.
- Inline mocks to extract: `MOCK_ANALYSIS_RESULT` (the synthetic result inside `verify()` in `FakeNewsAnalyze`), `MOCK_BULK_URLS` and `MOCK_BULK_RESULTS` (in `FakeNewsBulk`), `MOCK_HISTORY` (in `FakeNewsHistory`), `MOCK_RED_FLAGS`, `MOCK_TRUSTED_SOURCES`, `MOCK_VERIFY_STEPS` (in `FakeNewsLearn`).

## Non-functional
- p50 single text analysis: <3s
- p95 single text analysis: <8s
- Bulk 50 URLs: <2 min
- Throughput: 30 concurrent analyses per node
- Fact-check feed freshness: ≤6h
- Availability: 99.0% citizen / 99.5% gov_analyst
- Rate limits: citizen 20 analyses/day, gov_analyst 1000/day (per `api-conventions.md` ML limits)

## Open questions for user
- [ ] PIB Fact Check submission API — is there an official endpoint, or do we email/web-form their team?
- [ ] Source credibility allowlist/blocklist — who curates? Static seed list now, but who maintains it long-term?
- [ ] Election-misinformation monitoring (gov path) — is there a separate dashboard / alerting flow needed, or is the same `/analyses` surface enough?
- [ ] Are we OK with bias/lean classification, given political sensitivity? Some teams prefer to surface only "credibility" without left/right scoring.
