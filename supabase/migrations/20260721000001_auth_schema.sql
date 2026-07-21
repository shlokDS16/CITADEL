-- Phase 3.1 — real authentication schema.
--
-- users grows login columns (username/password_hash/role/lockout). The
-- existing passport_key_hash column is document_intelligence's template
-- lock — unrelated to login, untouched.
--
-- Password hashes are argon2id, computed app-side (argon2 has no Postgres
-- extension; pgcrypto only offers bcrypt, which security-baseline.md
-- forbids for new code) — the seed step that accompanies this migration
-- writes them.
--
-- refresh_tokens stores HASHES only (sha256), rotating: each refresh
-- revokes the old row and links its replacement, so a stolen-and-reused
-- old token is detectable (reuse of a revoked token → revoke the whole
-- chain).
--
-- Auth events audit into the existing append-only audit_log
-- (document_id is nullable there; UPDATE/DELETE already revoked in 0.7).

alter table public.users add column if not exists username      varchar(64) null;
alter table public.users add column if not exists password_hash text        null;
alter table public.users add column if not exists role          varchar(16) null;
alter table public.users add column if not exists is_active     boolean     not null default true;
alter table public.users add column if not exists failed_attempts integer   not null default 0;
alter table public.users add column if not exists locked_until  timestamptz null;
alter table public.users add column if not exists last_login_at timestamptz null;

create unique index if not exists ux_users_username on public.users(lower(username)) where username is not null;

alter table public.users drop constraint if exists users_role_check;
alter table public.users add constraint users_role_check
  check (role is null or role in ('gov_admin','gov_officer','gov_analyst','citizen'));

create table if not exists public.refresh_tokens (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users(id) on delete cascade,
  token_hash   text not null unique,
  issued_at    timestamptz not null default now(),
  expires_at   timestamptz not null,
  revoked_at   timestamptz null,
  replaced_by  uuid null references public.refresh_tokens(id) on delete set null,
  user_agent   varchar(255) null
);
create index if not exists ix_refresh_tokens_user on public.refresh_tokens(user_id, issued_at desc);

-- RLS posture consistent with the rest of the schema: enabled, zero
-- policies (deny-by-default for anon/authenticated; app path is
-- service_role via the backend, which is the enforcement point).
alter table public.refresh_tokens enable row level security;
revoke update, delete, truncate on public.refresh_tokens from anon, authenticated;

comment on table public.refresh_tokens is
  'Rotating refresh tokens, sha256-hashed. Raw tokens never stored. Reuse of a revoked token revokes the whole chain.';
