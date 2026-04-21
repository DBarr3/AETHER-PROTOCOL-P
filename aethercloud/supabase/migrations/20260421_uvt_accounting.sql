-- ═══════════════════════════════════════════════════════════════════════════
-- UVT (User Visible Tokens) accounting + plan config
-- 2026-04-21
--
-- Adds: plans, uvt_balances, usage_events, tasks + overage fields on users
-- Adds: rpc_record_usage (atomic ledger commit)
-- Preserves: tier keys ('free','solo','pro','team'). Starter branding lives
-- in plans.display_name, NOT in a DB rename — keeps existing rows + the
-- users_tier_check constraint + every dependency intact.
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. plans — single source of truth for tier config
create table if not exists public.plans (
  tier text primary key check (tier in ('free','solo','pro','team')),
  display_name text not null,
  price_usd_cents integer not null check (price_usd_cents >= 0),
  stripe_price_id text,
  uvt_monthly bigint not null check (uvt_monthly > 0),
  sub_agent_cap integer not null check (sub_agent_cap > 0),
  output_cap integer not null check (output_cap > 0),
  opus_pct_cap numeric(4,3) not null default 0 check (opus_pct_cap >= 0 and opus_pct_cap <= 1),
  concurrency_cap integer not null check (concurrency_cap > 0),
  overage_rate_usd_cents_per_million integer,
  context_budget_tokens integer not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists plans_set_updated_at on public.plans;
create trigger plans_set_updated_at
  before update on public.plans
  for each row execute function public.set_updated_at();

alter table public.plans enable row level security;

comment on table public.plans is
  'Tier config — pricing, UVT quota, per-task caps, Opus sub-budget, concurrency, overage rate. Single source of truth read by tiers.ts via /api/plans and by VPS2 PricingGuard.';
comment on column public.plans.opus_pct_cap is
  'Fraction of uvt_monthly that may be spent on Opus. 0 = no Opus. Enforced by router.';
comment on column public.plans.overage_rate_usd_cents_per_million is
  'Post-quota usage bill rate in USD cents per 1,000,000 UVT. NULL = overage not offered.';
comment on column public.plans.context_budget_tokens is
  'Max tokens for QOPC-hydrated context passed to orchestrator. Prevents context-injection UVT leaks.';

-- Seed — NEW pricing model 2026-04-21
insert into public.plans
  (tier, display_name, price_usd_cents, uvt_monthly, sub_agent_cap, output_cap,
   opus_pct_cap, concurrency_cap, overage_rate_usd_cents_per_million, context_budget_tokens)
values
  ('free', 'Free',    0,     15000,   5,  8000,  0.000,  1, null, 8000),
  ('solo', 'Starter', 1999,  400000,  8,  16000, 0.000,  1, 4900, 24000),
  ('pro',  'Pro',     4999,  1500000, 15, 32000, 0.100,  3, 3500, 80000),
  ('team', 'Team',    8999,  3000000, 25, 64000, 0.250, 10, 3200, 160000)
on conflict (tier) do update set
  display_name                        = excluded.display_name,
  price_usd_cents                     = excluded.price_usd_cents,
  uvt_monthly                         = excluded.uvt_monthly,
  sub_agent_cap                       = excluded.sub_agent_cap,
  output_cap                          = excluded.output_cap,
  opus_pct_cap                        = excluded.opus_pct_cap,
  concurrency_cap                     = excluded.concurrency_cap,
  overage_rate_usd_cents_per_million  = excluded.overage_rate_usd_cents_per_million,
  context_budget_tokens               = excluded.context_budget_tokens,
  updated_at                          = now();

-- 2. users — overage + period fields
alter table public.users
  add column if not exists overage_enabled boolean not null default false,
  add column if not exists overage_cap_usd_cents integer,
  add column if not exists current_period_started_at timestamptz not null default now();

comment on column public.users.overage_enabled is
  'When true, quota exhaustion switches to metered billing at plans.overage_rate.';
comment on column public.users.overage_cap_usd_cents is
  'Hard cap on overage charges per period. NULL = no cap (not recommended).';
comment on column public.users.current_period_started_at is
  'Start of the current UVT period. Resets roll every 30 days from this timestamp.';

-- 3. uvt_balances — current-period counters per user
create table if not exists public.uvt_balances (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  period_started_at timestamptz not null,
  period_ends_at timestamptz not null,
  total_uvt  bigint not null default 0 check (total_uvt >= 0),
  haiku_uvt  bigint not null default 0 check (haiku_uvt >= 0),
  sonnet_uvt bigint not null default 0 check (sonnet_uvt >= 0),
  opus_uvt   bigint not null default 0 check (opus_uvt >= 0),
  overage_usd_cents integer not null default 0 check (overage_usd_cents >= 0),
  updated_at timestamptz not null default now(),
  unique (user_id, period_started_at)
);

create index if not exists uvt_balances_user_period_idx
  on public.uvt_balances(user_id, period_started_at desc);

drop trigger if exists uvt_balances_set_updated_at on public.uvt_balances;
create trigger uvt_balances_set_updated_at
  before update on public.uvt_balances
  for each row execute function public.set_updated_at();

alter table public.uvt_balances enable row level security;

comment on table public.uvt_balances is
  'Per-user per-period UVT consumption. total_uvt is the meter the user sees; haiku/sonnet/opus split is the cost ledger for margin analytics. Written only via rpc_record_usage.';

-- 4. usage_events — append-only per-call ledger
create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  task_id uuid,
  model text not null check (model in ('haiku','sonnet','opus','gpt5','gemma')),
  input_tokens integer not null check (input_tokens >= 0),
  output_tokens integer not null check (output_tokens >= 0),
  cached_input_tokens integer not null default 0 check (cached_input_tokens >= 0),
  uvt_counted bigint not null check (uvt_counted >= 0),
  cost_usd_cents_fractional numeric(12,6) not null default 0,
  qopc_load text check (qopc_load in ('light','medium','heavy')),
  created_at timestamptz not null default now()
);

