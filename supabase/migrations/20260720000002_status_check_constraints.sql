-- Phase 0.3 — CHECK constraints on the 7 status columns.
--
-- Domains derived from application code (authoritative), not from live data:
--   documents        app/modules/document_intelligence/schemas.py:27  DocumentStatus
--   jobs             app/modules/resume/schemas.py:12                 JobStatus
--   candidates       app/modules/resume/schemas.py:13                 CandidateStatus
--   tv_incidents     app/modules/traffic_violations/service.py:137    _incident_status_to_ui
--   tv_challans      app/modules/traffic_violations/service.py:326    _CHALLAN_STATUS_COLOR
--   tv_cameras       app/modules/traffic_violations/service.py:1011   (read-only; never written by app)
--   fn_review_queue  app/modules/fake_news/repo.py:113,272            pending -> resolved
--
-- Live data was verified to conform to every domain below before this ran.
-- fn_review_queue.status is nullable; a CHECK evaluates to NULL (= pass) on
-- NULL, so existing nullability is preserved deliberately.

alter table public.documents
  add constraint documents_status_check
  check (status in ('PROCESSING', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'ARCHIVED'));

alter table public.jobs
  add constraint jobs_status_check
  check (status in ('draft', 'open', 'closed', 'archived'));

alter table public.candidates
  add constraint candidates_status_check
  check (status in ('PROCESSING', 'SHORTLISTED', 'REJECTED', 'INTERVIEW', 'OFFER', 'RECRUITED'));

alter table public.tv_incidents
  add constraint tv_incidents_status_check
  check (status in ('PENDING_REVIEW', 'APPROVED', 'REJECTED'));

alter table public.tv_challans
  add constraint tv_challans_status_check
  check (status in ('UNPAID', 'PAID', 'DISPUTED'));

alter table public.tv_cameras
  add constraint tv_cameras_status_check
  check (status in ('active', 'degraded', 'offline'));

alter table public.fn_review_queue
  add constraint fn_review_queue_status_check
  check (status in ('pending', 'resolved'));
