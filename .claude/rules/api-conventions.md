# Rule: API Conventions

> The contract between frontend and backend. Both sides obey this. Reviewed by `api-contract-validator` agent.

## URL shape
- Versioned: `/api/v1/<module>/<resource>`
- Module names match frontend page IDs (kebab-case): `doc-intel`, `resume`, `traffic`, `anomaly`, `chatbot`, `fake-news`, `tickets`, `expenses`.
- Resource names are plural nouns: `/documents`, `/candidates`, `/incidents`, `/alerts`, `/tickets`, `/expenses`.
- Actions on a resource use sub-paths: `/documents/{id}/approve`, `/candidates/{id}/move-stage`.

## Request format
- JSON body for `POST` / `PUT` / `PATCH`.
- `multipart/form-data` only for file uploads.
- Headers required:
  - `Authorization: Bearer <jwt>` (except auth endpoints)
  - `Content-Type: application/json` (or `multipart/form-data`)
  - `Idempotency-Key: <uuid>` on all mutating requests
  - `X-Request-Id: <uuid>` (optional — server generates if missing)

## Response format

### Success
```json
{
  "data": { ... } or [ ... ],
  "meta": {
    "request_id": "uuid",
    "page": 1,
    "page_size": 25,
    "total": 142
  }
}
```

### Error
```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document with id abc-123 was not found.",
    "details": { "id": "abc-123" },
    "request_id": "uuid"
  }
}
```

## HTTP status codes
| Code | When |
|------|------|
| 200 | OK — read or sync write |
| 201 | Created — new resource (return resource in `data`) |
| 202 | Accepted — async job started (return `{ job_id, status_url }` in `data`) |
| 204 | No Content — successful delete |
| 400 | Validation failure (request body shape wrong) |
| 401 | Missing or expired JWT |
| 403 | Authenticated but not authorized (RBAC: citizen tried gov endpoint) |
| 404 | Resource not found |
| 409 | Conflict (duplicate, state transition invalid) |
| 422 | Semantic validation failure (well-formed but invalid — e.g. job already filled) |
| 429 | Rate limited (include `Retry-After` header) |
| 500 | Server error (log + return `request_id`, never stack trace) |

## Error code naming
- `UPPER_SNAKE_CASE`.
- Module-prefixed when scoped: `DOC_INTEL_OCR_FAILED`, `RESUME_INVALID_PDF`, `TRAFFIC_CAMERA_OFFLINE`.
- Generic codes: `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_FAILED`, `RATE_LIMITED`, `INTERNAL_ERROR`.

## Pagination
- Query params: `?page=1&page_size=25`. Defaults: `page=1`, `page_size=25`. Max: `page_size=100`.
- Response `meta.total` is the unfiltered count (after `?q=` and filters).

## Filtering
- Each module spec defines its filter params explicitly (e.g. `?status=pending&severity=high&from=2026-01-01`).
- All filter values comma-separated for multi-select: `?status=pending,review`.

## Sorting
- `?sort=field` ascending. `?sort=-field` descending. Multi: `?sort=-created_at,name`.
- Whitelist allowed sort fields per endpoint (return 400 on disallowed fields).

## Search
- `?q=<text>`. Module decides scope (subject + description, name + role, plate + driver, etc.).

## Async jobs
- Return `202 Accepted` with body:
  ```json
  { "data": { "job_id": "...", "status_url": "/api/v1/<module>/jobs/<job_id>", "estimated_seconds": 12 } }
  ```
- Status endpoint returns `{ status: "queued" | "running" | "succeeded" | "failed", progress: 0..1, result?, error? }`.
- Optional WebSocket: `/api/v1/<module>/jobs/<job_id>/stream` for live progress.

## Real-time channels
- WebSocket URL: `/ws/<module>/<channel>`
- Examples: `/ws/traffic/live-feed`, `/ws/anomaly/alerts`, `/ws/tickets/inbox`.
- Auth: send JWT as first message after connect.
- Message format: `{ type: "...", payload: {...}, ts: "..." }`.

## Versioning
- Major version in URL: `/api/v1`, `/api/v2`. No minor version in URL.
- Backward-compatible additions go in v1. Breaking changes require v2.
- Sunset older versions with 6-month deprecation notice via `Deprecation` and `Sunset` response headers.

## CORS
- Allowed origins: `http://127.0.0.1:8080`, `http://localhost:8080`, plus prod domains via env config.
- Allowed headers include `Authorization`, `Content-Type`, `Idempotency-Key`, `X-Request-Id`.
- Allow credentials only when actually needed.

## Rate limiting
- Default: 60 req/min per user, 600 req/min per IP for unauthenticated.
- ML-heavy endpoints (OCR, inference): 10 req/min per user.
- Headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

## Idempotency
- All `POST` / `PUT` / `PATCH` / `DELETE` should accept `Idempotency-Key`.
- Server stores `(user_id, key) → response` for 24h.
- Replay returns the cached response.
