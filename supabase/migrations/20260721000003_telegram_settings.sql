-- Phase 6 — per-account Telegram configuration.
--
-- Keeps the EXISTING delivery framework (Bot API sendMessage/sendPhoto via
-- TELEGRAM_BOT_TOKEN). This table just lets any signed-in account point
-- alerts at THEIR own chat, exactly the way the platform's demo account
-- receives them today (which is simply TELEGRAM_DEFAULT_CHAT_ID).
--
-- bot_token is nullable: the easy path is to reuse the platform's shared
-- bot (@citadel2005_bot) and only supply your chat_id. Advanced users can
-- paste their own BotFather token to run fully independently.
--
-- Token is stored server-side and NEVER returned to the client in full
-- (the API masks it). It is written only through the service_role backend,
-- and the direct data API is already sealed (migration 20260721000002).

create table if not exists public.telegram_settings (
  user_id     uuid primary key references public.users(id) on delete cascade,
  bot_token   text null,
  chat_id     text not null,
  enabled     boolean not null default true,
  verified_at timestamptz null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint telegram_chat_id_check check (length(chat_id) between 1 and 64)
);

create trigger telegram_settings_set_updated_at
  before update on public.telegram_settings
  for each row execute function public.trigger_set_updated_at();

comment on table public.telegram_settings is
  'Per-account Telegram recipient config. bot_token null = use the platform shared bot. Token never leaves the backend unmasked.';