create index if not exists usage_events_user_created_idx
  on public.usage_events(user_id, created_at desc);
create index if not exists usage_events_task_idx
  on public.usage_events(task_id);

alter table public.usage_events enable row level security;

comment on table public.usage_events is
  'Append-only ledger of every model call. One row per TokenAccountant.call(). Drives uvt_balances rollups and Stripe overage invoices. cost_usd_cents_fractional is internal COGS, never billed to user.';

-- 5. tasks — per-task aggregate for UX breakdown panel
create table if not exists public.tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  status text not null default 'pending' check (status in ('pending','running','completed','failed','canceled','right_sized')),
  orchestrator_model text check (orchestrator_model in ('haiku','sonnet','opus','gpt5','gemma')),
  sub_agent_count integer not null default 0 check (sub_agent_count >= 0),
  total_uvt bigint not null default 0 check (total_uvt >= 0),
  qopc_load_final text check (qopc_load_final in ('light','medium','heavy')),
  plan_rewritten boolean not null default false,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists tasks_user_created_idx on public.tasks(user_id, created_at desc);
alter table public.tasks enable row level security;

comment on table public.tasks is
  'Per-task aggregate. Feeds the post-task UX breakdown panel. plan_rewritten=true when PricingGuard right-sized a plan that exceeded tier caps.';

-- 6. rpc_record_usage — atomic commit (event + balance upsert)
create or replace function public.rpc_record_usage(
  p_user_id uuid,
  p_task_id uuid,
  p_model text,
  p_input_tokens integer,
  p_output_tokens integer,
  p_cached_input_tokens integer,
  p_cost_usd_cents_fractional numeric,
  p_qopc_load text
) returns table (
  total_uvt  bigint,
  haiku_uvt  bigint,
  sonnet_uvt bigint,
  opus_uvt   bigint
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uvt bigint := (coalesce(p_input_tokens, 0) - coalesce(p_cached_input_tokens, 0)) + coalesce(p_output_tokens, 0);
  v_period_start timestamptz;
  v_period_end   timestamptz;
begin
  if v_uvt < 0 then v_uvt := 0; end if;

  select current_period_started_at
    into v_period_start
    from public.users
    where id = p_user_id
    for update;

  if v_period_start is null then
    v_period_start := now();
    update public.users set current_period_started_at = v_period_start where id = p_user_id;
  end if;

  v_period_end := v_period_start + interval '30 days';

  insert into public.usage_events (
    user_id, task_id, model, input_tokens, output_tokens,
    cached_input_tokens, uvt_counted, cost_usd_cents_fractional, qopc_load
  ) values (
    p_user_id, p_task_id, p_model, p_input_tokens, p_output_tokens,
    p_cached_input_tokens, v_uvt, p_cost_usd_cents_fractional, p_qopc_load
  );

  insert into public.uvt_balances (
    user_id, period_started_at, period_ends_at,
    total_uvt, haiku_uvt, sonnet_uvt, opus_uvt
  ) values (
    p_user_id, v_period_start, v_period_end,
    v_uvt,
    case when p_model = 'haiku'  then v_uvt else 0 end,
    case when p_model = 'sonnet' then v_uvt else 0 end,
    case when p_model = 'opus'   then v_uvt else 0 end
  )
  on conflict (user_id, period_started_at) do update set
    total_uvt  = public.uvt_balances.total_uvt  + excluded.total_uvt,
    haiku_uvt  = public.uvt_balances.haiku_uvt  + excluded.haiku_uvt,
    sonnet_uvt = public.uvt_balances.sonnet_uvt + excluded.sonnet_uvt,
    opus_uvt   = public.uvt_balances.opus_uvt   + excluded.opus_uvt;

  return query
    select b.total_uvt, b.haiku_uvt, b.sonnet_uvt, b.opus_uvt
    from public.uvt_balances b
    where b.user_id = p_user_id and b.period_started_at = v_period_start;
end;
$$;

revoke all on function public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text) from public;
revoke all on function public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text) from anon, authenticated;

comment on function public.rpc_record_usage is
  'Atomic UVT ledger write: appends usage_events + upserts uvt_balances in one transaction. Returns new balance so caller can short-circuit next call. Callable only by service_role.';
