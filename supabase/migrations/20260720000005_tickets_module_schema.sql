-- Citizen Module 3 — Support Tickets, Phase 1.0 schema.
-- Contract: docs/module-specs/07-support-tickets.md
--
-- THREE DELIBERATE DEVIATIONS FROM THE SPEC, forced by the live DB:
--
-- 1. No PostGIS on this project (extensions: vector, pgcrypto, uuid-ossp,
--    pg_stat_statements — no postgis). The spec's
--    `geo GEOGRAPHY(POINT,4326)` + `USING GIST(geo)` cannot be created.
--    Using plain geo_lat/geo_lng doubles + an H3 cell string computed
--    app-side. Radius search = bounding box on (lat,lng) then haversine
--    in Python; clustering = group by geo_h3.
--
-- 2. `templates` already belongs to document_intelligence (document_type,
--    fields, is_system). The spec's ticket templates would collide, so
--    they live in `ticket_templates`.
--
-- 3. Ticket ids are VARCHAR(16) "TKT-1024" per the spec and the frontend
--    mock, allocated from ticket_id_counter — the same counter pattern
--    the doc/cand/job/tv modules already use.
--
-- Phase 0's standards (CHECK constraints on status columns, updated_at
-- triggers, FK delete actions, FK indexes) are applied here at creation
-- time rather than retrofitted later.

-- ---------------------------------------------------------------- counter
create table if not exists public.ticket_id_counter (
  id    int primary key default 1,
  seq   bigint not null default 1023,          -- next id is 1024, matching the mock
  constraint ticket_id_counter_id_check check (id = 1)
);
insert into public.ticket_id_counter (id, seq) values (1, 1023)
  on conflict (id) do nothing;

-- ---------------------------------------------------------------- tickets
create table if not exists public.tickets (
  id                varchar(16) primary key,               -- "TKT-1024"
  subject           varchar(255) not null,
  description       text not null default '',              -- HTML-stripped on insert
  category          varchar(32)  not null,
  priority          varchar(8)   not null default 'NORMAL',
  priority_was_auto boolean      not null default true,
  status            varchar(16)  not null default 'open',
  department        varchar(32)  not null,
  submitted_by      uuid         null references public.users(id) on delete set null,
  is_anonymous      boolean      not null default false,
  geo_lat           double precision null,
  geo_lng           double precision null,
  geo_h3            varchar(20)  null,                     -- H3 cell, computed app-side
  location_label    varchar(255) null,
  upvotes           integer      not null default 0,
  sentiment         varchar(8)   null,
  ai_classification jsonb        not null default '{}'::jsonb,
  rating            integer      null,
  rating_comment    text         null,
  sla_due_at        timestamptz  not null,
  sla_status        varchar(16)  not null default 'on_track',
  assigned_at       timestamptz  null,
  assigned_to_id    uuid         null references public.users(id) on delete set null,
  resolved_at       timestamptz  null,
  closed_at         timestamptz  null,
  reopened_at       timestamptz  null,
  created_at        timestamptz  not null default now(),
  updated_at        timestamptz  not null default now(),

  constraint tickets_status_check check (status in
    ('open','assigned','in_progress','verification','resolved','closed','reopened')),
  constraint tickets_priority_check check (priority in
    ('LOW','NORMAL','HIGH','CRITICAL')),
  constraint tickets_category_check check (category in
    ('Roads','Water','Electric','Sanitation','Public_Safety','Parks','Health',
     'Drainage','Traffic','Planning','Other')),
  constraint tickets_department_check check (department in
    ('PWD','Water_Board','Electricity_Board','Sanitation','Police','Parks',
     'Health','Drainage','Traffic','Planning')),
  constraint tickets_sla_status_check check (sla_status in
    ('on_track','at_risk','breached')),
  constraint tickets_sentiment_check check (sentiment is null or sentiment in
    ('positive','neutral','negative')),
  constraint tickets_rating_check check (rating is null or rating between 1 and 5),
  -- lat/lng travel together or not at all
  constraint tickets_geo_pair_check check (
    (geo_lat is null and geo_lng is null) or (geo_lat is not null and geo_lng is not null)),
  constraint tickets_geo_range_check check (
    geo_lat is null or (geo_lat between -90 and 90 and geo_lng between -180 and 180)),
  -- an anonymous ticket must not carry a submitter
  constraint tickets_anonymous_check check (not (is_anonymous and submitted_by is not null))
);

