-- Citizen Module 4 — Expense Categorizer, Phase 2.0 schema.
-- Contract: docs/module-specs/08-expense-categorizer.md
--
-- DEVIATIONS FROM THE SPEC, decided against the live environment:
--
-- 1. One category vocabulary. The spec's Out-schemas use underscore
--    literals ("Food_Dining") while the mock UI and the shipped
--    merchants.py lexicon both use display names ("Food & Dining").
--    Tickets needed the dual vocabulary because its DB predated the UI;
--    here we control both ends, so the display names ARE the stored
--    values — no mapping layer to drift.
--
-- 2. citizen_id is a bare uuid with NO FK to public.users. The spec never
--    FK'd it either, and users only holds gov accounts pre-Phase-3 — the
--    browser identity uuid (same citadel_tk_uid the tickets module mints)
--    is stored directly so personal finance is genuinely per-browser
--    scoped even before auth. Phase 3 swaps in the JWT subject.
--
-- 3. Money is stored as paise (bigint) per the spec; the API accepts and
--    returns rupees. The conversion lives in exactly one place
--    (service.py) — schemas document it.
--
-- 4. expense_merchant_cache is an extension table (not in the spec): it
--    memoises per-merchant labels from the LLM/human corrections so a new
--    merchant costs one Groq call ever, not one per transaction. This is
--    the token-frugality core of the categorizer design (merchants.py).

-- ---------------------------------------------------------------- helpers
-- Categories mirrored by app.modules.expenses.merchants.CATEGORIES.
-- Changing one side without the other will 23514 — that is the point.

-- --------------------------------------------------------------- expenses
create table if not exists public.expenses (
  id                  uuid primary key default gen_random_uuid(),
  citizen_id          uuid not null,
  description         varchar(255) not null,
  merchant            varchar(128) null,
  amount_paise        bigint not null,
  category            varchar(24) not null default 'Other',
  category_was_auto   boolean not null default true,
  category_confidence double precision null,
  spent_at            date not null,
  tax_deductible      boolean not null default false,
  tax_section         varchar(16) null,
  is_anomaly          boolean not null default false,
  anomaly_reason      text null,
  source              varchar(16) not null default 'manual',
  receipt_id          uuid null,
  import_batch_id     uuid null,
  notes               text null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  deleted_at          timestamptz null,

  constraint expenses_amount_check check (amount_paise > 0),
  constraint expenses_category_check check (category in
    ('Food & Dining','Groceries','Transport','Utilities','Healthcare',
     'Shopping','Education','Entertainment','Housing','Insurance','Other')),
  constraint expenses_source_check check (source in
    ('manual','receipt_ocr','bank_csv','bank_pdf','upi','card')),
  constraint expenses_tax_section_check check (tax_section is null or tax_section in
    ('80C','80D','HRA','BUSINESS','NONE')),
  constraint expenses_confidence_check check (
    category_confidence is null or (category_confidence >= 0 and category_confidence <= 1))
);
create index if not exists ix_expenses_citizen  on public.expenses(citizen_id, spent_at desc) where deleted_at is null;
create index if not exists ix_expenses_category on public.expenses(citizen_id, category, spent_at desc) where deleted_at is null;
create index if not exists ix_expenses_anomaly  on public.expenses(citizen_id) where is_anomaly = true and deleted_at is null;
create index if not exists ix_expenses_batch    on public.expenses(import_batch_id) where import_batch_id is not null;

-- --------------------------------------------------------------- receipts
create table if not exists public.receipts (
  id                 uuid primary key default gen_random_uuid(),
  citizen_id         uuid not null,
  storage_path       text not null,
  original_filename  varchar(255) null,
  status             varchar(16) not null default 'review',
  merchant           varchar(128) null,
  subtotal_paise     bigint null,
  tax_paise          bigint null,
  total_paise        bigint null,
  purchase_date      date null,
  predicted_category varchar(24) null,
  confidence         double precision null,
  ocr_raw_text       text null,               -- pruned after 30 days
  ocr_engine         varchar(32) null,        -- which engine actually read it
  expense_id         uuid null,
  created_at         timestamptz not null default now(),
  confirmed_at       timestamptz null,
  constraint receipts_status_check check (status in
    ('queued','processing','review','confirmed','rejected')),
  constraint receipts_category_check check (predicted_category is null or predicted_category in
    ('Food & Dining','Groceries','Transport','Utilities','Healthcare',
     'Shopping','Education','Entertainment','Housing','Insurance','Other'))
);
create index if not exists ix_receipts_citizen on public.receipts(citizen_id, created_at desc);
create index if not exists ix_receipts_status  on public.receipts(status);

create table if not exists public.receipt_items (
  id               uuid primary key default gen_random_uuid(),
  receipt_id       uuid not null references public.receipts(id) on delete cascade,
  name             varchar(255) not null,
  qty              integer not null default 1,
  unit_price_paise bigint null,
  line_total_paise bigint null
);
create index if not exists ix_receipt_items_receipt on public.receipt_items(receipt_id);

