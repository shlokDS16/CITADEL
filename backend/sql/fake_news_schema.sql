-- =====================================================================
-- CITADEL · Citizen Module 2 — Fake News Detector
-- Supabase / Postgres schema. Run this whole file once in the Supabase
-- SQL editor (Dashboard → SQL → New query → paste → Run).
--
-- Safe to re-run: every statement is IF NOT EXISTS / idempotent.
-- Backend uses the service-role client (app.database.get_supabase()),
-- so RLS stays permissive for service_role; auth is enforced in FastAPI.
-- Tables degrade gracefully if absent — the module still analyzes,
-- it just can't persist/queue until these exist.
--
-- Contract base: docs/module-specs/06-fake-news-detector.md (spec tables)
-- + production extension tables (fn_*).
-- =====================================================================

-- gen_random_uuid()
create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- SPEC-06 TABLES
-- ---------------------------------------------------------------------

-- Every analysis (text / url / image / video). Raw input is NOT stored
-- (only an excerpt + a hash) per data-handling.md.
create table if not exists analyses (
  id                  uuid primary key default gen_random_uuid(),
  requester_id        text,
  requester_role      varchar(16) default 'citizen',   -- citizen|gov_analyst|gov_admin
  mode                varchar(8),                       -- TEXT|URL|IMAGE|VIDEO
  input_text_hash     char(64),                         -- sha256 for de-dup
  input_simhash       bigint,                           -- near-dup (L1)
  input_url           text,
  input_media_path    text,
  input_excerpt       varchar(500),
  verdict             varchar(16),                      -- REAL|LIKELY_REAL|UNCERTAIN|LIKELY_FAKE|FAKE
  confidence          double precision,                 -- 0..1
  risk_score          double precision,                 -- 0..1 aggregate
  layers              jsonb,                            -- per-layer raw output (heuristics/classifier/nli/llm/forensics)
  claims              jsonb,                            -- list[ClaimAnalysis]
  source_credibility  jsonb,
  bias_profile        jsonb,
  sentiment           jsonb,
  manipulation        jsonb,
  red_flags           jsonb,
  related_fact_checks jsonb,
  reasoning           jsonb,                            -- LLM reasoning trace (list[str])
  model_versions      jsonb,
  response_time_ms    integer,
  needs_review        boolean default false,            -- HITL gate
  submitted_at        timestamptz default now(),
  completed_at        timestamptz,
  reported_to_pib     boolean default false,
  reported_at         timestamptz,
  deleted_at          timestamptz
);
create index if not exists ix_analyses_requester on analyses (requester_id, submitted_at desc);
create index if not exists ix_analyses_verdict   on analyses (verdict);
create index if not exists ix_analyses_hash      on analyses (input_text_hash);

create table if not exists claim_analyses (
  id                    uuid primary key default gen_random_uuid(),
  analysis_id           uuid references analyses(id) on delete cascade,
  claim_text            text,
  verdict               varchar(16),                    -- TRUE|FALSE|UNVERIFIED|SUSPICIOUS|MISLEADING
  confidence            double precision,
  notes                 text,
  nli_label             varchar(16),                    -- entailment|contradiction|neutral
  supporting_evidence   jsonb,                          -- list[Source]
  contradicting_evidence jsonb,
  created_at            timestamptz default now()
);
create index if not exists ix_claims_analysis on claim_analyses (analysis_id);

-- Editable like govt_fines_penalties — Phase 3 seeds it from MBFC/AllSides
-- public lists + the PIB/Boom/AltNews/Vishvas allowlist.
create table if not exists source_credibility_db (
  domain         varchar(255) primary key,
  publisher_name varchar(255),
  trust_rating   varchar(8),                             -- LOW|MEDIUM|HIGH
  in_allowlist   boolean default false,
  in_blocklist   boolean default false,
  score          integer,                                -- 0..100
  bias_lean      varchar(8),                             -- left|center|right
  notes          text,
  reviewed_at    timestamptz default now(),
  reviewed_by    text
);
create index if not exists ix_creddb_trust on source_credibility_db (trust_rating);

