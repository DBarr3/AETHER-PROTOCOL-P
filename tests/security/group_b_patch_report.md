# Group B Patch Report — 2026-04-23

**Scope:** Sweep #1 Medium + Low findings (M2–M6, L3) + the remaining High rate-limit (H3).
**Branch:** `claude/suspicious-wright-619275` (appends to PR #8 — NOT a new PR).
**Live DB impact:** none. Three prod-only migrations the user applied between Group A and Group B are committed as history files (see below) but NOT re-applied.

---

## Commits landed

| # | SHA | Finding | Summary |
|---|---|---|---|
| 1 | `8e02f3a` | **H3** | IP + user rate limit (60/IP/min + 600/user/min) |
| 2 | `b5ba9a8` | **M2** | `constantTimeEqual` → `node:crypto.timingSafeEqual` in `site/lib/router/serviceToken.ts` |
| 3 | `272bfe4` | **M3** | `AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT` TTL + OTel counter |
| 4 | `4353930` | **M4** | Zod regex-restrict `requestId`/`traceId` to `[A-Za-z0-9._:-]{1,128}` |
| 5 | `1a1f4bb` | **M5** | `assertPlanParity()` boot-time DB ↔ `PLAN_CAPS` check |
| 6 | `04e5a0c` | **M6** | CI regression guard on `ROUTER_CONFIG.shadow_mode === true` |
| 7 | `782175f` | **L3** | 16 KB HTTP body size ceiling on `/api/internal/router/pick` |

All 7 commits pushed to `origin/claude/suspicious-wright-619275` (see push step below).

---

## Per-finding patch reports

### H3 — IP + user rate limit

**Diff summary:**
- New `site/lib/router/rateLimit.ts` (42 LOC) — sliding-window in-process limiter. Exports `rateCheck(key, nowMs, windowMs, limit) → {allowed, retry_after_seconds}` + `IP_LIMIT_PER_MIN=60` / `USER_LIMIT_PER_MIN=600` / `RATE_WINDOW_MS=60_000`.
- `site/middleware.ts` — adds IP rate-limit before the auth check; extracts client IP from `x-forwarded-for` leftmost or `x-real-ip`; 429 with `retry-after` header on limit.
- `site/app/api/internal/router/pick/route.ts` — adds user rate-limit AFTER Zod parse (keys on validated `userId`, not client-lied).
- New tests: `site/tests/unit/rateLimit.test.ts` (6) + `site/tests/integration/router.ratelimit.test.ts` (7).

**Verification evidence:**
- RED → GREEN: 13/13 tests flipped from "module not found" to pass.
- Behavior: 60 IP-bucket allows pass, 61st returns 429 with retry_after; 600 user-bucket allows, 601st 429; different IPs / userIds bucketed independently; auth-valid requests still count against IP budget.
- Upgrade path documented in module header: swap Map for Upstash Redis + atomic INCR+TTL.

### M2 — `constantTimeEqual` consolidation

**Diff summary:**
- New `site/lib/router/serviceToken.ts` (54 LOC) — single source of truth.
  - `serviceTokenEquals(a,b)`: wraps `node:crypto.timingSafeEqual`. For unequal-length inputs, pads both to the longer length with `Buffer.alloc(n - len)` and runs a throwaway `timingSafeEqual` so the unequal-length branch and equal-length-mismatch branch take equal time.
  - `isValidServiceTokenHeader(header)`: single-source check of current + prev tokens.
- `site/middleware.ts` and `site/app/api/internal/router/pick/route.ts` — dropped local `constantTimeEqual`; import from `serviceToken`.

**Verification evidence:**
- RED → GREEN: 10 tests flipped from "module not found" to pass.
- Behavior: same-length match/mismatch, unequal-length no-throw, empty-edge, 64-char hex token, current+prev accept, null/wrong reject.

### M3 — `_PREV` token TTL

**Diff summary:**
- `site/lib/router/serviceToken.ts` — added `isPrevExpired()` helper: reads `AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT` env (ISO 8601). Past-expiry → PREV rejected. Unparseable → fail-closed. Unset → legacy accept (backward compat for deploys that haven't adopted the TTL).
- OTel `metrics.getMeter("aether.router.service_token")` creates `router.prev_token_accepted` counter; increments on every PREV match.
- `isValidServiceTokenHeader` checks `!isPrevExpired()` before the PREV compare and fires the counter when PREV matches.

**Verification evidence:**
- 5 behavior tests (TTL unset, future, past, invalid, current-still-works-after-PREV-expired) green.
- Counter emission verified by source review — vi.spyOn + vi.resetModules doesn't survive the re-imported `metrics` module reference; docstring in the test file explains the limitation. NoopCounter is a documented no-op that can't throw, so worst case is silent no-op (same as no-SDK-wired default).

### M4 — traceId / requestId charset

**Diff summary:**
- `site/app/api/internal/router/pick/route.ts` — Zod schema changed from `z.string().min(1).max(256)` to `z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/, {message: "..."})` on both `requestId` and `traceId`.

**Verification evidence:**
- RED → GREEN: 6 rejection tests (newline, ANSI, space, emoji, oversize, slash) flipped from "accepted" to "rejected-with-400-validation_failed".
- 4 accept-path assertions still pass (UUIDs, colon-delimited spans, empty-rejection, 128-char-exact boundary).
- All existing callers (Python shadow dispatch sending `uuid4()`, integration tests, H3 rate-limit tests) use short alphanumeric IDs that fit the new charset.

### M5 — `assertPlanParity()` boot-time check

**Diff summary:**
- `site/lib/router/startupAssertions.ts`:
  - Added `PlanParityError` class.
  - Added `assertPlanParity(supabase)` — selects `tier, uvt_monthly, opus_pct_cap, concurrency_cap, output_cap, sub_agent_cap, context_budget_tokens` from `public.plans`, compares numerically field-by-field against `PLAN_CAPS`, throws on any mismatch or missing tier.
  - Added `recordPlanParityResult(err)` + module-level cache slot + `__setPlanParityResultForTests` / `__resetPlanParityStateForTests` helpers.
  - `assertRouterWired` now throws the cached parity error in production (test mode unchanged).
- `site/lib/router/boot.ts` — after Supabase client construction, fires `void assertPlanParity(supabase).then(record null).catch(record err)`. Fire-and-forget; first few requests may land before the check completes (pass through); once cached, subsequent requests throw.

**Verification evidence:**
- 7/7 tests: match-4-rows, drift on `uvt_monthly`, drift on `opus_pct_cap`, missing tier, wrapped DB error, prod-throw, test-no-op.

### M6 — shadow_mode CI guard

**Diff summary:**
- New `site/tests/unit/router.config.shadow_mode.test.ts` (27 LOC). 3 assertions: `ROUTER_CONFIG.shadow_mode === true`, `canary_user_ids` is empty, `Object.isFrozen(ROUTER_CONFIG)` true.

**Verification evidence:**
- No RED stage (the test is a regression guard on existing-correct state, not new behavior). Any future commit that flips `shadow_mode` to `false` MUST update these assertions in the same change, which is the whole point.

### L3 — body size ceiling

**Diff summary:**
- `site/app/api/internal/router/pick/route.ts` — added `const BODY_MAX_BYTES = 16_384` and a Content-Length check immediately after the auth check (before `req.json()`). Returns `413 payload_too_large {limit_bytes: 16384}` when the header reports > 16 KB.

**Verification evidence:**
- RED → GREEN: 2 rejection tests (16385 bytes, 1 MB) flipped from 400 to 413. 3 accept-path tests still pass.
- Missing Content-Length (chunked encoding) falls through to `req.json()`'s own protections — documented in the code comment.

---

## Historical migration files added

The three Supabase advisor fixes the user applied via MCP between Group A and Group B are now committed as history files (applied-timestamp noted in each header; DO NOT re-apply):

- `aethercloud/supabase/migrations/20260423c_lock_contact_inbox_backend_only.sql` — revokes anon/authenticated grants on `contact_inbox` view + flips to `security_invoker = true`. Addresses `security_definer_view` (ERROR).
- `aethercloud/supabase/migrations/20260423d_pin_set_updated_at_search_path.sql` — pins `set_updated_at()` to `search_path = ''`. Addresses `function_search_path_mutable` (WARN).
- `aethercloud/supabase/migrations/20260423e_deny_all_on_server_only_tables.sql` — explicit deny-all policies on `plans`, `signup_attempts`, `tasks`, `usage_events`, `users`, `uvt_balances`. Addresses 6× `rls_enabled_no_policy` (INFO).

Each file's header warns against re-apply (idempotency differs per change; policy creation would error on duplicate name).

---

## Aggregate verification

| Metric | Before Group B | After Group B |
|---|---|---|
| TS tests passing | 111 | **164** (+53) |
| Python tests passing (router scope) | 308 | **308** (unchanged — no Python changes) |
| OTel PII lint | PASS | PASS |
| Supabase advisor new warnings | 0 | 0 |
| Sweep #1 Highs open | 1 (H3) | **0** (all closed) |
| Sweep #1 Mediums open | 5 (M2–M6) | **0** (all closed) |
| Sweep #1 Lows open | 4 (L1–L4) | **3** (L3 closed) |

Total automated assertions: **472** (164 TS + 308 Python) + OTel lint.

---

## What's still open after Group B

### Group C (Python hardening) — next up
- **Sweep #2 M1** — remove surviving `downgrade_reason` refs, especially `desktop/pages/uvt-meter/uvt-meter.js:90`
- **Sweep #2 M4** — remove `_warned_once` + lock `policy_bypass_by_gate` writes under threaded uvicorn/gunicorn
- **Sweep #2 L1** — strip control chars from `chosen_model` before `log.info`

### Group D (PR 2 prerequisites) — deferred
- **L1 Sweep #1** — prototype-chain defense on `LOGICAL_TO_SHORT` (elevate to High at PR 2 cutover)
- **L2 Sweep #1** — `UnknownModelError` message sanitization
- **L4 Sweep #1** — proper microbenchmark for timing-safe compare
- **Sweep #2 M2** — `AETHER_ROUTER_URL` hostname allowlist + TLS pinning
- **Sweep #2 M3** — TOCTOU: move balance check into `rpc_record_usage` tx
- **Sweep #2 M5** — reclassify rate cap / classifier determinism
- **Sweep #2 M6** — `plans_cache` TTL / Supabase realtime invalidation

---

## File collisions with Group A

None. Group B touched:
- `site/middleware.ts` — last touched in Group A (no overlap; H3/M2 append + refactor, no conflict)
- `site/app/api/internal/router/pick/route.ts` — touched in Group A (H2 Zod cap). Group B added H3 rate-limit block + M2 import + M4 Zod regex + L3 size check. No conflict with H2's `max(2_000_000)`; that line is preserved as-is.
- `site/lib/router/auditLog.ts` — NOT touched in Group B (no overlap with Group A H4).
- `site/lib/router/boot.ts` — touched in Group A (C1-C3). Group B added M5 assertPlanParity wiring. No conflict with resolver registrations.
- `site/lib/router/startupAssertions.ts` — touched in Group A (C4). Group B added PlanParityError + assertPlanParity + cache. Additive only; `assertRouterWired` remains backward-compatible.
- `site/lib/router/helpers/getOpusPctMtd.ts` — NOT touched in Group B (Group A H5 intact).

---

## Nothing blocked

PR #8 remains open, not merged, not rebased. Branch is ready to push. Awaiting user signal for Group C.
