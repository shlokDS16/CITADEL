-- Phase 0.4 — updated_at triggers.
--
-- SCOPE CORRECTION vs the original plan ("triggers for fake_news + traffic"):
-- a live-DB audit shows NO fn_* or tv_* table has an updated_at column at all
-- (12 such tables, zero with the column), so there is nothing there to trigger.
-- Adding the column to 12 tables no code reads would be dead weight.
--
-- The actual gap: 5 tables have updated_at, only 3 carry the trigger.
--   has trigger  : candidates, jobs, templates
--   MISSING      : govt_fines_penalties, learn_content
--
-- govt_fines_penalties is the live fine source of truth, edited through the
-- Traffic Settings fine editor (service.py:976). That UPDATE never sets
-- updated_at and no trigger fired, so the column has been frozen at insert
-- time since creation — every fine edit left a stale timestamp on a
-- governance-relevant record. This fixes that.
--
-- Reuses the existing public.trigger_set_updated_at() (NEW.updated_at = NOW()).

create trigger govt_fines_penalties_set_updated_at
  before update on public.govt_fines_penalties
  for each row execute function public.trigger_set_updated_at();

create trigger learn_content_set_updated_at
  before update on public.learn_content
  for each row execute function public.trigger_set_updated_at();
