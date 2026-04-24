# UVT v2 + OpenAI Provider Integration — Design

| Field | Value |
|---|---|
| **Status** | Draft — pending final review |
| **Date** | 2026-04-24 |
| **Supersedes** | PR2 ("weighted formula flip") from `docs/superpowers/plans/2026-04-22-router-pr1-v5.md` §8 |
| **Target rollout** | Days 0–14 shadow, Day 14 flip, Day 104 full cleanup |
| **Primary owner** | DBarr3 (founder) |
| **Secondary reviewers** | TBD (billing, ops) |

---

## 1. Problem

AetherCloud today bills through a UVT (Unified Value Token) system that:

1. Is **Anthropic-hardcoded**. `DEFAULT_MODEL_BY_TIER_AND_TASK` has no provider axis; `usage_events.model` is a CHECK enum over Anthropic + placeholder names; the sole provider HTTP call lives at `lib/token_accountant.py:145`.
2. Uses a **weighted-tokens** formula (`input=1.0, output=4.0, thinking=5.0, cached=0.1, subagent=250, tool=50, model_multiplier`) that is **not dollar-denominated**. Margin, overhead, and risk buffer are implicit in the weights.
3. Has **no user override** of routing — the router is 100% automatic.

We want to add OpenAI as a first-class provider with correct per-request billing, while letting users (a) accept router defaults by task kind, or (b) configure a custom agent team that overrides defaults.

## 2. Goals & Non-goals

### Goals
- Add OpenAI as a fully-supported provider alongside Anthropic.
- Replace v1 weighted-tokens UVT with a **dollar-native v2 formula** that computes UVT debit from per-model rate-card pricing × margin × overhead.
- Keep internal settlement (`provider_cost_to_uvt_rate`) and external customer billing (`overage_rate_usd_cents_per_million`) **decoupled** — two distinct variables, two layers.
- Support a hybrid A+B routing model: router picks by task when no override, per-agent override takes precedence when set.
- Preserve v1 audit continuity — no data mutation during migration.
- Ship text-only OpenAI at launch; tool use deferred behind flag.

### Non-goals (explicit — out of scope this PR)
- Stripe metered overage wiring (Stage H, separate PR).
- Flipping the old weighted-formula PR2 enforcement (v2 supersedes it).
- OpenAI streaming, tool calling, JSON mode, vision, file input.
- Azure OpenAI endpoint.
- Gemini, Perplexity, or any third provider.
- Per-agent margin override UI (schema + backend land here; UI flagged off).
- Live cost meter in chat UI.
- Cross-provider A/B harness (use `/agent-eval` post-launch).

### Parity invariant (blocks rollout)
A representative Anthropic Sonnet request (8k input + 2k output, no cache) must produce v2 UVT within **±5% median** and **±15% p99** of v1 on the 30-day calibration corpus. Any larger drift is a **product pricing change** requiring its own announcement, not an accounting refactor.

## 3. Architecture Overview

### 3.1 Layered model

