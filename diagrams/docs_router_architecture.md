# Router Architecture — Two Layers, Two Jobs

**Audience:** anyone writing code in `/site/lib/router/*` (TypeScript), `lib/router.py` (Python), or `lib/router_client.py`.
**Status:** authoritative. If code disagrees with this doc, code is wrong.
**Last updated:** 2026-04-22 (PR 1 v5 landed)

---

## TL;DR

AetherCloud has **two routers**. They are NOT redundant. They do different jobs at different layers.

| Layer | Name | Lives at | Decides | Language |
|---|---|---|---|---|
| 1 | **PolicyGate** | HTTP edge (`/api/internal/router/pick`) | *Is this call allowed?* | TypeScript (Vercel Node runtime) |
| 2 | **ModelRouter** | Python orchestrator (`lib/router.py`) | *Which model fits this work?* | Python |

**Every user request passes through PolicyGate first, then ModelRouter.** If PolicyGate throws, ModelRouter is never invoked. In PR 1 v5 PolicyGate is shadow-mode; Stage D is still the live enforcer. PR 2 flips it over for canary users.

---

## The Flow

```
┌──────────────┐
│  User / UI   │
└──────┬───────┘
       │ HTTPS
       ▼
┌─────────────────────────────────────┐
│  Next.js API / orchestrator ingress │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — PolicyGate  (TypeScript, PR 1 v5)                │
│  File: site/app/api/internal/router/pick/route.ts           │
│                                                             │
│  Checks, in order:                                          │
│    1. Valid service token (middleware + route)              │
│    2. Tier × task default model lookup                      │
│    3. Opus monthly budget cap                               │
│    4. Output tokens ≤ plan.output_cap                       │
│    5. Active concurrent tasks < plan.concurrency_cap        │
│    6. Predicted UVT ≤ user balance (simple formula in PR1)  │
│                                                             │
│  On violation → throws typed RouterGateError                │
│              → HTTP 402 / 413 / 429                         │
│              → user sees upgrade message                    │
│              → audit row in routing_decisions               │
│              → ModelRouter NEVER called                     │
│                                                             │
│  On pass     → returns RoutingDecision { chosen_model, ... }│
└──────────────────────┬──────────────────────────────────────┘
                       │  (only if all gates pass)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2 — ModelRouter  (Python, Stage D)                   │
│  File: lib/router.py                                        │
│                                                             │
│  Accepts: the chosen_model hint from PolicyGate             │
│  Does:                                                      │
│    1. Load plan caps (cached)                               │
│    2. Compress hydrated context to plan.context_budget      │
│    3. Classify load via QOPC bridge (light/medium/heavy)    │
│    4. Pick final model (may agree or refine vs hint)        │
│    5. Confidence gate — low-confidence heavy → reclassify   │
│    6. Call model via TokenAccountant (sole Anthropic path)  │
│    7. Return RouterResponse with full breakdown             │
│                                                             │
│  Does NOT:                                                  │
│    - Enforce quota (PolicyGate did that)                    │
│    - Silently downgrade on budget miss (raises typed        │
│      PlanExcludesOpusError / OpusBudgetExhaustedError)      │
│    - Spawn sub-agents (deferred to D.5)                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  TokenAccountant (Stage A)                                  │
│  - sole call site to api.anthropic.com                      │
│  - applies prompt caching                                   │
│  - writes usage_events + decrements uvt_balances            │
│  - DLQ on RPC failure                                       │
└──────┬──────────────────────────────────────────────────────┘
       │
       ▼
    Response
```

---

## Division of Responsibility — the hard line

| Concern | Owned by | Not owned by |
|---|---|---|
| "Is user on the right plan?" | **PolicyGate** | ModelRouter |
| "Can user afford this UVT?" | **PolicyGate** | ModelRouter |
| "Is user over their output cap?" | **PolicyGate** | ModelRouter |
| "Is user at concurrency limit?" | **PolicyGate** | ModelRouter |
| "What's the default model for this (tier, task)?" | **PolicyGate** (table lookup) | ModelRouter |
| "Is this request light/medium/heavy work?" | **ModelRouter** (QOPC classifier) | PolicyGate |
| "Should we reclassify on low confidence?" | **ModelRouter** | PolicyGate |
| "How do we compress context to plan budget?" | **ModelRouter** | PolicyGate |
| "Billing / usage write" | **TokenAccountant** | Both routers |
| "Prompt caching" | **TokenAccountant** | Both routers |

### The anti-rule
> **ModelRouter NEVER returns a different model because of plan/budget/quota reasons.**
> Those are PolicyGate's job. If a cap is hit, PolicyGate throws upstream.
> ModelRouter picks based on *work difficulty*, not *user eligibility*.

