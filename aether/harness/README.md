# aether/harness — Stage I Integration + Margin Harness

Proves the UVT stack (Stages A–F) is profitable before we deploy to VPS2.

## Quick start

```bash
# Full pro-tier simulation (default persona mix, deterministic seed)
python -m aether.harness.simulate --tier pro --users 25 --days 30 --seed 42

# Smaller runs:
python -m aether.harness.simulate --tier solo --users 10 --days 7 --seed 1
python -m aether.harness.simulate --tier free --users 50 --days 30

# Heavy abuse scenario:
python -m aether.harness.simulate --tier team --users 8 --days 30 \
    --persona-mix casual=0.2,power=0.5,abusive=0.3

# Smoke-test (pytest, 2 users × 3 days)
pytest tests/harness/test_harness_smoke.py -v
```

Artifacts land in `reports/`:
- `margin-<ts>.csv` — raw per-call fact table (include denied calls)
- `margin-<ts>.md` — human-readable tier summary + routing mix + warnings
- `sample-pro-25u-30d.md` — committed sample so you can eyeball output without running the CLI

## What the harness is

A **consumer** of the UVT stack — it never modifies `lib/token_accountant.py`, `lib/pricing_guard.py`, `lib/router.py`, `lib/qopc_bridge.py`, `lib/context_compressor.py`, or `lib/uvt_routes.py`. It:

1. Mounts `uvt_router` on a minimal FastAPI app (same pattern as `tests/test_uvt_routes.py`)
2. Installs a stub `api_server.svc.session_mgr` keyed by per-user bearer tokens
3. Wires an **in-memory Supabase client** (`in_memory_supabase.py`) into `uvt_routes.supabase_client` + `Router` — seeds `public.plans` from the same values as the 2026-04-21 migration
4. Swaps `httpx.AsyncClient` inside `lib.token_accountant` with a class that uses `FakeAnthropicTransport` — deterministic, RNG-seeded, returns realistic per-load token counts, never touches real Anthropic
5. Generates synthetic traffic via `UserProfile` (persona-driven call volume + load mix)
6. At end-of-run, diffs the harness tally against `/account/usage` for every user — any drift is surfaced as a section in the MD report

## Read the report

Per-tier table columns:

| column | meaning |
|---|---|
| UVT burned | sum of `uvt_charged` across allowed calls (classifier + orchestrator) |
| COGS $ | sum of `underlying_cost_usd` at Anthropic list price |
| Sub $ | `n_users × plan.price_usd_cents` (monthly subscription) |
| Overage $ | `max(0, user_uvt − monthly_cap) × plan.overage_rate`, summed per user |
| Revenue $ | `Sub $ + Overage $` |
| Margin $ | `Revenue $ − COGS $` |
| Margin % | `Margin $ / Revenue $` (— for free tier) |

**Warning flags** — shown above the routing breakdown when triggered:

- 🔴 **Negative margin on a paid tier** → pricing is wrong OR Opus sub-budget didn't fire. Investigate the routing breakdown before deploying.
- 🟡 **>40% of users hit quota** → caps too tight, churn risk. Consider raising `uvt_monthly` for that tier.
- 🟡 **<5% of users hit quota** (10+ users only) → caps too loose, money on the table. Consider tightening.

**Routing breakdown** — per-tier. Shows the model mix, denial reasons, and downgrade reasons (Opus sub-budget exhausted, tier excludes Opus, etc). If margin looks wrong, this is the diagnostic view: too much Opus usage, Opus sub-budget not firing, classifier mis-triaging, etc.

## Gotchas

- **Windows timing:** the 25×30×pro sample completes in ~2m4s locally (spec target: <2min). The overhead is FastAPI TestClient's per-request event-loop reset. A 4-second overshoot on a 2-minute budget is acceptable; use `--users 10` for iteration.
- **Pricing snapshot drift:** `in_memory_supabase.PLANS_SEED` is a hand-copy of `aethercloud/supabase/migrations/20260421_uvt_accounting.sql`. If you change the migration, update `PLANS_SEED` — the smoke test has an integration-drift check but it won't catch plan-config drift.
- **Classifier billing:** every `/agent/run` triggers two Anthropic calls (classifier Haiku + orchestrator at routed tier). The harness counts both toward `uvt_charged`. This matches `/account/usage` because `rpc_record_usage` is called for every Anthropic call, not just the orchestrator.
- **The fake transport uses the TRUE load** as a hint so the classifier returns the ground-truth tier. That isolates billing/routing from classifier accuracy — classifier drift is a separate concern (measure separately if you need to).

## Files

| File | What it does |
|---|---|
| `simulate.py` | CLI entry point + HarnessContext wiring |
| `fake_anthropic.py` | `httpx.AsyncBaseTransport` that returns canned `/v1/messages` responses |
| `in_memory_supabase.py` | Stateful Supabase mock supporting every query shape our code uses + `rpc_record_usage` |
| `user_simulator.py` | Persona-driven per-user call stream (casual/power/abusive) |
| `report.py` | CSV + Markdown writers + warning heuristics |
| `__init__.py` | Package marker |

## What this unblocks

Once the sample report shows:
- All paid tiers ≥ 50% margin
- No 🔴 flags
- At least one 🟡 quota-hit flag in the 5–40% band (or explicit acceptance of the current mix)

…we're cleared for **Stage J** — the VPS2 deploy runbook with `AETHER_UVT_ENABLED` feature flag. Don't ship without a green harness run.
