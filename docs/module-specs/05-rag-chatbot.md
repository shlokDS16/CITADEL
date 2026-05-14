# Module Spec — 05 · RAG Chatbot

> Frontend: `RAGChatbot` in `pages.jsx`. Tabs: Assistant · Service Catalog · History.
> Backend: `backend/app/modules/chatbot/`. Prefix: `/api/v1/chatbot`.
> Audience: citizens (`citizen` role). Gov staff may use it as well, but RBAC scope is identical for v1.

## Outcome
A citizen-facing assistant that answers questions about Indian government services (Aadhaar, PAN, passport, voter ID, driving license, property tax, Ayushman Bharat, scholarships, pensions, MSME, etc.) by retrieving from a curated civic knowledge base (~247 articles initially) and generating responses with a local LLM (Ollama Llama-3.2-3B). Every answer cites its sources with relevance scores and a confidence value. Multilingual: English, Hindi, Tamil, Bengali, Marathi, Telugu. Supports voice input (beta), conversation history, quick action shortcuts, and a Service Catalog browse mode for users who'd rather click than type.

## Personas & permissions
- `citizen`: chat, browse services, view own history, give feedback
- `gov_admin` (out of scope for chat surface): manage knowledge base via separate admin tool (later module)

## Endpoints

### Chat
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/sessions` | `chatbot:write` | Start a new chat session, returns `session_id` |
| `GET` | `/sessions/{session_id}` | `chatbot:read` | Get session metadata + message list |
| `POST` | `/sessions/{session_id}/messages` | `chatbot:write` | Send message → 202 + message id; reply streamed via SSE/WS |
| `GET` | `/sessions/{session_id}/messages/{msg_id}` | `chatbot:read` | Get single message + sources + confidence |
| `POST` | `/sessions/{session_id}/messages/{msg_id}/feedback` | `chatbot:write` | Thumbs up/down + optional reason |
| `DELETE` | `/sessions/{session_id}` | `chatbot:write` | Delete session (citizen erasure right) |
| `POST` | `/sessions/{session_id}/voice` | `chatbot:write` | Multipart audio upload → transcribed + answered |

### Streaming reply (SSE)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/sessions/{session_id}/messages/{msg_id}/stream` | `chatbot:read` | Server-Sent Events: `token`, `source`, `done` events |

### Services catalog
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/services/categories` | `chatbot:read` | All categories (Identity, Tax, Health, Education, Business, Pension, Property, Utilities) |
| `GET` | `/services` | `chatbot:read` | Search/filter `?q=&category=` services |
| `GET` | `/services/{service_id}` | `chatbot:read` | Service detail (description, links, prerequisites) |

### Knowledge base (read-only for citizens)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/kb/articles/{article_id}` | `chatbot:read` | Cited article full text (referenced from sources in messages) |
| `GET` | `/kb/search` | `chatbot:read` | Direct KB search `?q=&lang=&top_k=5` (skips LLM) |

### History
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/history` | `chatbot:read` | Citizen's past sessions with title, msg count, date, helpful flag |
| `GET` | `/history/export` | `chatbot:read` | JSON export of all sessions (right-to-access) |
| `POST` | `/history/{session_id}/resume` | `chatbot:write` | Re-open prior session (returns session_id, hydrates context) |

### Languages
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/languages` | public | Supported languages (code + label) |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + Ollama status + KB index size |

## Schemas (key shapes)

### Session
```python
class SessionOut(BaseModel):
    id: UUID
    citizen_id: UUID                          # owner
    title: str                                # auto-generated from first user msg
    language: Literal["en","hi","ta","bn","mr","te"]
    message_count: int
    helpful: bool | None                       # null until rated
    created_at: datetime
    last_activity_at: datetime
```

### Message
```python
class MessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: Literal["user","bot"]
    text: str
    language: str
    sources: list[Source] | None              # only on bot messages
    suggestions: list[str] | None             # follow-up chips
    confidence: float | None                  # 0..1, only on bot
    model_version: str | None                 # "ollama-llama3.2:3b"
    response_time_ms: int | None
    feedback: Literal["helpful","not_helpful"] | None
    created_at: datetime
```