create index if not exists ix_tickets_dept_status   on public.tickets(department, status);
create index if not exists ix_tickets_submitted_by  on public.tickets(submitted_by) where submitted_by is not null;
create index if not exists ix_tickets_assigned_to   on public.tickets(assigned_to_id) where assigned_to_id is not null;
create index if not exists ix_tickets_created       on public.tickets(created_at desc);
create index if not exists ix_tickets_upvotes       on public.tickets(upvotes desc);
create index if not exists ix_tickets_geo_h3        on public.tickets(geo_h3) where geo_h3 is not null;
create index if not exists ix_tickets_geo_latlng    on public.tickets(geo_lat, geo_lng) where geo_lat is not null;
create index if not exists ix_tickets_sla_due       on public.tickets(sla_due_at) where status not in ('resolved','closed');

-- ----------------------------------------------------------- attachments
create table if not exists public.ticket_attachments (
  id           uuid primary key default gen_random_uuid(),
  ticket_id    varchar(16) not null references public.tickets(id) on delete cascade,
  type         varchar(16) not null,
  name         varchar(255) not null,
  storage_path text not null,
  mime_type    varchar(128) null,
  size_bytes   bigint not null default 0,
  transcript   text null,                       -- voice -> text, 30-day retention
  created_at   timestamptz not null default now(),
  constraint ticket_attachments_type_check check (type in
    ('photo','video','voice','location','file'))
);
create index if not exists ix_ticket_attachments_ticket on public.ticket_attachments(ticket_id);

-- --------------------------------------------------------------- updates
create table if not exists public.ticket_updates (
  id          uuid primary key default gen_random_uuid(),
  ticket_id   varchar(16) not null references public.tickets(id) on delete cascade,
  actor_id    uuid null references public.users(id) on delete set null,
  actor_label varchar(128) not null default 'System',
  actor_role  varchar(16)  not null default 'system',
  text        text not null,
  visibility  varchar(8)   not null default 'public',
  created_at  timestamptz  not null default now(),
  constraint ticket_updates_role_check check (actor_role in
    ('citizen','gov_officer','gov_admin','system')),
  constraint ticket_updates_visibility_check check (visibility in ('public','internal'))
);
create index if not exists ix_ticket_updates_ticket   on public.ticket_updates(ticket_id, created_at);
create index if not exists ix_ticket_updates_actor    on public.ticket_updates(actor_id) where actor_id is not null;

-- --------------------------------------------------------------- upvotes
-- PK (ticket_id, citizen_id) makes upvoting idempotent per the spec.
create table if not exists public.ticket_upvotes (
  ticket_id  varchar(16) not null references public.tickets(id) on delete cascade,
  citizen_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (ticket_id, citizen_id)
);
create index if not exists ix_ticket_upvotes_citizen on public.ticket_upvotes(citizen_id);

-- -------------------------------------------------------------- comments
create table if not exists public.ticket_comments (
  id         uuid primary key default gen_random_uuid(),
  ticket_id  varchar(16) not null references public.tickets(id) on delete cascade,
  citizen_id uuid not null,
  text       text not null,
  created_at timestamptz not null default now(),
  deleted_at timestamptz null
);
create index if not exists ix_ticket_comments_ticket on public.ticket_comments(ticket_id, created_at);

-- ------------------------------------------------------- ticket templates
-- NOT `templates` — that name is document_intelligence's.
create table if not exists public.ticket_templates (
  id          uuid primary key default gen_random_uuid(),
  title       varchar(128) not null unique,
  body        text not null,
  category    varchar(32) not null,
  sort_order  integer not null default 0,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint ticket_templates_category_check check (category in
    ('Roads','Water','Electric','Sanitation','Public_Safety','Parks','Health',
     'Drainage','Traffic','Planning','Other'))
);

-- --------------------------------------------------------- routing rules
-- ML predicts the category; these rules pick department + priority + SLA.
create table if not exists public.routing_rules (
  id               uuid primary key default gen_random_uuid(),
  category         varchar(32) not null,
  keywords         jsonb not null default '[]'::jsonb,
  department       varchar(32) not null,
  default_priority varchar(8)  not null default 'NORMAL',
  sla_hours        integer     not null default 48,
  active           boolean     not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint routing_rules_category_check check (category in
    ('Roads','Water','Electric','Sanitation','Public_Safety','Parks','Health',
     'Drainage','Traffic','Planning','Other')),
  constraint routing_rules_department_check check (department in
    ('PWD','Water_Board','Electricity_Board','Sanitation','Police','Parks',
     'Health','Drainage','Traffic','Planning')),
  constraint routing_rules_priority_check check (default_priority in
    ('LOW','NORMAL','HIGH','CRITICAL')),
  constraint routing_rules_sla_check check (sla_hours > 0),
  constraint routing_rules_category_uniq unique (category)
);

