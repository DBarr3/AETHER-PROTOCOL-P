-- ═══════════════════════════════════════════════════════════════════════════
-- routing_decisions — audit log for PolicyGate decisions (PR 1 v5)
-- 2026-04-22
--
-- Adds:
--   public.routing_decisions (partitioned by created_at, monthly)
--   12 monthly partitions seeded (2026-04 … 2027-03)
--   public.rpc_opus_pct_mtd(uuid) — helper that PolicyGate's caller uses
--                                   to compute opusPctMtd before dispatching
--                                   the routing context
--
-- Notes:
--   - chosen_model stores spec's LOGICAL names (claude-haiku-4, …); no CHECK
--     constraint. Writers targeting usage_events must translate via
--     site/lib/router/model_id_map.ts toShortKey().
--   - predicted_uvt_cost       = weighted formula (spec §2) — logged only
--   - predicted_uvt_cost_simple = Python-parity (input-cached)+output — gates
--   - actual_* columns null in PR 1; reconciliation lands in PR 2.
--   - Composite PK (created_at, id) required by PARTITION BY RANGE.
--
-- Aether Systems LLC — Patent Pending
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. Parent table
create table if not exists public.routing_decisions (
  id                        uuid         not null default gen_random_uuid(),
  created_at                timestamptz  not null default now(),
  user_id                   uuid         not null,
  request_id                text         not null,
  trace_id                  text         not null,
  task_kind                 text         not null
    check (task_kind in ('chat','code_gen','code_review','research',
                         'summarize','classify','agent_plan','agent_execute')),
  tier                      text         not null
    check (tier in ('free','solo','pro','team')),
  chosen_model              text,                               -- null when reason_code='gate_rejected'
  reason_code               text         not null
    check (reason_code in ('default_by_tier_and_task','gate_rejected')),
  gate_error_type           text,                               -- populated when reason_code='gate_rejected'
  gate_cap_key              text,                               -- single cap that tripped
  estimated_input_tokens    integer      not null check (estimated_input_tokens >= 0),
  estimated_output_tokens   integer      not null check (estimated_output_tokens >= 0),
  actual_input_tokens       integer,                            -- PR 2 reconciliation
  actual_output_tokens      integer,                            -- PR 2 reconciliation
  predicted_uvt_cost        integer,                            -- weighted (null if gate_rejected)
  predicted_uvt_cost_simple integer,                            -- simple, Python-parity (null if gate_rejected)
  actual_uvt_cost           integer,                            -- PR 2 reconciliation
  opus_pct_mtd_snapshot     numeric(6,4) not null check (opus_pct_mtd_snapshot >= 0 and opus_pct_mtd_snapshot <= 1),
  active_concurrent_tasks   integer      not null check (active_concurrent_tasks >= 0),
  uvt_balance_snapshot      bigint       not null check (uvt_balance_snapshot >= 0),
  decision_schema_version   integer      not null check (decision_schema_version >= 1),
  uvt_weight_version        integer      not null check (uvt_weight_version >= 1),
  latency_ms                integer      not null check (latency_ms >= 0),
  primary key (created_at, id)
) partition by range (created_at);

comment on table public.routing_decisions is
  'PolicyGate decision audit log. One row per pick() call: success rows carry chosen_model + both predicted UVT costs; gate_rejected rows carry gate_error_type + gate_cap_key instead. Partitioned monthly on created_at.';
comment on column public.routing_decisions.predicted_uvt_cost is
  'Weighted UVT cost from TS computeUvtWeighted (spec §2). Not used for gating in PR 1 (UVT_FORMULA_ENFORCEMENT=simple).';
comment on column public.routing_decisions.predicted_uvt_cost_simple is
  'Simple UVT cost from TS computeUvtSimple = (input-cached)+output. Python-parity. Used for balance gate and opus_pct_mtd arithmetic in PR 1.';

-- 2. Monthly partitions — 12 months from 2026-04-01
do $$
declare
  y int;
  m int;
  start_ym date;
  end_ym   date;
  pname    text;
begin
  for i in 0..11 loop
    start_ym := (date '2026-04-01') + (i || ' month')::interval;
    end_ym   := start_ym + interval '1 month';
    y := extract(year  from start_ym);
    m := extract(month from start_ym);
    pname := format('routing_decisions_y%s_m%s', y, lpad(m::text, 2, '0'));
    execute format(
      'create table if not exists public.%I partition of public.routing_decisions
         for values from (%L) to (%L);',
      pname, start_ym, end_ym
    );
  end loop;
end $$;

-- 3. Indexes
create index if not exists routing_decisions_user_created_idx
  on public.routing_decisions (user_id, created_at desc);
create index if not exists routing_decisions_trace_idx
  on public.routing_decisions (trace_id);
create index if not exists routing_decisions_reason_idx
  on public.routing_decisions (reason_code, created_at desc);
create index if not exists routing_decisions_gate_idx
  on public.routing_decisions (gate_error_type, created_at desc)
  where gate_error_type is not null;

-- 4. RLS — own rows only. Writers use service_role so bypass RLS.
alter table public.routing_decisions enable row level security;

drop policy if exists "own rows" on public.routing_decisions;
create policy "own rows" on public.routing_decisions
  for select using (auth.uid() = user_id);

-- 5. rpc_opus_pct_mtd — helper used by PolicyGate's caller (the API route)
-- to compute opusPctMtd before dispatching the routing context. Returns a
-- fraction 0..1 = (opus uvt MTD) / (total uvt MTD). Zero when the user has
-- no MTD usage yet. Uses the simple formula (Python-parity) stored in
-- usage_events.uvt_counted — matches UVT_FORMULA_ENFORCEMENT=simple.
create or replace function public.rpc_opus_pct_mtd(p_user_id uuid)
returns double precision
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(
    sum(uvt_counted) filter (where model = 'opus')::double precision
    / nullif(sum(uvt_counted), 0),
    0
  )::double precision
  from public.usage_events
  where user_id = p_user_id
    and created_at >= date_trunc('month', now());
$$;

revoke all on function public.rpc_opus_pct_mtd(uuid) from public;
grant execute on function public.rpc_opus_pct_mtd(uuid) to service_role;

comment on function public.rpc_opus_pct_mtd(uuid) is
  'PolicyGate helper — returns fraction 0..1 of MTD UVT spent on Opus for the user. Called from Next.js API route via Supabase service-role client; result feeds RoutingContext.opusPctMtd.';