### Source citation
```python
class Source(BaseModel):
    article_id: UUID
    title: str                                # "gov-services-2026.pdf"
    section: str                              # "Section 3.2" or "Q4–Q7"
    relevance: float                          # 0..1
    snippet: str                              # short excerpt
```

### Send message
```python
class MessageIn(BaseModel):
    text: str = Field(..., max_length=2000)
    language: Literal["en","hi","ta","bn","mr","te"] = "en"
    voice_blob_id: UUID | None = None         # if voice input
```

### Service category
```python
class ServiceCategoryOut(BaseModel):
    id: str
    label: str                                # "Identity"
    icon: str                                 # emoji or asset key
    items: list[ServiceItemOut]

class ServiceItemOut(BaseModel):
    id: str
    label: str                                # "Aadhaar Enrollment"
    short_desc: str
    canonical_url: str | None                 # external gov portal
    related_kb_article_ids: list[UUID]
```

### SSE event payloads
```python
# event: token
{"text": "...partial..."}
# event: source
{"sources": [Source, ...]}
# event: done
{"message_id": "...", "confidence": 0.94, "response_time_ms": 1240}
```

## Data model
```sql
chat_sessions (
  id UUID PK,
  citizen_id UUID NOT NULL,
  title VARCHAR(255),
  language VARCHAR(8) DEFAULT 'en',
  helpful BOOLEAN NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_activity_at TIMESTAMPTZ DEFAULT NOW(),
  deleted_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_sessions_citizen ON chat_sessions(citizen_id, last_activity_at DESC);

chat_messages (
  id UUID PK,
  session_id UUID FK -> chat_sessions.id ON DELETE CASCADE,
  role VARCHAR(8),                            -- 'user' | 'bot'
  text TEXT,
  language VARCHAR(8),
  confidence FLOAT NULL,
  model_version VARCHAR(64) NULL,
  response_time_ms INT NULL,
  feedback VARCHAR(16) NULL,
  feedback_reason TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_messages_session ON chat_messages(session_id, created_at);

message_sources (
  id UUID PK,
  message_id UUID FK -> chat_messages.id ON DELETE CASCADE,
  article_id UUID FK -> kb_articles.id,
  section VARCHAR(64),
  relevance FLOAT,
  snippet TEXT
);
CREATE INDEX ix_sources_msg ON message_sources(message_id);

kb_articles (
  id UUID PK,
  title VARCHAR(255),
  slug VARCHAR(255) UNIQUE,
  category VARCHAR(32),
  language VARCHAR(8),
  body_md TEXT,
  source_url TEXT NULL,                       -- where original was scraped/imported
  version VARCHAR(16),
  embedding_model VARCHAR(64),                -- "BAAI/bge-base-en-v1.5"
  embedding_index_version VARCHAR(32),        -- e.g. "faiss-v3"
  published_at TIMESTAMPTZ,
  reviewed_by UUID NULL,
  reviewed_at TIMESTAMPTZ NULL,
  deprecated_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_kb_category ON kb_articles(category);
CREATE INDEX ix_kb_language ON kb_articles(language);

kb_chunks (
  id UUID PK,
  article_id UUID FK -> kb_articles.id ON DELETE CASCADE,
  chunk_index INT,
  text TEXT,
  text_hash CHAR(64),
  embedding_local_path TEXT NULL,             -- pointer into FAISS file (chunk position)
  token_count INT,
  section VARCHAR(64) NULL
);
CREATE INDEX ix_chunks_article ON kb_chunks(article_id);

services (
  id VARCHAR(64) PK,                          -- "aadhaar_enrollment"
  category VARCHAR(32),
  label VARCHAR(128),
  short_desc TEXT,
  canonical_url TEXT NULL,
  icon VARCHAR(8),
  related_kb_article_ids JSONB,
  active BOOLEAN DEFAULT TRUE,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_services_category ON services(category);
```

