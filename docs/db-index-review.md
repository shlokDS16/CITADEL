# DB Index Review (Phase 0.8)

Run: 2026-07-20 · Against the live Supabase DB (Postgres 17.6), not the `.sql` files.
Tools: `index_advisor` 0.2.0 + `hypopg` 1.4.1 (installed during this review), `pg_stat_statements` 1.11.

## Verdict

**No new indexes. Do not act on the advisor output yet.** Two independent reasons.

### 1. The statistics are not representative

`pg_stat_statements` held 267 statements / 1418 calls at review time, and the top
entries by total time were Supabase internals (`set_config`, `schema_migrations`,
`storage.buckets`) plus the audit queries *this review itself* had just issued.
Real application traffic is barely present — the backend was not serving load.

The advisor duly recommended an index for
`select count(*) from public.tv_audit_log where entity_id = $1`, which was a
verification query written minutes earlier, not an application query pattern.

It also recommended `audit_log (performed_by)` off a bare `select count(*) from
public.audit_log` — a query with no predicate at all. That is an advisor artifact.
Neither recommendation survives contact with the code.

### 2. Every table is far too small for an index to help

Largest table in the schema: **122 rows** (`fact_check_feed`). Next: 99
(`tv_audit_log`), 31 (`analyses`). Everything else is under 25 rows or empty.

Below roughly a few hundred rows a table occupies one or two heap pages, and a
sequential scan beats an index scan outright — the planner will correctly ignore
any index added today. `pg_stat_user_tables` confirms it is already choosing seq
scans (`tv_cameras`: 80 seq scans, 0 index scans).

The schema is in fact **already over-indexed for its size**: `documents` carries
10 indexes across 5 rows, `tv_incidents` 8, `tv_challans` 6 across 9 rows. Adding
more would cost write amplification and storage for no read benefit.

## What the review did produce

The advisor run was still worth doing — it surfaced a genuine defect while
inspecting how the audit tables are actually queried:

`tv_audit_log`'s timestamp column is `ts`, but two service queries ordered by
`created_at`, which does not exist. PostgREST rejected both (42703) and a bare
`except Exception` swallowed the error, silently emptying the Offenders-tab
timeline and the Analytics audit-trail widget. Fixed in commit `0b52deb`.

## Existing index coverage vs. real query patterns

Checked the audit tables' real filter/sort columns against what exists:

| Query site | Pattern | Covering index | Status |
|---|---|---|---|
| `service.py:2318` | `eq(entity_type)` + `eq(entity_id)` + `order(ts)` | `idx_tv_audit_entity (entity_type, entity_id)` | covered |
| `service.py:768` | `order(ts desc) limit 12` | `idx_tv_audit_ts (ts DESC)` | covered |
| `service.py:387` | `in_(entity_id)` + `order(ts)` | `idx_tv_audit_entity` leading col is `entity_type` | not covered — see below |
| `doc_intel service.py:348` | `eq(document_id)` + `order(created_at)` | `idx_audit_document`, `idx_audit_created_at` | covered |

The one genuine gap is `tv_audit_log.entity_id` queried *without* `entity_type`
(`offender_timeline`), which cannot use the composite index's leading column.
At 99 rows this is irrelevant. **Revisit when `tv_audit_log` passes ~10k rows**;
the fix would be a standalone `ix_tv_audit_log_entity_id`.

## When to re-run

Re-run this review once the platform has served realistic traffic — after auth
lands (Phase 3) and the dashboards are de-hardcoded (Phase 4), with the backend
up under load. Reset the baseline first so the sample is clean:

```sql
select pg_stat_statements_reset();
-- ...generate representative traffic...
select index_statements, errors
from index_advisor('<query from pg_stat_statements>');
```

Judge every recommendation against the calling code before applying it. This run
is the cautionary example.