```
┌─────────────────────────────────────────────────────────────┐
│ L4 — External billing (UNCHANGED this PR)                   │
│ overage_rate_usd_cents_per_million → Stripe invoice         │
└─────────────────────────────────────────────────────────────┘
                     ▲ (computed monthly)
┌─────────────────────────────────────────────────────────────┐
│ L3 — Internal metering (NEW: v2 dollar-native)              │
│ provider_cost_usd →  per-model rate card                    │
│                   ×  margin_multiplier (resolved)           │
│                   ×  (1 + variable_overhead_pct)            │
│                   ×  provider_cost_to_uvt_rate              │
│                   max( , min_uvt_per_call )                 │
└─────────────────────────────────────────────────────────────┘
                     ▲ (cost from)
┌─────────────────────────────────────────────────────────────┐
│ L2 — Provider execution (NEW: strategy pattern)             │
│ lib/providers/anthropic.py  |  lib/providers/openai.py      │
└─────────────────────────────────────────────────────────────┘
                     ▲ (which provider/model from)
┌─────────────────────────────────────────────────────────────┐
│ L1 — Routing resolution (TS PolicyGate, 3-tier)             │
│ 1. agent_routing_override   (sparse, flagged)               │
│ 2. account_routing_config   (account default team)          │
│ 3. DEFAULT_MODEL_BY_TIER_AND_TASK (static fallback)         │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Canonical naming glossary

| Concept | Name | Location |
|---|---|---|
| Internal $→UVT conversion | `provider_cost_to_uvt_rate` | `uvt_config` table |
| Per-model dollar rate card | `model_pricing.{input,cached_input,output}_usd_per_m` | `model_pricing` table |
| Per-model margin | `model_pricing.margin_multiplier` | same |
| Variable overhead | `variable_overhead_pct` (global) | `uvt_config` |
| Min UVT floor | `min_uvt_per_call` | `uvt_config` |
| Max output hard cap | `model_pricing.default_max_output_tokens` | `model_pricing` |
| Rate-card version | `pricing_version` | `uvt_config` + `model_pricing` |
| Formula version | `uvt_formula_version` | `usage_events` column |

### 3.3 Invariants

1. **Single margin layer.** Margin is resolved via replace-never-multiply: `agent_override → route_override → model.margin_multiplier`. First non-null wins. Never multiplies. CI AST walker blocks `BinOp(Mult, <~margin>, <~margin>)`.
2. **Proportional overhead.** `variable_overhead_pct` (5%) is proportional. Tiny calls not taxed disproportionately. `min_uvt_per_call = 3` floor handles degenerate zero-cost cases.
3. **Parity calibration.** v2 Sonnet UVT must track v1 Sonnet UVT within ±5% median / ±15% p99 on the 30-day Anthropic corpus.
4. **All provider calls go through `lib/providers/*`.** `token_accountant.call()` never calls Anthropic or OpenAI directly.
5. **No silent backfill.** Every `usage_events` row tagged with its `uvt_formula_version` and `pricing_version`.
6. **Fail-closed on unknown model.** Unknown or disabled model → error before any provider call.
7. **DB is the arbiter of billing correctness.** `rpc_record_usage_v2` receives raw tokens, recomputes the full formula, and rejects any writer-supplied `uvt_counted` that disagrees beyond 0.5% tolerance (absorbs FP rounding; catches real bugs).
8. **Decimal, not float, for money.** Python `decimal.Decimal` + PG `numeric(12,6)` with `ROUND_HALF_EVEN`. Precision contract tested in CI.

## 4. Schema Changes (Migrations)

All migrations are **additive and reversible**. Applied in order 1→7. No data mutation.

### 4.1 Migration 1 — `20260424_uvt_v2_pricing.sql`

```sql
-- Primary pricing table (one row per model, current values)
create table public.model_pricing (
  model text primary key,
  provider text not null check (provider in ('anthropic','openai')),
  input_usd_per_m numeric(10,4) not null,
  cached_input_usd_per_m numeric(10,4) not null,   -- REQUIRED (fails load if missing)
  output_usd_per_m numeric(10,4) not null,
  margin_multiplier numeric(4,2) not null check (margin_multiplier >= 1.0),
  fixed_overhead_usd numeric(8,6) default 0,       -- reserved; unused in v2
  overhead_min_tokens integer default 500,         -- reserved; unused in v2
  default_max_output_tokens integer not null,
  enabled boolean not null default true,
  pricing_version integer not null default 1,
  effective_from timestamptz not null default now(),
  created_at timestamptz default now()
);

-- Immutable audit — snapshot of every change
create table public.model_pricing_history (
  id bigserial primary key,
  model text not null,
  provider text not null,
  input_usd_per_m numeric(10,4) not null,
  cached_input_usd_per_m numeric(10,4) not null,
  output_usd_per_m numeric(10,4) not null,
  margin_multiplier numeric(4,2) not null,
  overhead_min_tokens integer,
  default_max_output_tokens integer not null,
  pricing_version integer not null,
  effective_from timestamptz not null,
  effective_to   timestamptz,   -- null = still current
  created_at timestamptz default now()
);

create index idx_model_pricing_history_lookup
  on public.model_pricing_history(model, effective_from desc);

create or replace function public.fn_model_pricing_snapshot() returns trigger
language plpgsql as $$
begin
  update public.model_pricing_history
    set effective_to = now()
    where model = NEW.model and effective_to is null;
  insert into public.model_pricing_history
    (model, provider, input_usd_per_m, cached_input_usd_per_m, output_usd_per_m,
     margin_multiplier, overhead_min_tokens, default_max_output_tokens,
     pricing_version, effective_from)
  values
    (NEW.model, NEW.provider, NEW.input_usd_per_m, NEW.cached_input_usd_per_m,
     NEW.output_usd_per_m, NEW.margin_multiplier, NEW.overhead_min_tokens,
     NEW.default_max_output_tokens, NEW.pricing_version, NEW.effective_from);
  return NEW;
end $$;

create trigger trg_model_pricing_snapshot
  after insert or update on public.model_pricing
  for each row execute function public.fn_model_pricing_snapshot();

-- RLS: read-only to app role; write via service_role only
alter table public.model_pricing enable row level security;
create policy "service_role writes" on public.model_pricing
  for all to service_role using (true) with check (true);
create policy "app reads" on public.model_pricing for select to authenticated using (true);
```

**Seed rows (required; some deprecated-but-grandfathered for FK):**

| model | provider | enabled | notes |
|---|---|---|---|
| `claude-haiku-4` | anthropic | true | current |
| `claude-sonnet-4` | anthropic | true | current |
| `claude-opus-4` | anthropic | true | current |
| `gpt-5.3-chat-latest` | openai | true | new |
| `gpt-5.3-codex` | openai | true | new |
| `gpt-5.5` | openai | **false** | "coming soon" placeholder |
| `haiku`, `sonnet`, `opus`, `gpt5`, `gemma` | varied | false | grandfathered short keys so FK migration succeeds |

Live rate-card values pulled at integration time from OpenAI's pricing page and Anthropic's pricing page — not hardcoded from memory. Business-target values locked via decision-log entry (§14.2).

### 4.2 Migration 2 — `20260424_routing_config.sql`

```sql
-- Reference table for allowed task kinds (data, not enum)
create table public.task_kinds (
  task_kind text primary key,
  description text not null,
  enabled boolean not null default true,
  created_at timestamptz default now()
);

insert into public.task_kinds (task_kind, description) values
  ('chat',      'conversational, multi-turn'),
  ('code_gen',  'code generation and editing'),
  ('research',  'long-form research with tools'),
  ('summarize', 'summarization of provided content'),
  ('classify',  'short structured classification');

-- Account-level default team (one row per user/workspace, sparse)
create table public.account_routing_config (
  user_id uuid primary key references public.users(id) on delete cascade,
  default_team jsonb not null,
  cache_bust_version integer not null default 0,  -- bumped on every UPDATE
  updated_at timestamptz default now(),
  constraint default_team_shape check (jsonb_typeof(default_team) = 'object')
);

-- Per-agent sparse override
create table public.agent_routing_override (
  user_id uuid references public.users(id) on delete cascade,
  agent_id text not null,
  task_kind text not null references public.task_kinds(task_kind),
  model text not null references public.model_pricing(model),
  margin_override numeric(4,2) check (margin_override is null or margin_override >= 1.0),
  updated_at timestamptz default now(),
  primary key (user_id, agent_id, task_kind)
);

-- Validate default_team JSONB keys (task_kinds) + values (models) via trigger
create or replace function public.fn_validate_default_team() returns trigger
language plpgsql as $$
declare
  k text;
  v text;
begin
  for k in select jsonb_object_keys(NEW.default_team) loop
    if not exists (select 1 from public.task_kinds
                   where task_kind = k and enabled = true) then
      raise exception 'unknown_or_disabled_task_kind: %', k using errcode = 'RTC01';
    end if;
    v := NEW.default_team ->> k;
    if not exists (select 1 from public.model_pricing
                   where model = v and enabled = true) then
      raise exception 'unknown_or_disabled_model: %', v using errcode = 'RTC02';
    end if;
  end loop;
  return NEW;
end $$;

create trigger trg_validate_default_team
  before insert or update on public.account_routing_config
  for each row execute function public.fn_validate_default_team();

-- pg_notify on write for cache invalidation (Python long-running listeners)
create or replace function public.fn_notify_routing_config_invalidate() returns trigger
language plpgsql as $$
begin
  perform pg_notify('routing_config_invalidate',
    jsonb_build_object('user_id', NEW.user_id,
                       'agent_id', NEW.agent_id,
                       'task_kind', NEW.task_kind)::text);
  return NEW;
end $$;

create trigger trg_account_routing_notify
  after insert or update on public.account_routing_config
  for each row execute function public.fn_notify_routing_config_invalidate();

create trigger trg_agent_override_notify
  after insert or update or delete on public.agent_routing_override
  for each row execute function public.fn_notify_routing_config_invalidate();
```

### 4.3 Migration 3 — `20260424_usage_events_v2.sql`

Drops the old CHECK enum, establishes FK to `model_pricing`, adds v2 accounting columns. **Prerequisite:** Migration 1 must seed deprecated short keys with `enabled=false` before this runs, or the FK fails.

```sql
alter table public.usage_events drop constraint usage_events_model_check;

alter table public.usage_events add constraint usage_events_model_fk
  foreign key (model) references public.model_pricing(model)
  on update cascade on delete restrict;

alter table public.usage_events add column provider text
  check (provider in ('anthropic','openai'));

alter table public.usage_events
  add column uvt_formula_version integer default 1,
  add column pricing_version integer,
  add column margin_applied numeric(4,2),
  add column actual_billable_usd numeric(12,6),
  add column predicted_uvt_cost_v2 bigint,
  add column prediction_drift_pct numeric(6,4);

create index idx_usage_events_provider_created
  on public.usage_events(provider, created_at desc);

-- v1 rows keep uvt_formula_version=1, margin_applied NULL, etc. Never backfill.
```

### 4.4 Migration 4 — `20260424_uvt_balances_provider_breakdown.sql`

**Rollout order matters:** app deploy must stop writing to `total_uvt` before this migration applies (generated columns reject direct writes).

```sql
alter table public.uvt_balances
  add column anthropic_uvt bigint default 0 not null,
  add column openai_uvt bigint default 0 not null;

alter table public.uvt_balances drop column total_uvt;
alter table public.uvt_balances
  add column total_uvt bigint generated always as (anthropic_uvt + openai_uvt) stored;

create or replace function public.fn_uvt_balance_shadow_check() returns trigger
language plpgsql as $$
begin
  if (NEW.haiku_uvt + NEW.sonnet_uvt + NEW.opus_uvt) <> NEW.anthropic_uvt then
    perform pg_notify('uvt_shadow_drift',
      jsonb_build_object('user_id', NEW.user_id,
                         'legacy_sum', NEW.haiku_uvt + NEW.sonnet_uvt + NEW.opus_uvt,
                         'anthropic_uvt', NEW.anthropic_uvt)::text);
  end if;
  return NEW;
end $$;

create trigger trg_uvt_balance_shadow_check
  after insert or update on public.uvt_balances
  for each row execute function public.fn_uvt_balance_shadow_check();
```

Legacy `haiku_uvt/sonnet_uvt/opus_uvt` retained through Day 104; dropped in cleanup migration.

### 4.5 Migration 5 — `20260424_rpc_record_usage_v2.sql`

**Full arbiter.** RPC accepts raw tokens, recomputes the full formula server-side, rejects any writer-supplied `uvt_counted` that disagrees.

```sql
create or replace function public.rpc_record_usage_v2(
  p_user_id uuid, p_task_id uuid,
  p_agent_id text, p_route text,
  p_provider text, p_model text,
  p_input_tokens integer, p_output_tokens integer, p_cached_input_tokens integer,
  p_uvt_formula_version integer
) returns public.uvt_balances language plpgsql security definer as $$
declare
  v_pricing public.model_pricing%rowtype;
  v_override public.agent_routing_override%rowtype;
  v_rate numeric; v_overhead numeric; v_min_uvt bigint;
  v_uncached integer; v_cost_usd numeric(12,6);
  v_margin numeric(4,2); v_billable_usd numeric(12,6);
  v_uvt_debit bigint;
  v_balance public.uvt_balances%rowtype;
begin
  -- Fail-closed on unknown/disabled model
  select * into v_pricing from public.model_pricing
    where model = p_model and enabled = true;
  if not found then
    raise exception 'unknown_or_disabled_model: %', p_model using errcode = 'UVT01';
  end if;
  if v_pricing.provider <> p_provider then
    raise exception 'provider_model_mismatch: expected % got %',
      v_pricing.provider, p_provider using errcode = 'UVT02';
  end if;

  -- Load v2 constants
  select value into v_rate from public.uvt_config where key='provider_cost_to_uvt_rate';
  select value into v_overhead from public.uvt_config where key='variable_overhead_pct';
  select value::bigint into v_min_uvt from public.uvt_config where key='min_uvt_per_call';

  -- Compute provider cost
  v_uncached := greatest(0, p_input_tokens - p_cached_input_tokens);
  v_cost_usd := round(
      (v_uncached::numeric * v_pricing.input_usd_per_m / 1000000)
    + (p_cached_input_tokens::numeric * v_pricing.cached_input_usd_per_m / 1000000)
    + (p_output_tokens::numeric * v_pricing.output_usd_per_m / 1000000),
    6);

  -- Resolve margin: agent_override > model.margin_multiplier (replace-never-multiply)
  if p_agent_id is not null then
    select * into v_override from public.agent_routing_override
      where user_id = p_user_id and agent_id = p_agent_id and task_kind = p_route;
  end if;
  v_margin := coalesce(v_override.margin_override, v_pricing.margin_multiplier);
  if v_margin < 1.0 then
    raise exception 'margin_below_floor: %', v_margin using errcode = 'UVT03';
  end if;

  -- Billable USD and UVT debit
  v_billable_usd := round(v_cost_usd * (1.0 + v_overhead) * v_margin, 6);
  v_uvt_debit := greatest(v_min_uvt, ceil(v_billable_usd * v_rate)::bigint);

  -- Atomic debit
  insert into public.uvt_balances
    (user_id, period_started_at, period_ends_at, anthropic_uvt, openai_uvt)
  values
    (p_user_id, date_trunc('month', now()),
     date_trunc('month', now()) + interval '1 month' - interval '1 second',
     case when p_provider='anthropic' then v_uvt_debit else 0 end,
     case when p_provider='openai'    then v_uvt_debit else 0 end)
  on conflict (user_id, period_started_at) do update set
    anthropic_uvt = public.uvt_balances.anthropic_uvt +
                    case when p_provider='anthropic' then v_uvt_debit else 0 end,
    openai_uvt    = public.uvt_balances.openai_uvt +
                    case when p_provider='openai'    then v_uvt_debit else 0 end,
    updated_at = now()
  returning * into v_balance;

  -- Append usage_events row
  insert into public.usage_events
    (user_id, task_id, provider, model,
     input_tokens, output_tokens, cached_input_tokens,
     uvt_counted, cost_usd_cents_fractional,
     uvt_formula_version, pricing_version, margin_applied, actual_billable_usd)
  values
    (p_user_id, p_task_id, p_provider, p_model,
     p_input_tokens, p_output_tokens, p_cached_input_tokens,
     v_uvt_debit, v_cost_usd * 100,
     p_uvt_formula_version, 1, v_margin, v_billable_usd);

  return v_balance;
end $$;
```

v1 `rpc_record_usage` retained — switched by feature flag `UVT_V2_ENFORCEMENT`. Cleanup at Day 104.

### 4.6 Migration 6 — `20260424_routing_decisions_v2.sql`

```sql
alter table public.routing_decisions
  add column chosen_provider text check (chosen_provider in ('anthropic','openai')),
  add column resolved_via text check (resolved_via in
      ('agent_override','account_default','system_fallback',
       'provider_tool_fallback','v1_legacy')),
  add column predicted_uvt_cost_v2 bigint,
  add column predicted_billable_usd numeric(12,6),
  add column predicted_margin_applied numeric(4,2),
  add column pricing_version integer,
  add column fell_back_from_openai boolean default false,
  add column decision_schema_version integer default 2;

alter table public.routing_decisions add constraint provider_tool_fallback_consistency
  check (
    (resolved_via <> 'provider_tool_fallback') OR
    (fell_back_from_openai = true AND chosen_provider = 'anthropic')
  );

create index idx_routing_decisions_provider_created
  on public.routing_decisions(chosen_provider, created_at desc);
create index idx_routing_decisions_resolved_via
  on public.routing_decisions(resolved_via, created_at desc);
```

### 4.7 Migration 7 — `20260424_uvt_config.sql`

```sql
create table public.uvt_config (
  key text primary key,
  value numeric not null,
  pricing_version integer not null,
  updated_at timestamptz default now()
);

-- Pricing-math domain
insert into public.uvt_config values
  ('provider_cost_to_uvt_rate', 333.0,  1, now()),   -- calibrated pre-flip (placeholder)
  ('min_uvt_per_call',          3,      1, now()),
  ('variable_overhead_pct',     0.05,   1, now()),
  ('decimal_rounding_mode_code', 6,     1, now()),   -- 6 = ROUND_HALF_EVEN
  ('usd_fractional_digits',     6,      1, now()),
  ('pct_fractional_digits',     4,      1, now());

-- Rollout/ops domain
insert into public.uvt_config values
  ('shadow_min_days',             14,   1, now()),
  ('shadow_min_samples_per_cell', 1000, 1, now()),
  ('shadow_drift_p50_threshold',  0.05, 1, now()),
  ('shadow_drift_p99_threshold',  0.15, 1, now()),
  ('v2_parity_gate_passed_at',    0,    1, now());

create or replace function public.rpc_invalidate_model_pricing_cache() returns void
language plpgsql security definer as $$
begin
  perform pg_notify('model_pricing_invalidate', now()::text);
end $$;
```

**Split trigger** (§12 open decision): split into `uvt_pricing_config` vs `uvt_rollout_config` when we add a key belonging to the **opposite domain of the most-recently-added key** — not an arbitrary count threshold.

### 4.8 Rollback

Migrations drop cleanly in reverse order. No data mutation means no reverse-migration complexity. Retained through Day 104:
- v1 `rpc_record_usage`
- Legacy `haiku_uvt/sonnet_uvt/opus_uvt` columns

Dropped at Day 21 cleanup:
- `usage_events_v2_shadow` table

## 5. Provider Module

### 5.1 Directory layout

```
lib/
├── providers/
│   ├── __init__.py        # PROVIDER_REGISTRY, flag-gated adapter registration
│   ├── base.py            # ProviderAdapter protocol, RetryPolicy, ProviderResponse
│   ├── anthropic.py       # current HTTP call extracted from token_accountant
│   ├── openai.py          # NEW
│   ├── pricing.py         # ModelPricing cache, 5-min TTL, pg_notify invalidation
│   └── types.py           # ProviderRequest, TokenUsage
├── token_accountant.py    # ORCHESTRATOR ONLY — dispatches to providers/*
└── pricing_v2.py          # FORMULA SOURCE OF TRUTH
                           # - compute_provider_cost_usd
                           # - resolve_margin  (replace-never-multiply)
                           # - provider_cost_usd_to_uvt
                           # All Decimal-aware; quantize at boundaries.
```

### 5.2 ProviderAdapter protocol

```python
# lib/providers/base.py
class ProviderAdapter(Protocol):
    name: Literal["anthropic", "openai"]

    async def call(self, *, model: str, messages: list[dict],
                   system: str | None, tools: list[dict] | None,
                   max_output_tokens: int,
                   request_id: str, trace_id: str) -> ProviderResponse: ...

    def supports_cached_input(self) -> bool: ...
    def supports_tools(self) -> bool: ...

@dataclass
class ProviderResponse:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    raw_response: dict
    model_returned: str
    finish_reason: Literal["stop", "length", "tool_use", "error"]  # canonical
    raw_finish_reason: str                                          # audit only

@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
    honor_retry_after: bool = True
    honor_provider_reset_headers: list[str] = field(default_factory=list)
    retry_on_statuses: set[int] = field(default_factory=lambda: {429,500,502,503,504})
    dlq_on_final_failure: bool = True

# Critical: on 5xx, check response body for populated usage.
# If tokens were consumed, DO NOT RETRY — record usage once, raise ProviderIncompleteError.
```

### 5.3 Anthropic adapter

Lift the existing HTTP call from `lib/token_accountant.py:145` verbatim into `lib/providers/anthropic.py`. No behavior change.

```python
ANTHROPIC_RETRY = RetryPolicy(
    honor_provider_reset_headers=[
        "anthropic-ratelimit-requests-reset",
        "anthropic-ratelimit-input-tokens-reset"],
)
```

### 5.4 OpenAI adapter

```python
# lib/providers/openai.py
_OPENAI_URL_DEFAULT = "https://api.openai.com/v1/chat/completions"

_PER_MODEL_PARAMS = {
    "gpt-5.3-chat-latest": {"max_output_key": "max_tokens",
                            "supports_temperature": True,
                            "supports_reasoning_effort": False},
    "gpt-5.3-codex":       {"max_output_key": "max_completion_tokens",
                            "supports_temperature": True,
                            "supports_reasoning_effort": False},
    "gpt-5.5":             {"max_output_key": "max_completion_tokens",
                            "supports_temperature": False,
                            "supports_reasoning_effort": True},
}

class OpenAIAdapter:
    name = "openai"
    def __init__(self, api_key: str, base_url: str | None = None):
        self._api_key = api_key
        self._url = base_url or _OPENAI_URL_DEFAULT

    async def call(self, *, model, messages, system, tools, max_output_tokens,
                   request_id, trace_id) -> ProviderResponse:
        params = _PER_MODEL_PARAMS[model]
        payload = {
            "model": model,
            "messages": ([{"role":"system","content":system}] if system else []) + messages,
            params["max_output_key"]: max_output_tokens,
        }
        # tools disabled at launch; supports_tools() returns False
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await _retry_loop(OPENAI_RETRY, client, self._url,
                                     headers=self._headers(request_id, trace_id),
                                     json=payload)
        body = resp.json()
        usage = body["usage"]
        return ProviderResponse(
            input_tokens=usage["prompt_tokens"],
            output_tokens=usage["completion_tokens"],
            cached_input_tokens=usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
            raw_response=body,
            model_returned=body["model"],
            finish_reason=_normalize_finish(body["choices"][0]["finish_reason"]),
            raw_finish_reason=body["choices"][0]["finish_reason"],
        )

    def supports_cached_input(self) -> bool: return True
    def supports_tools(self) -> bool: return False

OPENAI_RETRY = RetryPolicy(
    honor_provider_reset_headers=["x-ratelimit-reset-requests","x-ratelimit-reset-tokens"],
)

def _normalize_finish(raw: str) -> str:
    mapping = {"stop":"stop", "length":"length", "tool_calls":"tool_use",
               "content_filter":"error", "function_call":"tool_use"}
    if raw not in mapping:
        raise ProviderSchemaError(f"unknown openai finish_reason: {raw}")
    return mapping[raw]
```

### 5.5 Max-output enforcement — loud reject

```python
# lib/token_accountant.py orchestrator
pricing = model_pricing_cache.get(model)
if not pricing or not pricing.enabled:
    raise UnknownOrDisabledModelError(model)

if requested_max_tokens and requested_max_tokens > pricing.default_max_output_tokens:
    raise OutputCapExceededError(
        requested=requested_max_tokens,
        cap=pricing.default_max_output_tokens,
        model=model)

max_out = requested_max_tokens or pricing.default_max_output_tokens
```

Never silently truncates. `OutputCapExceededError` maps to HTTP 413.

### 5.6 Cache invalidation — asymmetric by runtime

| Runtime | Cache | Invalidation |
|---|---|---|
| Python (long-running FastAPI) | in-proc dict, 5-min TTL | `LISTEN model_pricing_invalidate` (pg_notify) |
| TS (Next.js serverless on Vercel) | LRU per instance, 60s TTL | **no broadcast** — best-effort eventual consistency. Cache key includes `account_routing_config.cache_bust_version` so write-then-read sees fresh data. |

Document the 60s SLA on the TS side explicitly in runbook.

### 5.7 Env vars

```bash
OPENAI_PROVIDER_ENABLED=0          # master flag
OPENAI_API_KEY=sk-...              # required if enabled
OPENAI_API_KEY_NEXT=               # optional, for rotation (see §10.8)
OPENAI_BASE_URL=                   # optional override
OPENAI_ORG_ID=
OPENAI_TOOLS_ENABLED=0             # ship text-only at launch
```

Boot-time assertion:
```python
if OPENAI_PROVIDER_ENABLED and not OPENAI_API_KEY:
    raise StartupError("OPENAI_PROVIDER_ENABLED=1 but OPENAI_API_KEY unset")
```

## 6. UVT v2 Formula + Calibration

### 6.1 The formula (source of truth: `lib/pricing_v2.py`)

```python
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

USD_QUANT = Decimal("0.000001")    # numeric(12,6)
PCT_QUANT = Decimal("0.0001")
RATE_QUANT = Decimal("0.01")

def _q_usd(x: Decimal) -> Decimal:
    return x.quantize(USD_QUANT, rounding=ROUND_HALF_EVEN)

def compute_provider_cost_usd(pricing: ModelPricing,
                              input_tokens: int,
                              cached_input_tokens: int,
                              output_tokens: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28
        ctx.rounding = ROUND_HALF_EVEN
        uncached = max(0, input_tokens - cached_input_tokens)
        raw = (
            Decimal(uncached) * pricing.input_usd_per_m / 1_000_000
          + Decimal(cached_input_tokens) * pricing.cached_input_usd_per_m / 1_000_000
          + Decimal(output_tokens) * pricing.output_usd_per_m / 1_000_000
        )
        return _q_usd(raw)

def resolve_margin(model_margin: Decimal,
                   route_override: Decimal | None,
                   agent_override: Decimal | None) -> Decimal:
    """Replace, never multiply. First non-None wins."""
    if agent_override is not None: return agent_override
    if route_override is not None: return route_override
    return model_margin

def provider_cost_usd_to_uvt(provider_cost_usd: Decimal,
                             margin: Decimal,
                             overhead_pct: Decimal,
                             rate: Decimal,
                             min_uvt: int) -> tuple[int, Decimal]:
    billable_usd = _q_usd(provider_cost_usd * (Decimal(1) + overhead_pct) * margin)
    raw_uvt = billable_usd * rate
    uvt_debit = max(min_uvt, math.ceil(raw_uvt))
    return uvt_debit, billable_usd
```

### 6.2 Constants (in `uvt_config` table)

| Key | Initial | How derived |
|---|---|---|
| `provider_cost_to_uvt_rate` | calibrated (placeholder 333.0) | Regression on Anthropic corpus (§6.3) |
| `min_uvt_per_call` | 3 | Business call |
| `variable_overhead_pct` | 0.05 | 5% for retries + logging + moderation |
| `decimal_rounding_mode_code` | 6 | ROUND_HALF_EVEN |
| `usd_fractional_digits` | 6 | numeric(12,6) |
| `pct_fractional_digits` | 4 | numeric(6,4) |

### 6.3 Calibration procedure (one-time, pre-flip)

```
Step 1. CORPUS  (scripts/calibrate_v2.py)
  Export last 30 days of Anthropic routing_decisions + usage_events joined.
    anonymize: strip user_id, task_id, trace_id, agent_id, session_id
    created_at → hour bucket
    keep: task_kind, model, provider, tokens (in/out/cached), v1_uvt, v1_cost_usd
  Write to tests/pricing/corpus/<month>_<model>.jsonl  (gitignored)
  Upload to s3://aethercloud-calibration-corpus/<month>/
  CI role has read-only access.

Step 2. FIX    min_uvt_per_call = 3 (business)
Step 3. FIX    variable_overhead_pct = 0.05 (ops)

Step 4. REGRESS provider_cost_to_uvt_rate:
  candidates = [250, 275, 300, 325, 333, 350, 375, 400, 450, 500]
  for c in candidates:
    deltas = [(v2_uvt(row, rate=c) - row.v1_uvt)/row.v1_uvt for row in corpus]
    median_signed = statistics.median(deltas)   # SIGNED
    p99_abs = numpy.percentile(numpy.abs(deltas), 99)
    if abs(median_signed) > 0.02: continue       # bias gate (tighter)
    if p99_abs > 0.15: continue                  # spread gate
    candidates_passing.append((c, median_signed, p99_abs))
  best = min(candidates_passing,
             key=lambda x: (abs(x[1]), x[2], abs(x[0] - 333.0)))
  # bias first, spread second, doc-coherence tiebreaker third.

Step 5. LOCK (rate, overhead_pct, min_uvt) into uvt_config with pricing_version=1.

Step 6. COMMIT regression run log to repo under tests/pricing/calibration-runs/.
```

**Asymmetric gates are intentional** — bias gate (2%) tighter than spread gate (15%) because systematic undercharge compounds forever while outliers are tolerable variance.

### 6.4 CI parity gates (block merge)

```python
# tests/pricing/test_v2_parity.py
def test_v2_median_drift_sonnet():  assert abs(stats.median(_deltas("sonnet-4"))) < 0.05
def test_v2_p99_drift_sonnet():     assert abs(np.percentile(_deltas("sonnet-4"),99)) < 0.15
def test_v2_median_drift_haiku():   ...
def test_v2_median_drift_opus():    ...

# tests/pricing/test_openai_business_targets.py — floor + ceiling (both enforced)
BUSINESS_TARGETS = {
    ("gpt-5.3-chat-latest","chat"):  {"input":2000,"output":800,  "min":12,"max":25},
    ("gpt-5.3-codex","code_gen"):    {"input":8000,"output":2500, "min":90,"max":180},
}
def test_openai_routes_within_business_targets(): ...

# tests/pricing/test_no_margin_compounding_ast.py — AST walker
# Catches BinOp(Mult, <identifier-containing-'margin'>, <same>) across
# Attribute, Subscript, and Name access forms. Not regex.

# tests/pricing/test_decimal_contract.py — PG↔Python round-trip preserves 6th digit
```

### 6.5 Edge cases

| Input | Behavior |
|---|---|
| `cached > input` | Clamp: `uncached = max(0, input - cached)`. Log warning, don't error. |
| `output == 0` | Charge `min_uvt_per_call` if `input > 0`, else zero. |
| `provider_cost_usd == 0` | Charge `min_uvt_per_call`. |
| `margin < 1.0` | Reject at RPC via `UVT03`. DB CHECK also enforces. |
| `pricing_version` drift (app cache vs RPC) | RPC errors → app reloads cache → retry once. |
| `cached_input_usd_per_m` missing | Reject at load time. No implicit fresh-input pricing. |

### 6.6 Shadow mode + dynamic extension

```
Day 0: deploy. Flag state SHADOW=1, ENFORCEMENT=0.
Day 1-13: shadow job (async fire-and-forget) writes usage_events_v2_shadow rows.
         Never awaited on request path. Shadow exceptions alarm, never propagate.
Day 14 gate: every (model × task_kind) cell must be:
  EITHER n >= shadow_min_samples_per_cell AND drifts within thresholds
  OR     n < shadow_min_samples_per_cell AND daily volume < 10/day
If any cell drift_exceeded → pause indefinitely, root-cause.
If any cell insufficient_samples with >10/day volume → extend by 7 days.
```

Query (daily during shadow):
```sql
select task_kind, chosen_model, count(*) n,
       percentile_cont(0.5) within group (order by abs(drift_pct)) p50,
       percentile_cont(0.99) within group (order by abs(drift_pct)) p99,
       case
         when count(*) < 1000 then 'insufficient_samples'
         when percentile_cont(0.99) within group (order by abs(drift_pct)) > 0.15 then 'drift_exceeded'
         when percentile_cont(0.5)  within group (order by abs(drift_pct)) > 0.05 then 'drift_exceeded'
         else 'ready_to_flip'
       end as flip_gate_status
from usage_events_v2_shadow
where created_at >= now() - interval '14 days'
group by 1,2;
```

### 6.7 `usage_events_v2_shadow` table (drops at Day 21)

```sql
create table public.usage_events_v2_shadow (
  source_event_id uuid references public.usage_events(id),
  v1_uvt bigint,
  v2_uvt_predicted bigint,
  drift_pct numeric(6,4),
  pricing_version integer,
  created_at timestamptz default now()
);
```

Shadow compute posted asynchronously:
```python
asyncio.create_task(
    _shadow_compute_v2(event_id=committed.id, ...)
)  # fire-and-forget — never awaited on request path
```

## 7. Router Resolution + Audit

### 7.1 Resolution order (TS PolicyGate)

```
Input: (user_id, agent_id, task_kind, tier)

1. agent_routing_override[user_id, agent_id, task_kind] → {model, margin_override?}
   miss ↓
2. account_routing_config[user_id].default_team[task_kind] → {model}
   miss ↓
3. DEFAULT_MODEL_BY_TIER_AND_TASK[tier][task_kind]   (static)

Provider derived from model_pricing.model → provider (cache).

Tool-fallback:
  if provider=openai AND task.requires_tools AND OPENAI_TOOLS_ENABLED=0:
    model = DEFAULT_MODEL_BY_TIER_AND_TASK[tier][task_kind]
    provider = "anthropic"
    resolved_via = "provider_tool_fallback"
    posthog.capture("provider_tool_fallback", {...})
```

### 7.2 `RoutingDecision` v2 shape

```typescript
interface RoutingDecisionV2 {
  chosen_model: string;
  chosen_provider: "anthropic" | "openai";
  resolved_via: "agent_override" | "account_default" | "system_fallback"
              | "provider_tool_fallback" | "v1_legacy";
  reason_code: string;
  predicted_uvt_cost_simple: number;    // v1 retained through Day 104
  predicted_uvt_cost_v2: number;
  predicted_billable_usd: string;       // Decimal serialized — string, never float
  predicted_margin_applied: string;
  pricing_version: number;
  uvt_formula_version: 2;
  decision_schema_version: 2;
  fell_back_from_openai: boolean;
  latency_ms: number;
}
```

### 7.3 TS cache

```typescript
const agentOverrideCache = new LRU<string, AgentOverride | null>({ max: 5000, ttl: 60_000 });
const accountDefaultCache = new LRU<string, AccountDefault | null>({ max: 2000, ttl: 60_000 });
// Keys: `${user_id}:${agent_id}:${task_kind}` and `${user_id}`.
// Negative cache on miss. Write-then-read via cache_bust_version in key.
// NO realtime broadcast on TS side (serverless). 60s TTL is the SLA.
// Python router uses LISTEN routing_config_invalidate for near-instant invalidation.
```

### 7.4 v1 tolerant parsers

```python
def _parse_v2_tolerant(row: dict) -> RoutingDecisionV2:
    """v1-shaped row → v2 with legacy sentinel, no fabricated data."""
    if row.get("decision_schema_version", 1) == 1:
        return RoutingDecisionV2(
            chosen_model=row["chosen_model"],
            chosen_provider="anthropic",           # historical truth
            resolved_via="v1_legacy",              # do NOT label as system_fallback
            predicted_uvt_cost_v2=None,
            decision_schema_version=1,
            ...
        )
    return _parse_strict_v2(row)

def _parse_v1_tolerant(row: dict) -> RoutingDecisionV1:
    """v2 row during rollback → v1 parser. Extra fields ignored, not errored."""
    # pydantic extra='allow' on v1 parser; fails cleanly on missing required v1 fields
```

### 7.5 Analytics rule (runbook)

> Analytical queries grouping by `resolved_via` MUST either
> `WHERE decision_schema_version = 2` or explicitly handle the `v1_legacy` bucket.
> Dashboard builders: add a global "data era" filter pinned to v2-only by default.

## 8. UI (Minimum Viable for A+B Hybrid)

### Ships (behind `ACCOUNT_ROUTING_UI_ENABLED=0` at launch, flipped Day 14):
- **Account Settings → "Model Defaults"** page
- Per-task-kind dropdowns, options from `model_pricing WHERE enabled=true`
- Labeled `Claude Sonnet 4 (Anthropic)`, `GPT-5.3 Codex (OpenAI)`, etc.
- UVT-cost estimate badge per option: "~18 UVT / typical request" from business targets
- Save writes `account_routing_config.default_team`
- Reset-to-defaults clears row
- Task kinds loaded live from `task_kinds` table

### Deferred (scaffolded, flagged off):
- Per-agent override page (same pattern, `AGENT_ROUTING_UI_ENABLED=0`)
- Margin-override input (sub-flag, power-user only)

### Explicitly NOT in scope:
- Live cost meter during chat (requires streaming; separate PR)
- Model comparison view (use `/agent-eval` post-launch)
- Provider outage status page (ops dashboard)

## 9. Testing Matrix

### Unit (Python)

| File | Asserts |
|---|---|
| `tests/pricing/test_pricing_v2_formula.py` | Formula output on fixed inputs |
| `tests/pricing/test_resolve_margin.py` | Override chain, replace-never-multiply |
| `tests/pricing/test_decimal_contract.py` | Python↔PG round-trip preserves 6th digit |
| `tests/pricing/test_no_margin_compounding_ast.py` | AST walk rejects `margin*margin` across dict/attr/name forms |
| `tests/pricing/test_v2_parity_sonnet.py` | Signed median <2%, p99 <15% on Anthropic corpus |
| `tests/pricing/test_openai_business_targets.py` | Floor + ceiling enforced per model × task |
| `tests/pricing/test_edge_cases.py` | cached>input; zero-output min_uvt; margin<1.0; pricing_version drift |
| `tests/providers/test_anthropic_adapter.py` | Extract + expand from existing `test_token_accountant.py` |
| `tests/providers/test_openai_adapter.py` | Happy path, 429+Retry-After, 5xx-with-usage no-retry |
| `tests/providers/test_output_cap_loud_reject.py` | `OutputCapExceededError` raised, never silent truncation |
| `tests/router/test_resolution_order.py` | agent_override > account_default > system_fallback |
| `tests/router/test_provider_tool_fallback.py` | Flag off + tool-needing task → Anthropic + PostHog |

### Integration (local Supabase)

| File | Asserts |
|---|---|
| `tests/integration/test_rpc_record_usage_v2.py` | Full recompute from raw tokens; rejects forged values |
| `tests/integration/test_model_pricing_history_trigger.py` | UPDATE writes history row with `effective_to` |
| `tests/integration/test_account_routing_config_trigger.py` | Unknown task_kind OR model → rejected |
| `tests/integration/test_usage_events_fk.py` | INSERT unknown model fails at DB |
| `tests/integration/test_routing_decisions_fallback_constraint.py` | provider_tool_fallback invariant |

### Schema (TS)

| File | Asserts |
|---|---|
| `site/tests/unit/router.resolution.test.ts` | Resolution order, fallback events |
| `site/tests/unit/router.cache.test.ts` | LRU hit/miss; cache_bust_version bumps on writes |
| `site/tests/integration/router.pick.api.test.ts` | v2 shape serializes/deserializes |
| `site/tests/unit/router.decision_schema_version.test.ts` | v1 tolerant parse, v2 parse, v1_legacy sentinel |

### Ops (Grafana/PostHog)

- v2 vs v1 drift p50/p99 by (model, task_kind)
- Samples per cell (red below 1000)
- `provider_tool_fallback` rate
- `model_pricing_cache_age_seconds` (alarm >600)
- `shadow_task_exception_rate` (alarm >1%)
- `prediction_drift_pct` p99 (alarm >20%)

## 10. Rollout

### 10.1 Feature flag matrix

| Flag | Default | Controls | Flip order |
|---|---|---|---|
| `OPENAI_PROVIDER_ENABLED` | 0 | Adapter registration | 1st (prereq) |
| `OPENAI_API_KEY` | unset | Required when enabled | 1st |
| `UVT_V2_SHADOW_MODE` | 0 | Shadow table writes | 2nd (Day 0) |
| `ROUTING_AGENT_OVERRIDE_ENABLED` | 0 | Agent override lookup | **Stays 0 this PR** — backend + schema ship; UI and flip deferred to follow-up |
| `UVT_V2_ENFORCEMENT` | 0 | Switch to v2 RPC | 4th (Day 14) |
| `ACCOUNT_ROUTING_UI_ENABLED` | 0 | UI writes/reads | 4th (Day 14) |
| `OPENAI_TOOLS_ENABLED` | 0 | Tool calling on OpenAI | separate PR |

### 10.2 Boot-time assertions

```python
if OPENAI_PROVIDER_ENABLED and not OPENAI_API_KEY:
    raise StartupError("OPENAI_PROVIDER_ENABLED=1 but OPENAI_API_KEY unset")

if UVT_V2_ENFORCEMENT and not UVT_V2_SHADOW_MODE:
    raise StartupError("Cannot enforce v2 without shadow mode ever having run")

if UVT_V2_ENFORCEMENT:
    gate_passed_at = uvt_config.get("v2_parity_gate_passed_at", 0)
    if gate_passed_at == 0:
        raise StartupError("Parity gate never recorded as passing")
    if datetime.now(UTC) - datetime.fromtimestamp(gate_passed_at, UTC) > timedelta(days=60):
        raise StartupError("Parity gate is stale — re-run before enforcement")
```

### 10.3 Timeline

```
─────────── Day -7 (Prep) ───────────
• Migrations 1-7 applied to staging.
• Seed model_pricing with live rates + grandfathered short keys.
• Run scripts/calibrate_v2.py against staging snapshot.
• Write docs/pricing/decisions/2026-04-24-business-targets-v1.md.
• Team review rollback runbook.

─────────── Day 0 (Shadow on) ───────────
• Merge PR. Deploy.
• Flag state: SHADOW=1, V2_ENFORCEMENT=0, OPENAI_ENABLED=0.
• v1 handles all traffic. Shadow async-writes to usage_events_v2_shadow.

─────────── Day 1-6 (Watch) ───────────
• Daily rollout_health_check.py posts to Slack.
• Drift dashboard review.
• Pause if any cell drift_exceeded.

─────────── Day 7 (Staging smoke) ───────────
• OPENAI_PROVIDER_ENABLED=1 in staging. E2E smoke against gpt-5.3-chat-latest.
• Prod remains shadow-only.

─────────── Day 14 (Flip gate) ───────────
• rollout_health_check.py must pass.
• Every populated cell: ready_to_flip.
• Operator writes v2_parity_gate_passed_at = now() to uvt_config.
• Flip UVT_V2_ENFORCEMENT=1 + OPENAI_PROVIDER_ENABLED=1 + ACCOUNT_ROUTING_UI_ENABLED=1.
• 4h on-call standby. First 100 OpenAI requests: manual spot-check.

─────────── Day 21 (Partial cleanup) ───────────
• Drop usage_events_v2_shadow.
• RETAIN rpc_record_usage (v1) and legacy balance columns through Day 104.

─────────── Day 30+ (Measure) ───────────
• /agent-eval: gpt-5.3-codex vs claude-opus-4 on code_gen benchmark.
• Quarterly calibration refresh.

─────────── Day 104 (Full cleanup) ───────────
• If no rollbacks: drop rpc_record_usage (v1), legacy balance columns.
• Ship 20260806_drop_v1_accounting_legacy.sql.
```

### 10.4 Health-check gate (daily during shadow)

`scripts/rollout_health_check.py` requires all of:
- No P0/P1 incident in last 72h
- Anthropic error rate p99 < 2% over last hour
- OpenAI error rate p99 < 2% over last hour
- Supabase p99 latency < 300ms over last hour
- Shadow task exception rate < 1% over last 24h
- DLQ depth < 100

Any blocker → phase transition auto-defers 24h; named operator (DBarr3) re-confirms.

### 10.5 No-go windows

Phase transitions (Days 0, 7, 14) must not occur when any of:
- P0/P1 incident in last 72h
- Pricing change deployed in last 7 days
- Marketing launch within next 72h
- Quarterly financial close within 5 business days
- Major dependency (Anthropic/OpenAI/Supabase/Vercel) has active incident

Violation → delay phase min 72h, re-check.

### 10.6 Kill switches

| Symptom | Action | Blast radius |
|---|---|---|
| OpenAI API outage | `OPENAI_PROVIDER_ENABLED=0` | OpenAI routes → Anthropic fallback |
| v2 drift exceeding threshold | `UVT_V2_ENFORCEMENT=0` | Billing reverts to v1; v2 audit preserved |
| Rate-card bad update | `UPDATE uvt_config`; `rpc_invalidate_model_pricing_cache()` | ≤5-min stale window |
| UI abuse | `ACCOUNT_ROUTING_UI_ENABLED=0` | Reads still work; writes blocked |
| Agent override harmful | `ROUTING_AGENT_OVERRIDE_ENABLED=0` | Reverts to account-default only |
| DLQ flood | `AETHER_DLQ_ALERT_THRESHOLD` replay | No user-visible |

### 10.7 Rollback runbook (`docs/runbooks/uvt_v2_rollback.md`)

1. `UVT_V2_ENFORCEMENT=0`. App switches to v1 RPC immediately.
2. New writes go to v1 path. v2 rows remain (no mutation).
3. `routing_decisions` continue with `decision_schema_version=2` — audit stays rich, v1 parser tolerant.
4. Dashboards querying `predicted_uvt_cost` (v1 column) keep working.
5. Re-flip after fix: rerun parity gate on fresh shadow data first.

**Do NOT** during rollback:
- Drop v2 columns (loses audit continuity)
- Delete v2 rows (loses record)
- Re-flip without fresh parity gate

### 10.8 Key rotation (90-day cadence)

```
1. Set OPENAI_API_KEY_NEXT in Vercel env + deploy.
2. Boot-time: if NEXT is set, one health-check call against OpenAI.
   If pass → use NEXT exclusively.
   If fail → stay on OPENAI_API_KEY, alarm, do NOT per-call fallback.
3. 24h monitoring: last-4-chars of key logged per adapter call.
4. Operator swaps: OPENAI_API_KEY = NEXT value; unset NEXT.
5. Revoke old key in OpenAI dashboard.
```

Per-call fallback rejected — doubles HTTP cost and muddies audit.

## 11. Success Metrics (30 days post-flip)

- **Correctness:** `prediction_drift_pct` p99 ≤ 20%
- **Adoption:** `resolved_via='account_default'` ≥ 15% of traffic
- **OpenAI share:** 5–20% of traffic
- **Margin:** Monthly `sum(actual_billable_usd)` vs OpenAI invoice — within 2%
- **Parity:** v2-vs-v1 rolling median drift on Anthropic stays < 5%
- **Recovery:** Mean time to rollback < 10 min

## 12. Open Decisions & TODOs

### 12.1 Open decisions
- **`uvt_config` split trigger.** Today 11 keys across two domains. Split into `uvt_pricing_config` vs `uvt_rollout_config` when a new key belongs to the **opposite domain of the most-recently-added key**, not an arbitrary count threshold.
- **Analytics era filter.** Dashboard team to add global "data era" filter excluding `decision_schema_version != 2` by default. Not in scope this PR.

### 12.2 Open-item TODOs (must close before Day -7)

| TODO | Owner | Blocks | Notes |
|---|---|---|---|
| Product sign-off on OpenAI business-target floor/ceiling values | DBarr3 | Day -7 decision-log entry `2026-04-24-business-targets-v1.md`; blocks CI gate on `test_openai_business_targets.py` | Placeholders in §6.4: chat (12/25), codex (90/180). Live values will need margin validation against live OpenAI rates. |
| Calibration regression numbers (`provider_cost_to_uvt_rate`) | DBarr3 + ops | Day -7 — locks `uvt_config` seed in Migration 7 | `333.0` is a docs-coherence placeholder. Real value comes from `scripts/calibrate_v2.py` regression against 30-day Anthropic corpus. Pre-run requires corpus export + S3 bucket provisioning. |
| Implement `scripts/rollout_health_check.py` | ops | Day 0 — daily health-check gate can't run without it | Checks: P0/P1 incidents, provider error rates, Supabase p99, shadow exception rate, DLQ depth. Posts to Slack/Discord. |
| **`cargo check` CI gap fix (desktop-installer/src-tauri/)** | separate PR — Session J | Unrelated to this spec's billing path; tracked here because Session H surfaced it and the scope fence would silently miss it | Branch: `claude/ci-installer-cargo-check`. Closes CI hole: installer builds were not gated by `cargo check` on PR, enabling broken Rust to merge. |
| Named operator for phase-transition override authority | DBarr3 | Day 0 — runbook needs a human signer | Pre-launch solo authority = founder. Post-launch: document in rollback runbook. |
| S3 bucket `aethercloud-calibration-corpus` + IAM role | ops | Day -7 — blocks corpus anonymization upload + CI read | Read-only CI role, 2-quarter retention per §14.1. |
| Pre-warm 14-day shadow corpus staging test | ops | Day 0 — shadow table must be proven to accept writes at volume | Synthetic traffic against staging to validate `usage_events_v2_shadow` insert path. |
| Post-launch recheck triggers for business targets | DBarr3 | Ongoing | Provider price change >10%, observed margin deviation >5pp, or quarterly. Written into decision-log template. |

## 13. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Anthropic-calibrated rate mis-charges OpenAI | Medium | Business-target floor+ceiling tests per OpenAI route |
| Serverless TS cache serves 60s stale config | Low | `cache_bust_version` in key makes write-then-read consistent |
| FK migration fails on orphan model strings | Medium | Seed grandfathered short keys in M1 before M3 applies |
| Shadow volume insufficient on rare cells | High | Dynamic extension; accept `n<1000` only if <10/day volume |
| RPC drift gate false-positives on FP rounding | Low | Decimal contract test; 0.5% tolerance |
| Key rotation boot-check fails silently | Low | Alarm on NEXT failure; stay on CURRENT; named operator intervention |
| OpenAI returns 5xx with usage → double bill | Medium | Retry loop inspects usage; records once, never retries with tokens consumed |

## 14. Appendix

### 14.1 Calibration corpus policy (`docs/launch/calibration_corpus_policy.md`)

- Refreshed quarterly from production
- Retained 2 quarters, then deleted from S3
- Access: GitHub Actions CI role + two named maintainers
- Anonymization: strip `user_id`, `task_id`, `trace_id`, `agent_id`, `session_id`; bucket `created_at` to hour
- Any pricing rollback re-runs calibration against current corpus, not archival

### 14.2 Decision-log template (`docs/pricing/decisions/YYYY-MM-DD-<topic>.md`)

```markdown
## Decision
<one-sentence>

## Values
<table of affected configs/fields with new values>

## Rationale
<margin target, provider-cost math, competitive positioning>

## Authority
<who signed off>

## Review trigger
<when this value should be reconsidered>
```

CI gate: hardcoded business-target values must match the latest decision-log entry or test fails.

### 14.3 Files touched (summary)

New:
- `lib/providers/{__init__,base,anthropic,openai,pricing,types}.py`
- `lib/pricing_v2.py`
- `aethercloud/supabase/migrations/20260424_uvt_v2_pricing.sql`
- `aethercloud/supabase/migrations/20260424_routing_config.sql`
- `aethercloud/supabase/migrations/20260424_usage_events_v2.sql`
- `aethercloud/supabase/migrations/20260424_uvt_balances_provider_breakdown.sql`
- `aethercloud/supabase/migrations/20260424_rpc_record_usage_v2.sql`
- `aethercloud/supabase/migrations/20260424_routing_decisions_v2.sql`
- `aethercloud/supabase/migrations/20260424_uvt_config.sql`
- `site/lib/router/routing-cache.ts`
- `site/app/settings/model-defaults/page.tsx`
- `scripts/calibrate_v2.py`
- `scripts/rollout_health_check.py`
- `docs/runbooks/uvt_v2_rollback.md`
- `docs/runbooks/uvt_v2_rollout_no_go_windows.md`
- `docs/pricing/decisions/2026-04-24-business-targets-v1.md`
- `docs/launch/calibration_corpus_policy.md`
- `tests/pricing/*`, `tests/providers/*`, `tests/router/*`, `tests/integration/*`

Modified:
- `lib/token_accountant.py` (orchestrator only, all provider HTTP extracted)
- `lib/router.py` (pass provider/route/agent_id to token_accountant.call())
- `lib/router_client.py` (parse v2 decision_schema_version)
- `site/lib/router/deterministic.ts` (resolution order with 3-tier lookup)
- `site/lib/router/types.ts` (RoutingDecision v2 shape)
- `site/lib/router/constants.ts` (DEFAULT_MODEL_BY_TIER_AND_TASK type update)
- `site/app/api/internal/router/pick/route.ts` (new response shape)

### 14.4 Retired at Day 104

Cleanup migration `20260806_drop_v1_accounting_legacy.sql` — out of scope this PR, pre-written for scheduling.

---

## 15. Bug Traceability Log (A–L)

Each bug surfaced during the 6-section brainstorming iteration. Log preserved so future readers can trace **why** each invariant exists — removing a test or loosening a constraint should require understanding what was broken.

| ID | Caught in | What was broken | Fix location in spec |
|---|---|---|---|
| **1** | §1→§2 (user refinement) | Units error: proposed `PROVIDER_COST_TO_UVT_RATE=333_333.33` but worked examples implied `~333`. Factor-of-1000 disagreement between constant and examples. | §4.7 — seed value `333.0` (placeholder); §12.2 — calibration TODO gates the real number |
| **2** | §1→§2 (user refinement) | Calibration underdetermined: 3 unknowns (rate, overhead_pct, min_uvt) and only 1 target (v1 parity). | §6.3 — fix 2 from business judgment, regress the 3rd |
| **3** | §1→§2 (user refinement) | Margin-compounding regex too narrow: `\w*margin\w*\s*\*\s*\w*margin\w*` misses dict/attr access like `MODEL_CONFIG[m]["margin_multiplier"] * route["margin_override"]`. | §6.4 — AST walker, not regex; checks `BinOp(Mult)` across Name/Attribute/Subscript |
| **4** | §1→§2 (user refinement) | `MODEL_CONFIG` example missing `cached_input_per_m` → cached tokens would be silently billed as fresh (~10× overcharge). | §4.1 — `cached_input_usd_per_m numeric(10,4) not null`; §6.5 edge case — reject at load if missing |
| **A** | §2 review | `total_uvt` already exists as regular column on `uvt_balances` and is written by `rpc_record_usage`; `ALTER ADD COLUMN GENERATED` fails and breaks all existing writers. | §4.4 — staged migration: app deploy stops writes first, then drop+re-add as generated column |
| **B** | §2 review | FK migration on `usage_events.model → model_pricing.model` fails because historical rows use short-keys (`haiku|sonnet|opus|gpt5|gemma`) not logical names. | §4.1 seed table — grandfathered short-key rows with `enabled=false`; §4.3 FK applies cleanly |
| **C** | §2 review | RPC drift gate hardcoded `333.0` and `3` inline, duplicating pricing config across Python and SQL. Split-brain failure mode. | §4.7 `uvt_config` table — single source of truth; RPC reads values at runtime |
| **D** | §3 review | `ProviderResponse.finish_reason` was single-field: canonical normalization lost provider-raw reason, breaking debuggability on production incidents. | §5.2 — dual field: `finish_reason` (4-value canonical enum) + `raw_finish_reason` (provider-native, audit only) |
| **E** | §3 review | `max_output_tokens = min(requested, cap)` silently truncated user's request when over cap → user sees truncated output with `finish_reason=length` and blames the model. | §5.5 — `OutputCapExceededError` raised; maps to HTTP 413; never silent |
| **F** | §3 review | Blind retry on 429/5xx ignored provider rate-limit headers AND — more seriously — retried 5xx responses that already had `usage` populated, double-billing tokens. | §5.2 `RetryPolicy` honors provider headers; retry loop inspects body for populated `usage` before retry; raises `ProviderIncompleteError` if tokens consumed |
| **G** | §3 review | `compute_provider_cost_usd` location ambiguous (split across `token_accountant` vs `pricing_v2`); RPC passed pre-computed `cost_usd` instead of raw tokens, making it a rubber-stamp not an arbiter. | §5.1 — `lib/pricing_v2.py` is single formula home; §4.5 RPC receives raw tokens + agent_id + route, joins `model_pricing` + `agent_routing_override` internally, recomputes full formula |
| **H** | §4 review | Regression gate used `|median|` → allowed candidates with systematic undercharge to pass if spread was tight. Revenue bleeds silently. | §6.3 — signed-median-first regression: bias gate (2%) applied before spread gate (15%); tiebreaker on rate proximity to examples' implied value |
| **I** | §4 review | Calibration corpus is Anthropic-only (no v1 history for OpenAI). Rate calibrated against Anthropic was applied to OpenAI with no invariant constraining OpenAI pricing. | §6.4 — per-OpenAI-model business-target tests with **floor AND ceiling** (floor prevents silent margin erosion); §6.7 — shadow compute is async fire-and-forget so latency unaffected |
| **J** | §6 review | Flag matrix allowed `UVT_V2_ENFORCEMENT=1` at boot without requiring the parity gate to have ever recorded success — a calendar misread could flip a week early. | §10.2 — boot assertion reads `uvt_config.v2_parity_gate_passed_at`, rejects if 0 or >60 days old |
| **K** | §6 review | `decision_schema_version` migration was one-way; v1 rows had NULL `resolved_via` which would be bucketed with v2 `system_fallback` rows, corrupting analytics. | §7.4 — dedicated `v1_legacy` sentinel in `resolved_via` CHECK; §7.5 runbook rule forcing `WHERE decision_schema_version=2` on analytics queries |
| **L** | §6 review | `OPENAI_API_KEY` had no rotation story — every quarter the app would be unable to rotate without downtime or per-call double-request cost. | §10.8 — `OPENAI_API_KEY_NEXT` boot-verified exclusive use (no per-call fallback); matches existing Anthropic rotation runbook #04 |

**Invariant that emerges from this log:** the spec treats billing arithmetic as safety-critical. Every bug above is either "billing silently wrong" or "audit trail compromised." Loosening any gate (AST check, parity tolerance, drift tolerance, FK constraint, decimal precision) requires explicit acknowledgment in a decision-log entry (§14.2).

---

**End of design.**