**Retention**: chat sessions/messages 1 year then anonymized (citizen PII rule); `kb_articles` indefinite (versioned); voice blobs 24h then purged after transcription.

## ML Pipeline
- **Embeddings**: `sentence-transformers/BGE-base-en-v1.5` for English; `BGE-m3` (multilingual) for hi/ta/bn/mr/te. Stored in FAISS local file (per `ml-conventions.md`); migrate to Qdrant when multi-tenant.
- **Retrieval**: top-k (default k=5) over FAISS; re-rank with cross-encoder `bge-reranker-base` to top 3.
- **LLM**: `Ollama` running `llama3.2:3b` locally; temperature 0.3; max_tokens 800; stop sequences include `</answer>`.
- **Prompt**: system prompt anchors persona ("CITADEL civic assistant — answer only from sources, cite by article+section, decline if not in KB"); injects retrieved chunks; output structured (answer + suggestions block).
- **Confidence**: synthesized from (a) retriever top-1 score, (b) LLM logprob avg, (c) chunk overlap to answer (rough heuristic). Below 0.6 → show "I'm not certain — check official portal" disclaimer.
- **Voice input**: `faster-whisper` (small/multilingual) for transcription; pipes into normal text path.
- **Translation**: detected non-English query → embed with multilingual model; reply in same language; for unsupported language, fall back to English with translation note.
- **Prompt-injection guard**: strip retrieved chunks of any text starting with "ignore previous instructions" patterns; sanitize bot output for echoed user prompts before display (per `security-baseline.md`).

**Latency budget**: <3s p50, <10s p99 per `ml-conventions.md`.
**Confidence threshold to surface answer without warning**: ≥0.60.

## Background jobs
- `embed_kb_article(article_id)` — re-embed when KB updated.
- `rebuild_faiss_index()` — full rebuild nightly; incremental adds during day.
- `transcribe_voice(blob_id)` — async if >5s audio; ≤5s runs in-request.
- `summarize_session_title(session_id)` — after first 2 turns, generate human title.
- `purge_old_sessions()` — daily, anonymize sessions >1 year.
- `purge_voice_blobs()` — daily, removes voice files >24h.

## Real-time
- SSE stream for token-by-token reply (no full WebSocket needed). Endpoint: `GET /sessions/{session_id}/messages/{msg_id}/stream`.
- Auth: standard JWT on initial GET (SSE supports headers).

## Frontend mock cross-reference
- Search `pages.jsx` for `RAGChatbot` component (line 1378).
- Sub-components: `ChatbotChat`, `ChatbotServices`, `ChatbotHistory`.
- Inline mocks to extract: `MOCK_INITIAL_BOT_MESSAGE` and `MOCK_BOT_REPLY` (in `ChatbotChat`), `MOCK_LANGUAGES` array, `MOCK_QUICK_ACTIONS` (sidebar buttons), `MOCK_SERVICES` (in `ChatbotServices`), `MOCK_HISTORY_SESSIONS` (in `ChatbotHistory`).

## Non-functional
- p50 reply latency: <3s end-to-end (incl. retrieval + LLM)
- p99 reply latency: <10s
- Streaming first-token: <800ms p95
- Throughput: 50 concurrent active sessions per node (Ollama 3B fits in single GPU)
- KB freshness: nightly index rebuild; manual force-rebuild via admin
- Availability: 99.0% (best-effort citizen surface)
- Citizen quota: 100 messages/day, 10 voice msgs/day (per `api-conventions.md` ML rate limits)

## Open questions for user
- [ ] Is the LLM allowed to call external APIs (e.g., live PAN status check from NSDL), or strictly KB-grounded only? Affects router design.
- [ ] What is the canonical KB ingestion path — manually curated by gov content team, scraped from gov portals, or both?
- [ ] For voice input, are we allowed to retain audio for QA/debug for 24h, or must it be deleted immediately after transcription?
- [ ] Confidence threshold (0.60) for surfacing without warning — is that acceptable, or should we be more conservative (0.75)?