-- expenses.receipt_id FK added after receipts exists (both directions used)
alter table public.expenses
  add constraint expenses_receipt_id_fkey
  foreign key (receipt_id) references public.receipts(id) on delete set null;

-- ---------------------------------------------------------------- budgets
create table if not exists public.budgets (
  id                  uuid primary key default gen_random_uuid(),
  citizen_id          uuid not null,
  category            varchar(24) not null,
  amount_paise        bigint not null,
  period              varchar(8) not null default 'monthly',
  alert_threshold_pct integer not null default 80,
  active              boolean not null default true,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint budgets_amount_check check (amount_paise > 0),
  constraint budgets_period_check check (period in ('monthly','weekly','yearly')),
  constraint budgets_threshold_check check (alert_threshold_pct between 1 and 100),
  constraint budgets_category_check check (category in
    ('Food & Dining','Groceries','Transport','Utilities','Healthcare',
     'Shopping','Education','Entertainment','Housing','Insurance','Other'))
);
create unique index if not exists ux_budgets_citizen_cat
  on public.budgets(citizen_id, category, period) where active;

-- ---------------------------------------------------------------- imports
create table if not exists public.import_batches (
  id             uuid primary key default gen_random_uuid(),
  citizen_id     uuid not null,
  source         varchar(16) not null,
  source_label   varchar(64) null,
  total_rows     integer not null default 0,
  parsed_rows    integer not null default 0,
  duplicate_rows integer not null default 0,
  committed_rows integer not null default 0,
  status         varchar(16) not null default 'pending',
  uploaded_at    timestamptz not null default now(),
  committed_at   timestamptz null,
  constraint import_batches_source_check check (source in ('bank_csv','bank_pdf','upi','card')),
  constraint import_batches_status_check check (status in
    ('pending','processing','parsed','committed','failed'))
);
create index if not exists ix_import_batches_citizen on public.import_batches(citizen_id, uploaded_at desc);

create table if not exists public.import_rows (
  id                   uuid primary key default gen_random_uuid(),
  batch_id             uuid not null references public.import_batches(id) on delete cascade,
  raw                  jsonb not null default '{}'::jsonb,
  parsed_description   varchar(255) null,
  parsed_merchant      varchar(128) null,
  parsed_amount_paise  bigint null,
  parsed_date          date null,
  predicted_category   varchar(24) null,
  predicted_confidence double precision null,
  is_duplicate_of      uuid null,
  selected_for_commit  boolean not null default false,
  expense_id           uuid null
);
create index if not exists ix_import_rows_batch on public.import_rows(batch_id);

-- ---------------------------------------------------------------- exports
create table if not exists public.exports (
  id           uuid primary key default gen_random_uuid(),
  citizen_id   uuid not null,
  format       varchar(16) not null,
  status       varchar(16) not null default 'queued',
  storage_path text null,
  expires_at   timestamptz null,               -- 7d TTL
  created_at   timestamptz not null default now(),
  ready_at     timestamptz null,
  constraint exports_format_check check (format in ('csv','xlsx','pdf','tax_package')),
  constraint exports_status_check check (status in ('queued','processing','ready','failed'))
);
create index if not exists ix_exports_citizen on public.exports(citizen_id, created_at desc);

-- --------------------------------------------------- merchant label cache
-- One row per merchant_key (merchants.merchant_key()). An LLM label or a
-- human correction is written here once and reused for every later
-- transaction that normalises to the same key.
create table if not exists public.expense_merchant_cache (
  merchant_key varchar(64) primary key,
  category     varchar(24) not null,
  confidence   double precision not null default 0.9,
  source       varchar(16) not null default 'llm',     -- llm | human | model
  hits         integer not null default 0,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint emc_category_check check (category in
    ('Food & Dining','Groceries','Transport','Utilities','Healthcare',
     'Shopping','Education','Entertainment','Housing','Insurance','Other')),
  constraint emc_source_check check (source in ('llm','human','model'))
);

-- ----------------------------------------------------- updated_at triggers
create trigger expenses_set_updated_at
  before update on public.expenses
  for each row execute function public.trigger_set_updated_at();

create trigger budgets_set_updated_at
  before update on public.budgets
  for each row execute function public.trigger_set_updated_at();

create trigger expense_merchant_cache_set_updated_at
  before update on public.expense_merchant_cache
  for each row execute function public.trigger_set_updated_at();

comment on table public.expenses is
  'Citizen personal expenses (module 08). Paise stored, rupees on the wire. citizen_id is the pre-auth browser uuid until Phase 3 JWT.';
comment on table public.expense_merchant_cache is
  'Per-merchant category memo — an LLM label or human correction is spent once per merchant_key, never per transaction.';
