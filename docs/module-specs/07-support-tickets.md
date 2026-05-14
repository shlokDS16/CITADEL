# Module Spec — 07 · Support Tickets

> Frontend (citizen surface): `SupportTickets` in `pages.jsx`. Tabs: Submit New · My Tickets · Community · Map View.
> Frontend (gov surface): same backend, separate UI screens (Inbox · Triage · Assigned · Reports) — to be built later in this module.
> Backend: `backend/app/modules/tickets/`. Prefix: `/api/v1/tickets`.
> Audience: citizens (`citizen` — submit, follow up, upvote others) AND gov officers (`gov_officer` per-department, `gov_admin` city-wide).

## Outcome
Citizen reports a civic issue (pothole, water outage, streetlight, garbage, stray animals, parks, etc.) with subject + description + multi-modal attachments (photo, video, voice, GPS, file). The system runs DistilBERT zero-shot classification to predict category + priority + routing department, runs VADER for sentiment (urgency cue), and shows the citizen a pre-analysis card before they submit. On submit, ticket is queued in the routed department's inbox. Department officer triages, assigns to a crew, posts updates, marks resolved. Citizen sees a status timeline + can comment, rate, or reopen. Community tab shows trending tickets in their area; upvotes ("supports") raise priority. Map view shows nearby issues. Anonymous submission is supported (whistleblower mode).

## Personas & permissions
- `citizen`: submit ticket (named or anonymous), view own + community tickets, upvote, comment, rate
- `gov_officer` (per dept): see assigned-to-dept inbox, triage, assign, update status, mark resolved
- `gov_officer` (lead): bulk-assign within dept, escalate to other dept
- `gov_admin`: cross-dept reports, SLA config, dept routing rules

## Endpoints

### Citizen — Submit & Mine
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/tickets` | `tickets:submit` | Create ticket (multipart for attachments) → 201 + TicketOut |
| `POST` | `/tickets/preview` | `tickets:submit` | Run AI pre-analysis without submitting (returns predicted cat/priority/dept/SLA) |
| `GET` | `/tickets/mine` | `tickets:read-own` | Citizen's own tickets, filter `?status=&cat=` |
| `GET` | `/tickets/{ticket_id}` | `tickets:read` | Detail (citizen sees if owner or anonymous-submitter; gov sees if same dept) |
| `POST` | `/tickets/{ticket_id}/updates` | `tickets:write` | Add update (citizen comment or gov status note) |
| `POST` | `/tickets/{ticket_id}/rate` | `tickets:write` | Citizen rates resolution 1–5 + optional comment |
| `POST` | `/tickets/{ticket_id}/reopen` | `tickets:write` | Citizen reopens a resolved ticket within 14 days |
| `GET` | `/tickets/{ticket_id}/attachments/{att_id}` | `tickets:read` | Pre-signed attachment download (5min TTL) |

### Templates
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/templates` | public | Quick-start templates (Pothole, Water Outage, Streetlight, etc.) |

### Community
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/community` | `tickets:read` | Public tickets, sort `?sort=trending,new,nearby,unresolved` |
| `POST` | `/tickets/{ticket_id}/upvote` | `tickets:write` | Citizen upvotes (idempotent per user) |
| `DELETE` | `/tickets/{ticket_id}/upvote` | `tickets:write` | Remove upvote |
| `POST` | `/tickets/{ticket_id}/comments` | `tickets:write` | Public comment on community ticket |
| `GET` | `/tickets/{ticket_id}/comments` | `tickets:read` | Comment thread |

### Map
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/map/nearby` | `tickets:read` | Nearby tickets `?lat=&lng=&radius_km=5` |

