# Rule: Security Baseline

> Enforced by `security-auditor` agent on every code review. Non-negotiable for gov-side modules.

## Authentication
- **JWT** (HS256 in dev, RS256 in prod). Two issuers: `citadel-gov` and `citadel-citizen`.
- Access tokens: 30 min lifetime. Refresh tokens: 14 days, rotating, stored hashed in DB.
- Passwords: `argon2id` only. Never `bcrypt` for new code (still acceptable to read legacy hashes).
- MFA required for all government accounts. TOTP via `pyotp`. Backup codes one-time-use.
- Session revocation: refresh token table supports `revoked_at`. Logout revokes the current refresh chain.

## Authorization (RBAC)
- Roles: `gov_admin`, `gov_officer`, `gov_analyst`, `citizen`. Plus per-module scopes (e.g. `doc-intel:approve`, `traffic:issue-challan`).
- All endpoints declare required role / scope via dependency: `Depends(require_scope("doc-intel:approve"))`.
- Citizen JWT cannot access any `/api/v1/<gov-module>/*` route. Server-side check, not client-side.
- Officer can only see records assigned to them or their division. Service-layer filter (not just hide in UI).

## Input validation
- All request bodies through Pydantic — never accept raw `dict`.
- File uploads validated for: extension allowlist, mime sniff (`python-magic`), max size (configurable, default 10MB), virus scan hook (ClamAV in prod, no-op in dev).
- Path parameters checked for traversal (`..`, absolute paths) before any file system use.
- Free-text fields (subject, description) HTML-stripped + length-capped at the schema layer.

## Output safety
- All API responses serialized via Pydantic `Out` schemas — never raw model dicts.
- HTML sanitization (`bleach`) for any field rendered as HTML on the frontend (e.g. ticket descriptions in admin view).
- File downloads: enforce `Content-Disposition: attachment; filename="..."` with sanitized filename.

## SQL & ORM
- Never concatenate user input into SQL. SQLAlchemy ORM or parameterized queries only.
- Prefer scoped queries (`WHERE org_id = ?`) so a missing filter can't leak across tenants.

## Secrets
- All secrets via env vars loaded by `app.core.config.Settings`. Never in code, never in git.
- `.env.example` committed with placeholder values. `.env` gitignored.
- Production uses a secrets manager (decided later — Vault, AWS Secrets Manager, or Doppler).
- Rotate JWT secret on incident. Document rotation steps in `docs/runbooks/rotate-jwt.md`.

## CSRF
- Backend is API-only with JWT (no cookies for auth) — CSRF token unnecessary.
- If we ever add cookie-based session, add `SameSite=Strict` + double-submit token.

## Rate limiting & abuse
- Per-IP and per-user rate limits (see `api-conventions.md`).
- ML-heavy endpoints have lower limits.
- Account lockout: 5 failed logins in 15 min → 30 min lockout. Unlock via admin or email confirmation.
- Audit log captures: login, logout, failed login, password change, role change, gov-side approvals/rejections.

## Logging
- **Never log**: passwords, JWTs, refresh tokens, raw PII (Aadhaar, PAN, full phone/email beyond domain), full document text.
- Use redaction filter that scrubs known patterns from log records.
- Structured JSON logs include `request_id`, `user_id` (if known), `module`, `action`, `result`.

## CORS
- Origin allowlist via env. No `*`. Credentials disabled unless a frontend explicitly needs them.

## File storage
- Uploaded files stored under `backend/storage/<module>/<yyyy-mm-dd>/<uuid>.<ext>` (or S3 prefix in prod).
- Filenames are server-generated UUIDs. Original filename stored in DB.
- Per-file ACL: only owner / assigned officer / explicit share can read.
- Pre-signed URLs expire in 5 min for downloads.

## ML-specific
- Adversarial inputs (huge images, malformed PDFs) caught at validation, not pipeline.
- LLM responses (RAG chatbot) sanitized for prompt injection echoes before display.
- Don't include raw user prompts in error messages echoed to other users.

## PII tagging
- Schemas mark PII fields with `Field(..., json_schema_extra={"pii": True})`.
- A pre-commit check (planned) flags any new field that looks like PII without the tag.
- Retention: PII-tagged data has shorter retention (24h–30d depending on module). Non-PII can stay longer for analytics.

## Audit trail (gov-side)
- Every gov-side mutation writes a row to `audit_log`: `(actor_id, module, action, target_id, before, after, ts, request_id, ip, user_agent)`.
- `audit_log` is append-only (no UPDATE/DELETE). Enforced via DB grants in prod.
- FOIA-grade trail. Searchable by date range and actor in admin UI.

## Dependency hygiene
- `pip-audit` (or `safety`) in CI on every PR.
- Dependabot / Renovate for upgrade PRs.
- Pin all direct deps in `pyproject.toml`. Lockfile (`pip-tools` or `uv lock`) committed.

## Anti-patterns
- ❌ `eval()`, `exec()`, `pickle.load()` on user input — ever.
- ❌ Disabling SSL verification in `httpx`/`requests`.
- ❌ Trusting client-supplied user IDs / role flags.
- ❌ "Temporary" `print()`-debug of secrets or PII.
- ❌ Hardcoded admin credentials in seed scripts.
