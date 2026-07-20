-- Phase 0.2 + 0.5 — FK delete actions and missing FK indexes.
--
-- Context: audited against the LIVE database (not the .sql files, which have
-- drifted from what is actually applied). Two concrete defects were found:
--
--   1. tv_incidents.cam_id referenced tv_cameras(id) with no ON DELETE action
--      (Postgres default NO ACTION = RESTRICT). This was not theoretical: it
--      blocked camera deletion in the Traffic module, and the service layer
--      had to manually NULL the referencing rows before deleting a camera to
--      work around it. Declaring ON DELETE SET NULL makes the database do what
--      the application was emulating by hand, and keeps incident evidence
--      (plate, violation, annotated frame) intact when a camera is retired.
--
--   2. Four foreign-key columns had no index. Postgres indexes the referenced
--      primary key, never the referencing column, so every join and every
--      cascade check on these was a sequential scan.
--
-- Both are non-breaking: no column types change, no rows are rewritten.
-- Idempotent — safe to re-run.

-- ---------------------------------------------------------------------------
-- 0.2  tv_incidents.cam_id -> tv_cameras(id)  ON DELETE SET NULL
-- ---------------------------------------------------------------------------
-- NOT VALID + VALIDATE splits the work: adding the constraint takes a brief
-- lock without scanning the table, then VALIDATE scans while holding only a
-- SHARE UPDATE EXCLUSIVE lock, so concurrent reads/writes keep running.
do $$
begin
  if exists (
    select 1 from pg_constraint
    where conrelid = 'tv_incidents'::regclass
      and contype  = 'f'
      and confrelid = 'tv_cameras'::regclass
      and confdeltype <> 'n'          -- 'n' = SET NULL; anything else needs fixing
  ) then
    alter table tv_incidents drop constraint tv_incidents_cam_id_fkey;

    alter table tv_incidents
      add constraint tv_incidents_cam_id_fkey
      foreign key (cam_id) references tv_cameras(id)
      on delete set null
      not valid;

    alter table tv_incidents validate constraint tv_incidents_cam_id_fkey;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 0.5  Missing foreign-key indexes
-- ---------------------------------------------------------------------------
-- CONCURRENTLY avoids the write-blocking lock a plain CREATE INDEX takes; it
-- cannot run inside a transaction block, which is why these sit outside the
-- DO block above and why this file must be applied with autocommit on.
create index concurrently if not exists ix_documents_template_id
  on documents (template_id);

create index concurrently if not exists ix_fn_feedback_analysis_id
  on fn_feedback (analysis_id);

create index concurrently if not exists ix_fn_review_queue_analysis_id
  on fn_review_queue (analysis_id);

create index concurrently if not exists ix_tv_challans_incident_id
  on tv_challans (incident_id);

-- Verification (expect 0 / 0):
--   FKs still NO ACTION:
--     select count(*) from pg_constraint c
--     join lateral unnest(c.conkey) k(attnum) on true
--     join pg_attribute a on a.attrelid=c.conrelid and a.attnum=k.attnum
--     where c.contype='f' and c.connamespace='public'::regnamespace
--       and c.confdeltype='a';
--   Unindexed FK columns:
--     select count(*) from pg_constraint c
--     join lateral unnest(c.conkey) k(attnum) on true
--     join pg_attribute a on a.attrelid=c.conrelid and a.attnum=k.attnum
--     where c.contype='f' and c.connamespace='public'::regnamespace
--       and not exists (select 1 from pg_index i
--                       where i.indrelid=c.conrelid
--                         and a.attnum = any(i.indkey::int[]));