### Gov — Inbox & Triage
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/gov/inbox` | `tickets:gov-read` | Officer's dept inbox, filter `?priority=&unassigned=true` |
| `POST` | `/tickets/{ticket_id}/assign` | `tickets:gov-write` | Assign to a crew/officer within dept |
| `POST` | `/tickets/{ticket_id}/reroute` | `tickets:gov-write` | Reroute to another department |
| `POST` | `/tickets/{ticket_id}/status` | `tickets:gov-write` | Set status (open → assigned → in_progress → verification → resolved) |
| `POST` | `/tickets/bulk-assign` | `tickets:gov-write` | Assign multiple tickets in one go |

### Gov — Reports
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/gov/reports/sla` | `tickets:gov-read` | SLA performance per dept |
| `GET` | `/gov/reports/volume` | `tickets:gov-read` | Volume by dept × category × time |
| `GET` | `/gov/reports/sentiment` | `tickets:gov-read` | Citizen sentiment trend (from rating + comments) |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + classifier load + queue depth per dept |

### Real-time channels
| Channel | Purpose | Message types |
|---|---|---|
| `/ws/tickets/inbox` | Gov officer inbox push | `ticket_created`, `ticket_assigned`, `ticket_updated`, `priority_change` |
| `/ws/tickets/{ticket_id}/updates` | Live update stream for a ticket detail page | `update_added`, `status_changed`, `upvote` |

## Schemas (key shapes)

### Ticket
```python
class TicketOut(BaseModel):
    id: str                                   # "TKT-1024"
    subject: str
    description: str                          # HTML-stripped, length-capped
    category: Literal["Roads","Water","Electric","Sanitation","Public_Safety","Parks","Health","Drainage","Traffic","Planning","Other"]
    priority: Literal["LOW","NORMAL","HIGH","CRITICAL"]
    priority_was_auto: bool                   # true if AI assigned
    status: Literal["open","assigned","in_progress","verification","resolved","closed","reopened"]
    department: Literal["PWD","Water_Board","Electricity_Board","Sanitation","Police","Parks","Health","Drainage","Traffic","Planning"]
    submitted_by: UUID | None                 # null if anonymous
    is_anonymous: bool
    geo: GeoPoint | None                      # if GPS attached
    location_label: str | None
    upvotes: int                              # supports count
    age: str                                  # human ("2d", "3h")
    created_at: datetime
    assigned_at: datetime | None
    resolved_at: datetime | None
    sla_due_at: datetime
    sla_status: Literal["on_track","at_risk","breached"]
    rating: int | None                        # citizen rating 1..5
    attachments: list[AttachmentOut]
    sentiment: Literal["positive","neutral","negative"] | None
```

### Attachment
```python
class AttachmentOut(BaseModel):
    id: UUID
    type: Literal["photo","video","voice","location","file"]
    name: str                                 # original filename or label
    size_bytes: int
    mime_type: str
    download_url: str | None                  # pre-signed, 5min TTL
    transcript: str | None                    # voice → text via Whisper
```

### Submit (multipart)
```python
class TicketCreateIn(BaseModel):
    subject: str = Field(..., max_length=200)
    description: str = Field(..., max_length=4000)
    category: str | None = None               # "Auto-detect" → AI predicts
    priority: Literal["AUTO","LOW","NORMAL","HIGH","CRITICAL"] = "AUTO"
    is_anonymous: bool = False
    geo_lat: float | None = None
    geo_lng: float | None = None
    # Files come via multipart 'attachments[]'
```

### AI pre-analysis (preview)
```python
class TicketPreviewOut(BaseModel):
    predicted_category: str
    predicted_priority: str
    predicted_department: str
    predicted_sla_label: str                  # "4 hours", "48 hours"
    predicted_sla_due_at: datetime
    sentiment: Literal["positive","neutral","negative"]
    confidence: float                         # 0..1 composite
    reasoning_summary: str                    # 1-line: "Public safety + urgency cues → Police HIGH"
```

### Update / comment
```python
class TicketUpdateIn(BaseModel):
    text: str = Field(..., max_length=2000)
    visibility: Literal["public","internal"] = "public"

class TicketUpdateOut(BaseModel):
    id: UUID
    ticket_id: str
    actor_id: UUID
    actor_label: str                          # "PWD Team", "You"
    actor_role: Literal["citizen","gov_officer","gov_admin","system"]
    text: str
    visibility: Literal["public","internal"]
    created_at: datetime
```

