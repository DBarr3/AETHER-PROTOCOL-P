# Group A Patch Report — 2026-04-23

**Scope:** Sweep #1 pre-flip Highs (H2, H4, H5) + Medium roll-forward (M1).
**Branch:** `claude/suspicious-wright-619275`
**PR:** https://github.com/DBarr3/AETHER-CLOUD/pull/8
**Live DB impact:** migrations applied to `cjjcdwrnpzwlvradbros` during session.

---

## Commits landed

| # | SHA | Finding | Scope |
|---|---|---|---|
| 1 | `fc7a796` | **H5** | `getOpusPctMtd` fail-closed (1.0 default, last-known-good fallback) |
| 2 | `9165bb0` | **H2** | `bigint` migration on 3 cost columns + Zod `max(2_000_000)` on estimatedInput/Output |
| 3 | `89d5150` | **H4** | Audit writer failure ladder: `console.error` + OTel counter + span event |
| 4 | `a1455e6` | H4 follow-up | Lint-clean helpers (renamed/extracted to avoid OTel-PII grep window) |
| 5 | `dec2bc1` | **M1** | DEFAULT partition + `extend_routing_decisions_partitions()` + pg_cron monthly |

All 5 commits pushed to `origin/claude/suspicious-wright-619275`.

---

## Per-finding change summary

### H5 — `getOpusPctMtd` fail-closed on DB error

**File:** `site/lib/router/helpers/getOpusPctMtd.ts`
**Tests:** `site/tests/unit/getOpusPctMtd.failclosed.test.ts` (7 assertions)

Behavior matrix:

| Scenario | Before | After |
|---|---|---|
| rpc success | cache + return value | unchanged |
| rpc throws, no LKG | return 0 (fail-open → unlimited Opus) | return 1.0 (blocks Opus) |
| rpc throws, LKG exists | return 0 | return LKG (best-effort) |
| `supabase.rpc` absent | return 0 | return 1.0 |
| OTel signal | `router.opus_cap_bypassed_fail_open` | `router.opus_pct_mtd_resolver_error` with `fallback={fail_closed,last_known_good}` |

The LKG cache is process-lifetime (unbounded) and updated on every rpc success. First-run users with no LKG get the 1.0 hard-block during an outage; returning users keep their most recent real value.

### H2 — integer overflow on `predicted_uvt_cost`

**Files:** `aethercloud/supabase/migrations/20260423_routing_decisions_bigint.sql` (new), `site/app/api/internal/router/pick/route.ts` (schema edit)
**Tests:** `site/tests/unit/policy_gate.token_upper_bound.test.ts` (5 assertions)

Two-layer defense:

1. **DB:** `ALTER COLUMN ... TYPE bigint` on `predicted_uvt_cost`, `predicted_uvt_cost_simple`, `actual_uvt_cost`. Applied live; verified via `pg_attribute` on parent + one partition — all 3 columns show `bigint`. ALTER cascades across the 13 partitions automatically.
2. **Edge:** Zod `.max(2_000_000)` on `estimatedInputTokens` and `estimatedOutputTokens`. Claude's context window is 200k; 2M is a 10× safety margin. 500M overflow input now rejected with HTTP 400 `validation_failed` before any DB insert.

### H4 — audit writer failure alerting

**File:** `site/lib/router/auditLog.ts`
**Tests:** `site/tests/unit/audit_error_handler.test.ts` (4 assertions)

Default `_errorHandler` upgraded from "OTel addEvent only" (no-op without SDK) to **three parallel channels**:

1. **`console.error`** with structured extras `{error_type, error_message}` — always-on, Vercel/journald catches stdout/stderr
2. **OTel counter** `audit_writer_failed_total` via `metrics.getMeter().createCounter()` — NoopCounter today, real counter once metrics SDK is wired. Target alert formula: `rate(audit_writer_failed_total[5m]) > 0.01 * rate(router_pick_total[5m])` → page.
3. **Span `addEvent`** — preserves distributed-trace context for the failing request