---

## Dual-formula shadow mode (PR 1 v5 decision C)

Python's live `model_registry.uvt()` is simple: `(input − cached) + output`. No weights, no model multipliers. It's the currency of `usage_events.uvt_counted` and `uvt_balances.total_uvt`. PR 1 does NOT change it.

PolicyGate computes BOTH formulas and logs both:

- `computeUvtWeighted(usage)` — spec §2 formula (7 inputs × weights × model multiplier) → `routing_decisions.predicted_uvt_cost`
- `computeUvtSimple(usage)` — Python-parity → `routing_decisions.predicted_uvt_cost_simple`

**All gate arithmetic (balance check, opus_pct_mtd) uses SIMPLE in PR 1.** `site/lib/router/constants.ts` exports `UVT_FORMULA_ENFORCEMENT = "simple"`. PR 2 flips it to `"weighted"` after `usage_events.uvt_counted` is backfilled.

100-fixture parity test proves both TS and Python compute identical values on both formulas.

---

## Model ID mapping (DB CHECK constraint)

`public.usage_events.model` is CHECK-constrained to `haiku|sonnet|opus|gpt5|gemma`. PolicyGate's `chosen_model` uses the spec's logical names (`claude-haiku-4`, `claude-sonnet-4`, `claude-opus-4`, `gpt-5`, `gpt-5-mini`, `perplexity-sonar`). `routing_decisions.chosen_model` is a NEW column with no enum — stores logical names as-picked.

`site/lib/router/model_id_map.ts` translates logical → short for any writer targeting the CHECK-constrained path:

| Logical (spec) | Short (DB enum) |
|---|---|
| `claude-haiku-4` | `haiku` |
| `claude-sonnet-4` | `sonnet` |
| `claude-opus-4` | `opus` |
| `gpt-5-mini` | `gpt5` *(TEMP — no mini in Python today)* |
| `gpt-5` | `gpt5` |
| `perplexity-sonar` | `gemma` *(PLACEHOLDER — no sonar bridge yet)* |

Snapshot IDs (`claude-haiku-4-5-20251001`, etc.) resolve inside Python `lib/model_registry.py`. PolicyGate never sees snapshots.

---

## Philosophy — "honest limits"

When a user hits a limit, they see the limit:

- **Free user tries a task** → runs on Haiku (explicit tier baseline, not a downgrade). Response header: `x-aether-upgrade-hint: {task}_on_opus_requires_pro`.
- **Solo user requests 20k output tokens** → 413 "Output cap is 16k on Solo. Upgrade to Pro for 32k."
- **Pro user at 3 concurrent tasks** → 429 "Concurrency limit reached. Wait for a task to finish or upgrade to Team for 10 concurrent."
- **User's opus monthly budget exceeded** → 402 "Opus budget used up this month. Upgrade to Team for 2.5× the Opus allowance."
- **User's UVT balance too low for call** → 402 "Not enough UVT — top up or upgrade."

No silent substitution. No buried `downgrade_reason` fields. The error IS the upsell moment.

---

## Dead-code safety net (post-PR 1 v5 cleanup)

Stage D's original code contained silent-downgrade branches. Those branches have been **replaced with typed Python exceptions**:

- `PlanExcludesOpusError` — tier has `opus_pct_cap=0` but heavy load classified
- `OpusBudgetExhaustedError` — opus sub-budget hit 0 MTD but heavy load classified

In production these exceptions should **never** fire, because PolicyGate blocks the same cases upstream at the HTTP layer. The exceptions exist as a defense-in-depth tripwire: if they ever raise in production, it means something bypassed PolicyGate, and we want a loud crash + alert rather than silent wrong behavior.

**SRE alerts:**
- `ModelRouter.policy_bypass_detected` counter > 0 (post-cutover) → page immediately
- `policy_bypass_by_gate["plan_excludes_opus"]` or `["opus_budget_exhausted"]` > 0 → page immediately

---

## Migration from Stage E to PolicyGate

Stage E (`lib/pricing_guard.py`) does in Python today what PolicyGate does in TS. They coexist intentionally.

**PR 1 v5 (this PR):** PolicyGate ships shadow-mode. `site/lib/router/config.ts` → `ROUTER_CONFIG.shadow_mode = true`. Stage E remains the production enforcer. Orchestrator's exactly-one shadow dispatch at [lib/uvt_routes.py](../lib/uvt_routes.py) (marked `# router-shadow-log`) calls PolicyGate purely for telemetry parity — the chosen_model is logged, NEVER substituted.

**PR 2 (future):** flip `shadow_mode = false` for canary users. PolicyGate becomes the production enforcer for them. Stage E still runs as belt-and-suspenders.

