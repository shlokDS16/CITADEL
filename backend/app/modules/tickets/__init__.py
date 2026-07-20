"""
Support Tickets — CITADEL Citizen Module 3.

Citizen reports a civic issue; the system classifies it (category →
department → priority → SLA), routes it to the owning department, and
tracks it through a status timeline the citizen can follow, comment on,
rate and reopen. Community tab surfaces trending issues nearby; upvotes
raise priority.

Layering (per .claude/rules/backend-conventions.md):
  router.py    HTTP only — parse, call service, shape response
  service.py   orchestration + business rules
  repo.py      Supabase access, degrades gracefully if a table is absent
  pipeline.py  classification (Groq-first, rule-router fallback)
  schemas.py   Pydantic request/response models

Contract: docs/module-specs/07-support-tickets.md (base path /api/v1/tickets).

Deviations from the spec, forced by the live environment — see the schema
migration 20260720000005 for the full reasoning:
  * No PostGIS → geo is geo_lat/geo_lng + app-side H3, not GEOGRAPHY.
  * `templates` is document_intelligence's → ticket templates live in
    `ticket_templates`.
  * No auth until Phase 3 → actor identity comes from X-User-Id /
    X-User-Role headers by the same convention traffic and anomaly use;
    it is NOT enforced server-side yet.
"""
from app.modules.tickets.router import router  # noqa: F401