Row body deliberately omitted from the log payload (only error class + driver message emit, not user_id / trace_id / other row fields).

User callers can still override via `setAuditErrorHandler(customFn)`. `resetAuditErrorHandler()` added for test isolation. Outer `try/catch` in `fireAndForget` guards against a user-handler throwing.

### M1 — partition roll-forward

**File:** `aethercloud/supabase/migrations/20260423b_routing_decisions_partition_rollforward.sql` (new)
**Live verification:** 7/7 checks pass + 0 new advisor warnings.

Two-layer defense:

1. **DEFAULT partition (`routing_decisions_default`)** — catches any row outside a specific monthly range. RLS enabled + "own rows" policy mirroring the parent. Empty in steady state; a non-zero row count = "cron stopped, investigate."
2. **`extend_routing_decisions_partitions(n_months_ahead)`** — idempotent plpgsql function (security definer, service_role-only). Creates current + N months ahead (default 2), also enables RLS + policy on each new partition (mirrors the 20260422b pattern).
3. **pg_cron schedule `5 0 1 * *`** — runs the extender on the 1st of each month at 00:05 UTC. Installed into Supabase's `extensions` schema per their convention.

Total partitions after migration: 13 (12 monthly + 1 DEFAULT).

---

## Verification evidence

```bash
# TS test suite
$ cd site && npm test
Test Files  15 passed (15)
      Tests  111 passed (111)

# Python router/uvt/client/parity/invariant/accountant suite
$ python -m pytest tests/test_router.py tests/test_uvt_routes.py \
    tests/test_router_client.py tests/test_pricing_guard.py \
    tests/test_uvt_parity.py tests/test_model_router_invariant.py \
    tests/test_token_accountant.py -q
308 passed in 9.65s

# OTel PII lint
$ bash tests/lint/no_pii_in_otel.sh
PASS: no PII in OTel attribute payloads.

# Supabase advisor (post-migration)
Zero new security warnings on routing_decisions or its partitions.
```

Total tests passing across all suites: **419**.

---

## Still outstanding (Groups B, C, D)

### Group B (operational hygiene) — next up
- **H3** rate limit on `/api/internal/router/pick`
- **M2** consolidate `constantTimeEqual` into `serviceToken.ts` with `node:crypto.timingSafeEqual`
- **M3** token rotation TTL + counter for `_PREV` usage
- **M4** regex-restrict `traceId`/`requestId` charset in Zod
- **M5** boot-time `assertPlanParity()` against live `public.plans`
- **M6** CI test guard on `ROUTER_CONFIG.shadow_mode === true`
- **L3** body size limit on the route

### Group C (Python hardening)
- **Sweep #2 M1** remove surviving `downgrade_reason` references (incl. `desktop/pages/uvt-meter/uvt-meter.js:90` UI field)
- **Sweep #2 M4** remove `_warned_once` + lock `policy_bypass_by_gate` writes under Gunicorn/threaded
- **Sweep #2 L1** strip control chars from `chosen_model` before logging

### Group D (PR 2 prerequisites — deferred)
- **L1 Sweep #1** prototype-chain defense on `LOGICAL_TO_SHORT` (elevate to High at PR 2 cutover)
- **Sweep #2 M2** `AETHER_ROUTER_URL` hostname allowlist + TLS pinning
- **Sweep #2 M3** TOCTOU — move balance check into `rpc_record_usage` tx
- **Sweep #2 M5** reclassify rate cap / determinism
- **Sweep #2 M6** `plans_cache` TTL / Supabase realtime invalidation
- **L2** UnknownModelError message sanitization
- **L4** proper microbenchmark for timing-safe compare

---

## Ready for Group B

Nothing blocks proceeding. Same branch discipline (stack commits, TDD per finding, push at end of group, amend PR body with new entries).

Awaiting user signal to begin Group B.