**PR 3 (future):** cut Stage E preflight out entirely. PolicyGate is the sole enforcer. Delete `lib/pricing_guard.py`'s `preflight()` function.

---

## Environment variables

| Name | Scope | Purpose |
|---|---|---|
| `AETHER_INTERNAL_SERVICE_TOKEN` | Vercel all envs (site/) | Edge middleware + route-level service-token auth (primary) |
| `AETHER_INTERNAL_SERVICE_TOKEN_PREV` | Vercel all envs, optional | 24h rotation overlap window |
| `AETHER_ROUTER_URL` | Python orchestrator (VPS) | e.g. `https://app.aethersystems.net/api/internal/router/pick` |

### Rotation runbook

1. Generate new token: `openssl rand -hex 32`.
2. Set `AETHER_INTERNAL_SERVICE_TOKEN_PREV = <current>` on Vercel (site/) — this keeps the outgoing token accepted.
3. Set `AETHER_INTERNAL_SERVICE_TOKEN = <new>` on both Vercel (site/) and VPS (`AETHER_INTERNAL_SERVICE_TOKEN` + `systemctl restart aethercloud`).
4. Wait for the orchestrator to roll (≤ 5 min).
5. After 24h: unset `AETHER_INTERNAL_SERVICE_TOKEN_PREV`.

The middleware accepts either primary or previous during the overlap window; after you unset `_PREV`, only the primary is accepted.

---

## Naming rules (enforce in PRs)

| Write this | NOT this |
|---|---|
| `PolicyGate` or `router.pick` (TS) | "the router" |
| `ModelRouter` or `Router.route` (Python) | "the router" |
| `RouterGateError` (TS) | "RouterError" |
| `routing_decisions.reason_code` | "router_status" |

When speaking: "the gate" for PolicyGate, "the model router" for Stage D. Never "the router" — always qualify.

---

## Deferrals (not in either layer yet, post-PR 1 v5)

- **Race-proof concurrency** — `activeConcurrentTasks` today is caller-supplied and advisory. Postgres advisory lock or Redis semaphore is PR 2 scope.
- **Sub-agent dispatch / fan-out** — Stage D.5 when demand pattern exists.
- **Right-sizing plans** — no sub-agents yet, nothing to size.
- **Explicit `requestedModel` override** — PR 2+ concern; `FreeTierModelBlockedError` class exists for when it lands.
- **UVT prediction reconciliation** — PR 2 writes `actual_input_tokens` / `actual_output_tokens` / `actual_uvt_cost` into `routing_decisions` from `usage_events`.
- **Weighted-formula enforcement flip** — PR 2 flips `UVT_FORMULA_ENFORCEMENT` from `"simple"` to `"weighted"` after `usage_events.uvt_counted` backfill.
- **Perplexity Sonar bridge** — PR 1 routes `research` task to `claude-sonnet-4` on paid tiers (haiku on free). Sonar integration gets its own PR; `perplexity-sonar` → `gemma` DB-enum placeholder in `model_id_map.ts` is a TODO to split.
- **gpt-5-mini distinct enum** — PR 2 migration adds `gpt5mini` to `public.usage_events.model` CHECK constraint; today both `gpt-5` and `gpt-5-mini` collapse to `gpt5`.

**Removed from Deferrals in PR 1 v5** (now in code):
- ~~Typed Python exceptions for budget/tier refusals~~ — `PlanExcludesOpusError` + `OpusBudgetExhaustedError` shipped
- ~~`routing_decisions` audit table~~ — migration 20260422 shipped
- ~~Python client with fail-closed semantics~~ — `lib/router_client.py` shipped
- ~~Dual-formula UVT accounting~~ — both formulas computed + logged in PR 1

---

## Contact surface between layers

PolicyGate → ModelRouter handoff is through the orchestrator's HTTP call. Payload from PolicyGate:

```json
{
  "chosen_model": "claude-opus-4",
  "reason_code": "default_by_tier_and_task",
  "predicted_uvt_cost": 14230,
  "predicted_uvt_cost_simple": 1450,
  "decision_schema_version": 1,
  "uvt_weight_version": 1,
  "latency_ms": 3
}
```

Orchestrator calls `Router.route(...)` in Python with `chosen_model` as a hint (via `lib/router_client.pick`). ModelRouter may confirm, or — via QOPC classification + confidence gate — pick a different model *within the same affordability envelope* (e.g. classifier says "this is actually light work, use Haiku instead of the suggested Sonnet"). ModelRouter MUST NOT pick a model that would have failed PolicyGate.

**Invariant:** `ModelRouter.final_model ∈ {models_affordable_for_this_tier_given_current_mtd_usage}`. Tested via `tests/test_model_router_invariant.py` with an adversarial classifier.
