-- Phase 3.4 — close the direct PostgREST data surface.
--
-- Threat model: the anon key is effectively public (shipped to browsers
-- by design, and this project's key has additionally appeared in docs /
-- git history). Anyone holding it can query PostgREST directly,
-- bypassing the backend that Phase 3.3 just made the enforcement point.
--
-- Current posture was "safe-by-empty": RLS enabled on all 47 tables with
-- zero policies denies rows, but table GRANTS still let anon/
-- authenticated *execute* queries (silent [] responses) and enumerate
-- the entire schema through PostgREST's OpenAPI. Defense in depth says
-- the roles should hold no object privileges at all: attempts then fail
-- loudly with 42501 instead of succeeding emptily.
--
-- The app is unaffected: every backend call is the service_role client
-- (grants intact + BYPASSRLS), and app/database.py's get_supabase_anon
-- has zero callers (verified before this migration). Storage signed URLs
-- are token-based and independent of these grants.
--
-- Schema USAGE is deliberately kept: revoking it can break Supabase
-- internals (realtime, graphql introspection); with zero object grants,
-- USAGE alone exposes nothing.

revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;

-- Future-proof: Supabase's default privileges re-grant to these roles on
-- every NEW table. Strip that default so the next migration cannot
-- silently reopen the surface.
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;

comment on schema public is
  'Direct data-API access closed (migration 20260721000002): anon/authenticated hold no object privileges; the FastAPI backend (service_role) is the sole data path and enforcement point.';
