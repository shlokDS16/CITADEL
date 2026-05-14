# Rule: Data Handling, PII, Retention & Tenancy

> Civic platform — handles PII at scale. This rule is checked on every schema change and storage decision.

## Tenancy model
- **Two top-level tenants**: `government` and `citizen`. They share an auth surface but their data is **fully isolated**.
- Every domain table has an `owner_role` column (`gov` | `citizen`) plus `owner_id` (FK to `users`).
- Service-layer queries filter by `owner_role` automatically via a base `Repo` class. Bypassing the filter requires an explicit `_admin_query()` method that audit-logs the access.

## PII classification
| Class | Examples | Storage rule | Log rule | Retention |
|---|---|---|---|---|
| Public | name (when self-published), city | normal | OK | indefinite |
| Personal | full name, email, phone, address | encrypted at rest | masked in logs | 3y default |
| Sensitive | Aadhaar, PAN, biometric, exact GPS, plate | column-level encrypted (`fernet`) | never logged | 1y for citizen / 7y for gov audit |
| Restricted | passwords, JWTs, OTP secrets | hashed (argon2id) / vault-only | never logged | rotated per-incident |

## Field tagging
- Pydantic schemas mark fields with `json_schema_extra={"pii_class": "sensitive"}`.
- DB models declare `__pii_classes__ = {"aadhaar": "sensitive", "phone": "personal"}`.
- A pre-commit hook (planned) flags any new `*_aadhaar`, `*_pan`, `*_phone`, `*_email` field that lacks a class.

## Encryption
- App-level: `cryptography.fernet` for sensitive columns. Key in env, rotated yearly.
- DB-level: full-disk encryption assumed in prod (RDS / managed Postgres handles it).
- Backups encrypted with a separate key. Restored backups go through a redaction pipeline before access.

## Retention & deletion
- Per-table retention policy defined in `app/db/models/<table>.py` as `RETENTION_DAYS = ...`.
- Daily job purges rows past retention. Soft-delete first (sets `deleted_at`), hard-delete after grace period (default 30 days).
- Citizen-initiated deletion: account delete cascades to all citizen-owned rows. Government-side records anonymized (preserve aggregates, redact PII).
- Audit log is **append-only** and exempt from deletion.

## Right-to-access (citizen)
- Endpoint: `GET /api/v1/me/export` returns a JSON ZIP of all the citizen's data within 30 days.
- Citizen can download their own ticket history, expense logs, chat sessions.

## Right-to-erasure (citizen)
- Endpoint: `DELETE /api/v1/me` schedules account deletion in 7 days (cooling period).
- During cooling period, account is locked but reversible.
- After cooling period, all owned rows hard-deleted, audit log entries anonymized (`actor_id` → `redacted-<hash>`).

## Cross-module data sharing
- **Default deny**. Modules don't read each other's tables.
- When sharing is needed (e.g. tickets module wants user's expense category history), it goes through an explicit `app.shared.read_*` function with audit logging.
- Government module → citizen data: requires legal basis, logged with `legal_basis_code`.

## File handling
- Uploaded files: original filename stored in DB; on disk, files are renamed to `<uuid>.<ext>` to prevent enumeration.
- Per-user storage quota enforced (default 100MB citizen, 5GB gov officer).
- Periodic orphan-file scan: files on disk without DB row → quarantined → deleted after 7 days.

## Indexing & search
- Sensitive fields not indexed in plaintext. If search is needed, store a deterministic HMAC hash for equality lookup.
- Free-text search (subjects, descriptions) goes through Postgres FTS or Meilisearch — never stores PII tokens separately.

## Caching
- Redis cache keys include `user_id` so cache leaks across users are impossible.
- Cache TTL ≤ 5 min for any query that includes filtered (per-user) results.
- Never cache sensitive PII fields.

## Analytics
- Analytics events scrubbed of PII at the SDK boundary.
- User identifier is a hashed pseudonymous ID, not raw `user_id`.
- Aggregate dashboards only — no per-user drilldown that exposes PII.

## Government audit trail
- Every gov-side mutation: `audit_log` row.
- Includes `actor_id`, `module`, `action`, `target_id`, `before`, `after` (JSON diff), `ts`, `request_id`, `ip`, `user_agent`, `legal_basis_code` (when accessing citizen data).
- Append-only DB role enforced: gov_app role has INSERT but not UPDATE/DELETE on `audit_log`.

## Anti-patterns
- ❌ Logging `request.json()` directly when the body has PII.
- ❌ "Soft-deleting" by setting a flag and forgetting the hard-delete job.
- ❌ Storing Aadhaar / PAN unencrypted "for now".
- ❌ Cross-tenant queries (gov reading citizen data) without audit log + legal basis code.
- ❌ Including raw IDs in URLs that get shared in support tickets / screenshots.