-- Fact-check feed cache (refreshed every <=6h by a background loop).
create table if not exists fact_check_feed (
  id           uuid primary key default gen_random_uuid(),
  publisher    varchar(64),                               -- PIB|BoomLive|AltNews|Factly|Google
  url          text,
  title        text,
  body_excerpt text,
  claim_norm   text,                                      -- normalized claim text for matching
  published_at timestamptz,
  fetched_at   timestamptz default now()
);
create index if not exists ix_factcheck_published on fact_check_feed (published_at desc);
create index if not exists ix_factcheck_publisher on fact_check_feed (publisher);
create unique index if not exists ux_factcheck_url on fact_check_feed (url);

create table if not exists learn_content (
  key        varchar(64) primary key,                     -- red_flags|trusted_sources|verification_guide|techniques
  body_json  jsonb,
  updated_at timestamptz default now()
);

-- ---------------------------------------------------------------------
-- PRODUCTION EXTENSION TABLES (fn_*)
-- ---------------------------------------------------------------------

-- L1 known-debunked store: exact (sha256) + near-dup (simhash) match.
create table if not exists fn_debunked (
  id               uuid primary key default gen_random_uuid(),
  content_sha256   char(64),
  simhash          bigint,
  claim_text       text,
  canonical_verdict varchar(16) default 'FAKE',
  source_url       text,
  added_by         text,
  created_at       timestamptz default now()
);
create index if not exists ix_debunked_sha on fn_debunked (content_sha256);
create index if not exists ix_debunked_simhash on fn_debunked (simhash);

-- HITL review queue (confidence < FN_AUTO_VERDICT_CONFIDENCE).
create table if not exists fn_review_queue (
  id            uuid primary key default gen_random_uuid(),
  analysis_id   uuid references analyses(id) on delete cascade,
  reason        text,
  status        varchar(16) default 'pending',            -- pending|in_review|resolved
  model_verdict varchar(16),
  human_verdict varchar(16),
  assigned_to   text,
  notes         text,
  created_at    timestamptz default now(),
  decided_at    timestamptz
);
create index if not exists ix_reviewq_status on fn_review_queue (status, created_at desc);

-- Reviewer ground-truth → retrain export + meta-classifier refit.
create table if not exists fn_feedback (
  id          uuid primary key default gen_random_uuid(),
  analysis_id uuid references analyses(id) on delete set null,
  human_verdict varchar(16),
  model_verdict varchar(16),
  correct     boolean,
  layer_scores jsonb,                                      -- feature vector for meta-classifier
  notes       text,
  reviewer    text,
  created_at  timestamptz default now()
);
create index if not exists ix_feedback_created on fn_feedback (created_at desc);

-- Concept-drift snapshots (Jensen-Shannon divergence vs reference window).
create table if not exists fn_drift_snapshots (
  id            uuid primary key default gen_random_uuid(),
  window_start  timestamptz,
  window_end    timestamptz,
  js_divergence jsonb,                                     -- per-feature JS values
  drifted       boolean default false,
  n_samples     integer,
  created_at    timestamptz default now()
);
create index if not exists ix_drift_created on fn_drift_snapshots (created_at desc);

-- Refittable logistic meta-classifier weights over layer scores.
create table if not exists fn_meta_weights (
  id         uuid primary key default gen_random_uuid(),
  weights    jsonb,
  n_samples  integer,
  metrics    jsonb,
  trained_at timestamptz default now()
);

-- CIB / propagation analysis runs (user-uploaded share-graph).
create table if not exists fn_propagation_runs (
  id            uuid primary key default gen_random_uuid(),
  requester_id  text,
  source_name   text,
  n_nodes       integer,
  n_edges       integer,
  burst_score   double precision,
  coordination_score double precision,
  bot_likeness_score double precision,
  cib_verdict   varchar(16),                               -- ORGANIC|SUSPICIOUS|COORDINATED
  clusters      jsonb,
  metrics       jsonb,
  created_at    timestamptz default now()
);
create index if not exists ix_prop_created on fn_propagation_runs (created_at desc);

-- =====================================================================
-- DONE. Expected: 11 tables created.
-- Quick check:
--   select table_name from information_schema.tables
--   where table_schema='public'
--     and (table_name in ('analyses','claim_analyses','source_credibility_db',
--          'fact_check_feed','learn_content') or table_name like 'fn_%')
--   order by table_name;
-- =====================================================================