### Community card
```python
class CommunityTicketOut(BaseModel):
    id: str
    title: str
    location_label: str
    category: str
    upvotes: int
    response_count: int
    age: str
    severity: Literal["LOW","MEDIUM","HIGH","CRITICAL"]
```

## Data model
```sql
tickets (
  id VARCHAR(16) PK,                          -- "TKT-1024"
  subject VARCHAR(255),
  description TEXT,                           -- HTML-stripped on insert
  category VARCHAR(32),
  priority VARCHAR(8),
  priority_was_auto BOOLEAN DEFAULT TRUE,
  status VARCHAR(16) DEFAULT 'open',
  department VARCHAR(32),
  submitted_by UUID NULL,                     -- null for anonymous
  is_anonymous BOOLEAN DEFAULT FALSE,
  geo GEOGRAPHY(POINT, 4326) NULL,
  location_label VARCHAR(255) NULL,
  upvotes INT DEFAULT 0,
  sentiment VARCHAR(8) NULL,                  -- positive/neutral/negative
  ai_classification JSONB,                    -- {predicted_cat, conf, reasoning}
  rating INT NULL,                            -- 1..5
  rating_comment TEXT NULL,
  sla_due_at TIMESTAMPTZ NOT NULL,
  sla_status VARCHAR(16) DEFAULT 'on_track',
  assigned_at TIMESTAMPTZ NULL,
  assigned_to_id UUID NULL,
  resolved_at TIMESTAMPTZ NULL,
  closed_at TIMESTAMPTZ NULL,
  reopened_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_tickets_dept_status ON tickets(department, status);
CREATE INDEX ix_tickets_submitted_by ON tickets(submitted_by) WHERE submitted_by IS NOT NULL;
CREATE INDEX ix_tickets_created ON tickets(created_at DESC);
CREATE INDEX ix_tickets_geo ON tickets USING GIST(geo);
CREATE INDEX ix_tickets_upvotes ON tickets(upvotes DESC);

ticket_attachments (
  id UUID PK,
  ticket_id VARCHAR(16) FK -> tickets.id ON DELETE CASCADE,
  type VARCHAR(16),
  name VARCHAR(255),
  storage_path TEXT NOT NULL,
  mime_type VARCHAR(64),
  size_bytes BIGINT,
  transcript TEXT NULL,                       -- for voice
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_attachments_ticket ON ticket_attachments(ticket_id);

ticket_updates (
  id UUID PK,
  ticket_id VARCHAR(16) FK -> tickets.id ON DELETE CASCADE,
  actor_id UUID NULL,
  actor_label VARCHAR(128),
  actor_role VARCHAR(16),
  text TEXT,
  visibility VARCHAR(8) DEFAULT 'public',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_updates_ticket ON ticket_updates(ticket_id, created_at);

ticket_upvotes (
  ticket_id VARCHAR(16) FK -> tickets.id ON DELETE CASCADE,
  citizen_id UUID NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (ticket_id, citizen_id)
);

ticket_comments (
  id UUID PK,
  ticket_id VARCHAR(16) FK -> tickets.id ON DELETE CASCADE,
  citizen_id UUID NOT NULL,
  text TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_comments_ticket ON ticket_comments(ticket_id, created_at);

routing_rules (
  id UUID PK,
  category VARCHAR(32),
  keywords JSONB,                             -- ["pothole","road","damage"]
  department VARCHAR(32),
  default_priority VARCHAR(8),
  sla_hours INT,
  active BOOLEAN DEFAULT TRUE,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Retention**: tickets indefinite for gov audit (anonymized after 7 years if citizen-owned and account deleted); attachments 2 years; voice transcripts 30 days; comments 1 year.

## ML Pipeline
- **Classification**: `DistilBERT` zero-shot (`facebook/bart-large-mnli` as zero-shot fallback) over fixed category set (Roads / Water / Electric / Sanitation / Public Safety / Parks / Health / Drainage / Traffic / Planning / Other).
- **Priority prediction**: rule-based on (a) category default, (b) urgency keywords ("emergency", "child", "fire", "leak"), (c) sentiment intensity, (d) co-located ticket density.
- **Sentiment**: `vaderSentiment` for English; `IndicSentiment` for Hindi/regional.
- **Routing**: rule-based — `routing_rules` table maps (category, keyword match) → department + default priority + SLA. ML predicts category; rules pick dept.
- **PII strip before classification**: name/address/phone redacted from the input embedding to comply with `ml-conventions.md` "Ticket priority must not learn from sender name".
- **Voice attachment transcription**: `faster-whisper` (small/multilingual), 24h SLA, transcript stored next to attachment.
- **Image attachment moderation**: `nudenet` filter to reject obvious abuse content; OCR via PaddleOCR for legibility (e.g., "shop name in photo helps locate").
- **Duplicate / similar ticket detection**: BGE embedding + nearest-neighbor over last-30-day tickets in same zone → suggest "you may want to upvote TKT-XXXX instead".

**Latency budget**: <300ms per ticket classification per `ml-conventions.md`; preview endpoint must return in <500ms.

## Background jobs
- `classify_ticket(ticket_id)` — runs on submit; sync if <300ms.
- `transcribe_voice(att_id)` — async, on attachment.
- `moderate_image(att_id)` — async, on attachment; auto-reject obvious abuse.
- `find_duplicates(ticket_id)` — async; if found, append "see also" comment.
- `escalate_sla_breach()` — every 5 min; bumps priority + notifies dept lead.
- `recompute_community_trending()` — every 15 min, weighted by recent upvotes + comments.
- `notify_resolution(ticket_id)` — push/SMS to citizen.
- `purge_old_voice_transcripts()` — daily, 30-day retention.

## Real-time
- `/ws/tickets/inbox` — gov officer inbox push. Auth: JWT after connect, requires `tickets:gov-read`. Filter by dept derived from JWT.
- `/ws/tickets/{ticket_id}/updates` — live updates for the open ticket detail screen (citizen sees public, gov sees public+internal).

## Frontend mock cross-reference
- Search `pages.jsx` for `SupportTickets` component (line 1931).
- Sub-components: `TicketSubmit`, `TicketMine`, `TicketCommunity`, `TicketMap`.
- Inline mocks to extract: `MOCK_TEMPLATES` (in `TicketSubmit`), `MOCK_AI_PREVIEW` (synthesized in `useTemplate()`), `MOCK_MY_TICKETS` (in `TicketMine`), `MOCK_TICKET_UPDATES` (expanded card timeline), `MOCK_COMMUNITY_TICKETS` (in `TicketCommunity`), `MOCK_MAP_PINS` and `MOCK_NEARBY` (in `TicketMap`).
- Gov surface (Inbox / Triage / Assigned / Reports) is not yet built in `pages.jsx` — same backend, future UI.

## Non-functional
- p50 ticket-submit-to-classified: <500ms
- p95 list/inbox: <300ms
- p95 attachment upload (10MB): <3s
- WebSocket inbox push: <1s submit-to-officer
- Throughput: 100 ticket creates/min sustained, 500/min burst (mass-event scenarios like floods)
- SLA breach detection: ≤5 min after due time
- Availability: 99.5% (gov SLA)
- Citizen quota: 20 ticket creates/day per account; anonymous tickets rate-limited per IP

## Open questions for user
- [ ] Anonymous submissions — must we still capture an SMS/email handle for resolution notification, or strictly fire-and-forget?
- [ ] Department list — current sketch is municipal. Are state-level depts (RTO, Police HQ) in scope, or only ULB (urban local body)?
- [ ] Routing rules — auto-route on AI classification alone, or always require officer triage first?
- [ ] SLA matrix — is it (department × priority) only, or also (location_zone × time-of-day)?
- [ ] Community upvote → priority bump: how many upvotes to bump from NORMAL to HIGH? E.g., 50? 100? Per-area threshold?
