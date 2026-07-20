-- Phase 0.7 — make the audit logs append-only.
--
-- Both audit tables (public.audit_log, public.tv_audit_log) currently grant
-- the full DELETE/INSERT/REFERENCES/SELECT/TRIGGER/TRUNCATE/UPDATE set to
-- anon, authenticated AND service_role. The application connects through
-- PostgREST as service_role, so today the app could silently rewrite or
-- erase its own audit trail — which defeats the point of an audit trail and
-- fails the FOIA-grade requirement in .claude/rules/security-baseline.md.
--
-- Verified before writing this: no code path anywhere under backend/app
-- issues .update() or .delete() against either audit table. Both are
-- INSERT + SELECT only, so revoking mutation grants is behaviour-preserving.
--
-- service_role has BYPASSRLS but that bypasses row-level policies, NOT table
-- grants — so this REVOKE genuinely binds the application.
--
-- The postgres role owns both tables and keeps full rights. An owner can
-- always mutate its own tables; that is the intended escape hatch for a
-- legitimate, out-of-band retention purge, not an app-reachable path.
--
-- TRUNCATE is revoked alongside UPDATE/DELETE: it is a separate privilege
-- and leaving it would let the same roles wipe the table wholesale.

revoke update, delete, truncate on public.audit_log    from anon, authenticated, service_role;
revoke update, delete, truncate on public.tv_audit_log from anon, authenticated, service_role;

-- Keep future-me honest: if a later migration recreates these tables, the
-- default grants come back. Re-run this file after any such change.
comment on table public.audit_log is
  'Append-only. UPDATE/DELETE/TRUNCATE revoked from anon, authenticated, service_role (migration 20260720000004). INSERT + SELECT only.';
comment on table public.tv_audit_log is
  'Append-only. UPDATE/DELETE/TRUNCATE revoked from anon, authenticated, service_role (migration 20260720000004). INSERT + SELECT only.';