-- ----------------------------------------------------- updated_at triggers
-- Phase 0.4's function, applied at creation time so these tables never
-- develop the stale-timestamp bug govt_fines_penalties had.
create trigger tickets_set_updated_at
  before update on public.tickets
  for each row execute function public.trigger_set_updated_at();

create trigger ticket_templates_set_updated_at
  before update on public.ticket_templates
  for each row execute function public.trigger_set_updated_at();

create trigger routing_rules_set_updated_at
  before update on public.routing_rules
  for each row execute function public.trigger_set_updated_at();

-- ------------------------------------------------------------ id allocator
-- Atomic: concurrent submits cannot collide on a ticket id.
create or replace function public.next_ticket_id()
returns varchar(16)
language plpgsql
as $$
declare
  n bigint;
begin
  update public.ticket_id_counter set seq = seq + 1 where id = 1 returning seq into n;
  return 'TKT-' || n::text;
end;
$$;

-- --------------------------------------------------------------- seeding
-- Routing rules: category -> department + default priority + SLA hours.
-- Derived from the frontend mock's own SLA/dept mapping (pages.jsx:7702-7703)
-- so behaviour matches what the UI already promises citizens.
insert into public.routing_rules (category, keywords, department, default_priority, sla_hours) values
  ('Roads',         '["pothole","road","crack","speed breaker","signage","footpath"]', 'PWD',                'NORMAL', 48),
  ('Water',         '["water","supply","leak","pipeline","tap","sewage backup"]',      'Water_Board',        'HIGH',    8),
  ('Electric',      '["streetlight","power","outage","electric","transformer","wire"]','Electricity_Board',  'NORMAL', 24),
  ('Sanitation',    '["garbage","waste","trash","dump","litter","smell"]',             'Sanitation',         'NORMAL', 48),
  ('Public_Safety', '["stray","dog","attack","unsafe","danger","harassment","fire"]',  'Police',             'HIGH',    4),
  ('Parks',         '["park","playground","bench","garden","tree","swing"]',           'Parks',              'LOW',    72),
  ('Health',        '["mosquito","dengue","clinic","hospital","disease","sanitary"]',  'Health',             'HIGH',   12),
  ('Drainage',      '["drain","flood","waterlog","overflow","manhole","clog"]',        'Drainage',           'HIGH',   12),
  ('Traffic',       '["signal","traffic","congestion","parking","jam","zebra"]',       'Traffic',            'NORMAL', 24),
  ('Planning',      '["construction","illegal","encroach","permit","zoning","build"]', 'Planning',           'LOW',    72),
  ('Other',         '[]',                                                              'PWD',                'NORMAL', 48)
on conflict (category) do nothing;

-- Ticket templates: the six the frontend mock hardcodes (pages.jsx:7689-7694),
-- so GET /templates can serve them from the DB instead of the bundle.
insert into public.ticket_templates (title, body, category, sort_order) values
  ('Road Pothole',            'There is a dangerous pothole on [Street Name] near [Landmark]. It has been there for [duration] and has caused damage to vehicles.', 'Roads',         1),
  ('Water Supply Issue',      'We have had no water supply in [Area/Zone] since [Date/Time]. This is affecting [N] households.',                                    'Water',         2),
  ('Streetlight Out',         'The streetlight at [Location] has been out for [duration]. This creates a safety risk at night.',                                    'Electric',      3),
  ('Garbage Pile',            'Uncollected garbage at [Location] since [Date]. Creating health hazard and bad smell in the area.',                                  'Sanitation',    4),
  ('Stray Animals',           'Aggressive stray dogs in [Area] have been attacking residents. Request immediate intervention.',                                     'Public_Safety', 5),
  ('Public Park Maintenance', 'The public park at [Location] needs [specific maintenance]. Benches broken / playground unsafe / etc.',                              'Parks',         6)
on conflict (title) do nothing;

comment on table public.tickets is
  'Citizen civic-issue tickets (module 07). No PostGIS on this project: geo is geo_lat/geo_lng + app-side H3 in geo_h3, not GEOGRAPHY.';
