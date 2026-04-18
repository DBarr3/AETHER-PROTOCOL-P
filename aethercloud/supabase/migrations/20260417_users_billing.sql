-- AetherCloud billing: public.users table
-- Written by the stripe-webhook edge function on checkout/subscription events.

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  stripe_customer_id text unique,
  stripe_subscription_id text unique,
  tier text not null default 'solo' check (tier in ('solo','team','pro')),
  license_key text unique,
  subscription_status text not null default 'inactive',
  current_period_end timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists users_stripe_customer_id_idx on public.users(stripe_customer_id);
create index if not exists users_email_idx on public.users(email);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end
$$;

drop trigger if exists users_set_updated_at on public.users;
create trigger users_set_updated_at
  before update on public.users
  for each row
  execute function public.set_updated_at();

-- Service role bypasses RLS; no user-facing policies yet.
alter table public.users enable row level security;

-- ───────────────────────────────────────────────────────────
-- Added 2026-04-17: 4-tier support + rate-limit table
-- ───────────────────────────────────────────────────────────

-- Allow 'free' tier (original CHECK was 'solo','team','pro')
alter table public.users drop constraint if exists users_tier_check;
alter table public.users add constraint users_tier_check
  check (tier in ('free','solo','pro','team'));
alter table public.users alter column tier set default 'free';

-- Signup attempts (IP rate limit for free-signup)
create table if not exists public.signup_attempts (
  id uuid primary key default gen_random_uuid(),
  ip text not null,
  created_at timestamptz not null default now()
);
create index if not exists signup_attempts_ip_created_idx
  on public.signup_attempts(ip, created_at desc);

alter table public.signup_attempts enable row level security;
-- Service role bypasses RLS; no user-facing policies.
