# Red Team Report — PolicyGate — 2026-04-22

**Scope:** Layer 1 (PolicyGate, TypeScript under `site/`). Layer 2 (Python orchestrator) is out of scope (red team #2).
**Branch under test:** `claude/suspicious-wright-619275` (PR 1 v5, unmerged).
**Tester:** Claude Opus 4.7 (1M context) as red team engineer per `redteam_prompt_1_policygate`.
**Verification report under adversarial review:** `tests/security/pr1_v5_verification_report.md`.

---

## Executive Summary

**Total findings: 19** — 4 Critical, 5 High, 6 Medium, 4 Low/Informational.

PolicyGate's design is clean (two-layer split, typed errors, `.strict()` Zod validation, dual service-token check, fire-and-forget audit), **but the production wire-up omits every server-side data fetch that would make the gates binding**. The HTTP route trusts client-supplied values for opus-MTD usage, UVT balance, and active-concurrent-tasks — the three numbers each of which would individually let an attacker burn any plan's budget. Combined, they amount to a complete gate no-op for any caller who already has the service token. The audit log is silent in the same way: the `setAuditWriter` wiring is exercised only in tests, so production writes go to the default no-op — `routing_decisions` receives zero rows.

Today these are masked because PR 1 v5 is explicitly in **shadow mode** (`ROUTER_CONFIG.shadow_mode = true`; Python caller hardcodes `opusPctMtd=0`, `activeConcurrentTasks=0`, `uvtBalance=1_000_000_000` — see `lib/uvt_routes.py:222-233`). The TS gate's output is logged, never used for substitution. **The moment PR 2 flips the constant, all three bypasses activate simultaneously** unless the orchestrator is also changed to pass real values AND the route is changed to resolve them server-side. PR 1 v5 lands the bugs pre-stocked for that flip.

**Top 3 risks** (pre-flip):
1. The audit log is always empty in production (`setAuditWriter` never wired) — billing/regulatory evidence cannot be reconstructed even though the shadow gate is "running."
2. Both ends of the Python ↔ TS contract pass hardcoded/zero values for gate inputs — once enforcement flips, no gate can fire for anyone (not even low-balance users).
3. `predicted_uvt_cost` is an `integer` column but the weighted formula (now in the audit row) can exceed `int32` for legitimate Opus + large-input requests — silent audit drop on insert.

**Posture:** not shippable to "enforce" without the 4 Critical fixes; acceptable as shadow-only if the audit-writer wire-up and the shadow-caller hardcoded values are treated as must-fix before PR 2.

---

## Critical Findings

### C1 — Client-supplied `opusPctMtd` bypasses `opus_pct_cap` gate
- **CVSS 3.1:** 8.6 — AV:N/AC:L/PR:H/UI:N/S:C/C:N/I:H/A:N (Privilege: High assumes stolen service token; impact is integrity of billing/plan enforcement).
- **File:** `site/app/api/internal/router/pick/route.ts:24, 61-67, 69-70`
- **Evidence:** Zod schema at L24 declares `opusPctMtd: z.number().min(0).max(1).finite()`. After `safeParse`, L70 passes `parse.data` (unchanged) into `pick(parse.data)`. `site/lib/router/helpers/getOpusPctMtd.ts:6` explicitly notes "Called by the API route BEFORE `pick()`" — but grep confirms no caller: only the helper file itself and the plan doc reference `getOpusPctMtd`.
- **Impact:** A Pro (`opus_pct_cap=0.10`) or Team (`opus_pct_cap=0.25`) user whose true MTD Opus spend is 99 % attests `opusPctMtd: 0`. `ctx.opusPctMtd >= plan.opus_pct_cap` → `0 >= 0.1` → false → gate passes. Attacker runs unlimited Opus; their audit-row `opus_pct_mtd_snapshot` matches the lie, so post-hoc analytics cannot detect the abuse.
- **PoC:** `tests/security/policygate/poc_2_4_client_opus_pct_mtd_bypass.ts`
- **Fix (PR-ready):**
  ```diff
  @@ site/app/api/internal/router/pick/route.ts
  @@
  +import { createClient } from "@supabase/supabase-js";
  +import { getOpusPctMtd } from "@/lib/router/helpers/getOpusPctMtd";
  +
  +const supabase = createClient(
  +  process.env.SUPABASE_URL!,
  +  process.env.SUPABASE_SERVICE_ROLE_KEY!,
  +);
   const RoutingContextSchema = z
     .object({
       userId: z.string().uuid(),
       tier: z.enum(["free", "solo", "pro", "team"]),
       taskKind: z.enum([...]),
       estimatedInputTokens: z.number().int().nonnegative().finite(),
       estimatedOutputTokens: z.number().int().nonnegative().finite(),
  -    opusPctMtd: z.number().min(0).max(1).finite(),
  -    activeConcurrentTasks: z.number().int().nonnegative().finite(),
  -    uvtBalance: z.number().int().nonnegative().finite(),
       requestId: z.string().min(1).max(256),
       traceId: z.string().min(1).max(256),
     })
     .strict();
  @@
  -  try {
  -    const decision = pick(parse.data);
  +  try {
  +    const [opusPctMtd, uvtBalance, activeConcurrentTasks] = await Promise.all([
  +      getOpusPctMtd(parse.data.userId, { supabase }),
  +      getUvtBalance(parse.data.userId, { supabase }),
  +      getActiveConcurrentTasks(parse.data.userId, { supabase }),
  +    ]);
  +    const decision = pick({ ...parse.data, opusPctMtd, uvtBalance, activeConcurrentTasks });
  ```

### C2 — Client-supplied `uvtBalance` bypasses `InsufficientUvtBalance` gate
- **CVSS 3.1:** 9.0 — AV:N/AC:L/PR:H/UI:N/S:C/C:N/I:H/A:H (unmetered inference).
- **File:** `site/app/api/internal/router/pick/route.ts:26, 61-67`; `site/lib/router/deterministic.ts:90`
- **Evidence:** Same pattern as C1. `uvtBalance` is Zod-validated as `z.number().int().nonnegative().finite()`, passed through to `pick()`, and compared directly at `deterministic.ts:90` (`if (enforced > ctx.uvtBalance)`). No server-side read of `public.uvt_balances`.
- **Impact:** Attacker attests `uvtBalance = Number.MAX_SAFE_INTEGER`. Every request passes the balance gate regardless of the user's actual balance. Combined with C1 the attacker gets unmetered Opus.
- **PoC:** `tests/security/policygate/poc_2_4_client_uvt_balance_bypass.ts`
- **Fix:** Same diff as C1 — resolve from `public.uvt_balances` server-side.

### C3 — Client-supplied `activeConcurrentTasks` bypasses `concurrency_cap` gate
- **CVSS 3.1:** 7.5 — AV:N/AC:L/PR:H/UI:N/S:C/C:N/I:H/A:L
- **File:** `site/app/api/internal/router/pick/route.ts:25`; `site/lib/router/deterministic.ts:60`
- **Evidence:** Identical trust-the-client pattern. The architecture doc admits the field is "advisory" and defers race-proof concurrency (`Deferrals` list). But PR 1 v5 accepts the field as the SOURCE OF TRUTH, not as an advisory — the gate uses no other data.
- **Impact:** Pro plan (`concurrency_cap = 3`) loses its hard cap. Downstream infra cost scales with attacker concurrency; tail-latency of shared services degrades. TOCTOU compounds this: even if a server-side counter were added, N simultaneous POSTs would all observe pre-increment count.
- **PoC:** `tests/security/policygate/poc_2_4_client_concurrency_bypass.ts`
- **Fix:** Fetch from a counter source (pg advisory lock, Redis INCR, or a dedicated `active_tasks` table) server-side; drop field from schema. PR 2-scoped race-proof concurrency is acknowledged in the architecture doc but the shipped-today gate should at minimum read a server-resolved snapshot.

### C4 — Production audit writer is never wired; `routing_decisions` stays empty
- **CVSS 3.1:** 7.1 — AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N (evidence-integrity)
- **File:** `site/lib/router/auditLog.ts:29-45, 120-129`; `site/app/api/internal/router/pick/route.ts` (no import)
- **Evidence:** `auditLog.ts:31` declares `let _writer: AuditWriter = noopWriter;` as the module default. `makeSupabaseAuditWriter` is exported but never instantiated. Grep confirms `setAuditWriter` is referenced only from `site/tests/**`. The route does not import or call it.
- **Impact:** In production, every call to `pick()` → `recordDecisionAsync/recordGateAsync` → `fireAndForget` → `noopWriter()`. The `routing_decisions` table receives zero rows. The verification report §12.4 explicitly admits "NOT RUN — migration file written but NOT applied" — which means this was never observed, but the code path is unambiguous. Billing and regulatory evidence claims collapse.
- **PoC:** `tests/security/policygate/poc_2_5_audit_writer_never_wired.ts`
- **Fix (PR-ready):**
  ```diff
  @@ site/lib/router/boot.ts (new)
  +import { createClient } from "@supabase/supabase-js";
  +import { setAuditWriter, makeSupabaseAuditWriter } from "@/lib/router/auditLog";
  +
  +let booted = false;
  +export function ensureRouterBooted(): void {
  +  if (booted) return;
  +  const url = process.env.SUPABASE_URL;
  +  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  +  if (!url || !key) throw new Error("Supabase env vars missing for audit writer");
  +  const supabase = createClient(url, key, { auth: { persistSession: false } });
  +  setAuditWriter(makeSupabaseAuditWriter(supabase));
  +  booted = true;
  +}
  @@ site/app/api/internal/router/pick/route.ts
  +import { ensureRouterBooted } from "@/lib/router/boot";
  ...
   export async function POST(req: Request): Promise<Response> {
  +  ensureRouterBooted();
     if (!isValidServiceToken(...)) { ... }
  ```
  Add a CI assertion (integration test that runs the route and checks that `setAuditWriter`-installed writer was the Supabase one, e.g. by checking the active writer against a marker function). Without this, regressions are invisible.

---

## High Findings

### H1 — Python shadow caller hardcodes gate-input fields
- **File:** `lib/uvt_routes.py:220-233`
- **Evidence:** The shadow dispatch sends `opusPctMtd: 0.0`, `activeConcurrentTasks: 0`, `uvtBalance: 1_000_000_000` verbatim on every call.
- **Impact:** Today (shadow mode) this makes the `routing_decisions` snapshots useless for finance analytics — every row claims the user had 0 % Opus MTD and a billion UVT. On the PR 2 flip day, if only the constant is changed and this caller is not updated, all four gates silently no-op.
- **Severity:** HIGH (operational foot-gun pre-loaded for flip day).
- **Fix:** In `uvt_routes.py`, resolve these from the existing Stage E balance / concurrency / opus-pct sources before the shadow dispatch; or move the fetch entirely to the TS route (preferred — see C1/C2/C3 patch).

### H2 — `predicted_uvt_cost` integer overflow → dropped audit row
- **File:** `aethercloud/supabase/migrations/20260422_routing_decisions.sql:45-46`; `site/lib/router/deterministic.ts:82-83`
- **Evidence:** Both `predicted_uvt_cost` and `predicted_uvt_cost_simple` are declared `integer` (int32). Attacker-controlled `estimatedInputTokens` has no explicit cap in the schema or the gate. For Opus: `Math.ceil((input * 1 + output * 4) * 5)`. With `input=500_000_000, output=32_000` (within team output_cap), weighted cost ≈ 3.2 × 10⁹ — overflows `int32`. Postgres insert fails; `fireAndForget`'s catch swallows it.
- **Impact:** Authenticated Opus-eligible users who can shape `estimatedInputTokens` wipe their audit footprint. Combined with C2 (balance bypass) this is a turn-key cost-and-evidence attack.
- **PoC:** `tests/security/policygate/poc_2_5_integer_overflow_audit_gap.ts`
- **Fix:**
  ```diff
  @@ aethercloud/supabase/migrations/20260422_routing_decisions.sql
  -  predicted_uvt_cost        integer,
  -  predicted_uvt_cost_simple integer,
  -  actual_uvt_cost           integer,
  +  predicted_uvt_cost        bigint,
  +  predicted_uvt_cost_simple bigint,
  +  actual_uvt_cost           bigint,
  ```
  AND add an input-token cap in `RoutingContextSchema`:
  ```diff
  -  estimatedInputTokens: z.number().int().nonnegative().finite(),
  +  estimatedInputTokens: z.number().int().nonnegative().max(2_000_000).finite(),
  ```

### H3 — No IP / user rate limit on `/api/internal/router/pick`
- **File:** `site/middleware.ts` (absent)
- **Evidence:** Middleware only checks the service token. There is no IP bucket, no authenticated per-user bucket, no sliding window. The redteam prompt §2.7 assumes one exists ("With the IP rate limit for unauthenticated requests, how long to brute force a 256-bit token?") — there isn't one.
- **Impact:** Service-token brute-force is limited only by Vercel's per-function invocation ceiling. 256-bit space is still infeasible, but (a) any future shorter-token or dev fallback becomes trivially brute-forceable, and (b) the endpoint is trivially floodable (each 401 still spins a Vercel lambda = cost). Also amplifies H1/H2/C2 — no backoff on abusive authenticated-side floods.
- **Fix:** Add an Upstash/Redis fixed-window limiter in middleware, keyed by source IP for 401s and by userId for 200/4xx. Target 60 req/IP/min unauth'd, 600 req/user/min auth'd.

### H4 — Audit error handler swallows silently by default
- **File:** `site/lib/router/auditLog.ts:32-37, 52-60`
- **Evidence:** Default `_errorHandler` emits an OTel event, but nothing page-able. The catch block in `fireAndForget` explicitly swallows handler errors ("audit must never crash caller"). Combined with C4 (writer is noop) there's nothing to ever fire — but once C4 is fixed, any transient DB failure is invisible.
- **Impact:** Partitioned DB under pressure, network partition, RLS mis-config, partition roll-over missing (see M1) all cause audit-row drops. Without an alerting ladder, drops accumulate until someone notices the row count is suspiciously flat.
- **Fix:** Wire `_errorHandler` at boot to an `audit_writer_failed_total` OTel counter AND a Sentry capture. SRE alert: `rate(audit_writer_failed_total[5m]) > 0.01 * rate(router_pick_total[5m])` → page.

### H5 — `getOpusPctMtd` fails open on DB error (dead today, live after C1 fix)
- **File:** `site/lib/router/helpers/getOpusPctMtd.ts:58-65`
- **Evidence:** The helper's catch returns `0` on any RPC error and emits `router.opus_cap_bypassed_fail_open`. The prompt explicitly flags this ("Is there a test seam... injected into a production bundle?" — no, but the fail-open is built-in).
- **Impact:** Once C1 is fixed and the route actually calls `getOpusPctMtd`, a Supabase outage or a transient RPC error yields `0 >= plan.opus_pct_cap = 0.1` → false → gate passes. DB down = Opus free for everyone.
- **Fix:** Fail closed. Cache last-known-good value with a short TTL; if cache also missing, return `1.0` (always block Opus) not `0`.

---

## Medium Findings

### M1 — Partition window ends 2027-03-31; no roll-forward job
- **File:** `aethercloud/supabase/migrations/20260422_routing_decisions.sql:65-85`
- **Evidence:** `DO $$ … FOR i IN 0..11 …` seeds 12 monthly partitions starting 2026-04-01. PR 1 defers pg_cron roll-forward. After 2027-04-01, inserts with `created_at = now()` error with "no partition of relation found." Combined with H4 this is invisible.
- **PoC:** `tests/security/policygate/poc_2_12_partition_exhaustion.sql`
- **Fix:** Add a pg_cron job OR a `DEFAULT` partition; ship as follow-up migration today, not "in PR 2."

### M2 — Hand-rolled constant-time compare leaks token length
- **File:** `site/middleware.ts:3-8`; `site/app/api/internal/router/pick/route.ts:32-37`
- **Evidence:** `if (a.length !== b.length) return false;` early-returns before the XOR loop. The verification report admits the Windows timing test was relaxed to a 60 % noise ceiling. In isolation the length oracle leaks only that the server token is 64 hex chars (openssl `rand -hex 32`), a weak signal. Worse: two separate copies of this function in two files drift risk.
- **PoC:** `tests/security/policygate/poc_2_1_token_length_oracle.ts`
- **Fix:**
  ```diff
  -function constantTimeEqual(a: string, b: string): boolean {
  -  if (a.length !== b.length) return false;
  -  let diff = 0;
  -  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  -  return diff === 0;
  -}
  +import { timingSafeEqual } from "node:crypto";
  +function constantTimeEqual(a: string, b: string): boolean {
  +  const ab = Buffer.from(a, "utf8");
  +  const bb = Buffer.from(b, "utf8");
  +  if (ab.length !== bb.length) {
  +    // pad both to the longer length so the length check doesn't leak
  +    const n = Math.max(ab.length, bb.length, 1);
  +    return timingSafeEqual(
  +      Buffer.concat([ab, Buffer.alloc(n - ab.length)], n),
  +      Buffer.concat([bb, Buffer.alloc(n - bb.length)], n),
  +    ) && ab.length === bb.length;
  +  }
  +  return timingSafeEqual(ab, bb);
  +}
  ```
  Extract into `site/lib/router/serviceToken.ts` and import from both call sites.

### M3 — Token rotation window controlled only by env-var presence
- **File:** `site/middleware.ts:10-26`
- **Evidence:** The doc rotation runbook relies on an operator manually unsetting `AETHER_INTERNAL_SERVICE_TOKEN_PREV` at end-of-overlap. There is no timestamp-bounded window in code. If an operator forgets, PREV is valid indefinitely.
- **Impact:** Leaked PREV token remains valid until manual unset. No TTL, no alerting on PREV-auth'd requests.
- **Fix:** Emit an OTel counter `router.prev_token_used_total` when PREV matches. Alert on any traffic after rotation+24 h. Or add `AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT` and skip PREV once past that.

### M4 — trace_id / request_id echoed in response without sanitization
- **File:** `site/app/api/internal/router/pick/route.ts:76-91`
- **Evidence:** The route returns `trace_id: parse.data.traceId` verbatim in both success and gate bodies. Zod constrains length `(1..256)` but nothing else — newlines, ANSI escapes, and control characters are allowed. JSON encoding escapes `\n` and `"` but not e.g. `` (ESC) in the string payload.
- **Impact:** Low in an HTTP JSON envelope (clients generally don't re-render the field). Higher concern is the audit row: `trace_id` lands in `routing_decisions.trace_id text` unescaped, which corrupts log dashboards and grep lines that split on newlines.
- **Fix:** Regex-restrict at schema level:
  ```diff
  -  traceId: z.string().min(1).max(256),
  -  requestId: z.string().min(1).max(256),
  +  traceId: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
  +  requestId: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/),
  ```

### M5 — `PLAN_CAPS` hardcoded without boot-time DB assertion
- **File:** `site/lib/router/constants.ts:27-60` ("locked against live public.plans … in startupAssertions.ts"); grep finds no `startupAssertions.ts` in the repo.
- **Evidence:** Plan doc §"Plans table ground truth (locked)" promises a boot-time assertion file. It doesn't exist. The comment at L26-27 is aspirational.
- **Impact:** If an operator updates the `public.plans` row (e.g. new pricing), the TS constants drift silently. A Solo user paying for `uvt_monthly = 400000` still gets enforced against the old value until someone ships a TS patch.
- **Fix:** Ship `site/lib/router/startupAssertions.ts`; call `assertPlanParity()` from the `ensureRouterBooted()` added in C4.

### M6 — `ROUTER_CONFIG.shadow_mode` frozen but no test that it's `true` at build time
- **File:** `site/lib/router/config.ts`
- **Evidence:** `Object.freeze({ shadow_mode: true, canary_user_ids: [] })`. There's no CI test that asserts `shadow_mode === true` for PR 1's main branch.
- **Impact:** The "safety net" is one line with no signature gate. A bad merge or an over-eager ops change to the constant ships PR 2-style enforcement without the prerequisites (C1-C4 fixes).
- **Fix:** Add `site/tests/unit/router.config.test.ts` asserting `shadow_mode === true` and `canary_user_ids.length === 0` — flip the assertions intentionally only in the PR 2 commit.

---

## Low / Informational Findings

### L1 — Plain-object model-id map allows prototype-chain escape under future `requestedModel`
- **File:** `site/lib/router/model_id_map.ts:19-25`; `site/lib/uvt/compute.ts:35-38`
- **PoC:** `tests/security/policygate/poc_2_11_model_id_map_prototype.ts`
- **Severity:** LOW today (model_id always trusted). HIGH when PR 2 ships `requestedModel`.
- **Fix:** Either `if (!Object.hasOwn(MAP, key))` guards, or convert `LOGICAL_TO_SHORT` and `MODEL_MULTIPLIERS_V1` to `new Map<string, …>()`.

### L2 — `UnknownModelError` leaks model_id in message string
- **File:** `site/lib/uvt/errors.ts:3`
- **Severity:** Informational — only trusted values flow through in PR 1; no PII.
- **Fix:** None required now. Keep in mind for PR 2.

### L3 — No HTTP body size limit configured
- **File:** `site/app/api/internal/router/pick/route.ts` (no `export const bodyParser` override)
- **Severity:** Informational — Vercel default is 4.5 MB, sufficient for a small RoutingContext.
- **Fix:** Add `export const config = { api: { bodyParser: { sizeLimit: '16kb' } } };` or validate `Content-Length ≤ 8 KB` in middleware.

### L4 — Verification report's constant-time test is admitted-weak
- **File:** `site/tests/integration/router.middleware.test.ts:53-77`
- **Evidence:** 60 % catastrophic-leak ceiling. The real implementation is only as strong as the XOR-reduce; the test exists primarily to guard against a future regression to `===`.
- **Severity:** Informational. Fixed for real by M2.

---

## §2.9 Known Zero-Day Class Checklist

| Class | Verdict | Evidence |
|---|---|---|
| SSRF via any URL field | ABSENT | No `fetch(…)` / `URL(…)` / `new Request(url)` construction in `site/lib/router/**`. Only the Python client fetches PolicyGate, not vice versa. |
| SQL injection | ABSENT | Audit writer uses `supabase.from('routing_decisions').insert(row)` — parameterized. `rpc_opus_pct_mtd` takes `uuid` typed arg; body uses `filter (where model = 'opus')` literal, no concat. |
| NoSQL injection | N/A | Postgres only. |
| ReDoS | ABSENT | No user-input regex in router code; Zod schemas use `.uuid()`/`.enum()` only. traceId/requestId currently unrestricted (see M4) but no regex. |
| XXE / XML external entity | N/A | JSON only; no XML parser imported. |
| Deserialization (eval / Function / vm) | ABSENT | Grep `eval\(\|Function\(\|vm\.` in `site/lib/router/`: no matches. `JSON.parse` only on trusted fixtures inside tests. |
| CRLF injection | ABSENT | Response headers are only the `content-type` constant; no dynamic `set` of header values from user input. |
| Open redirect | N/A | Internal POST endpoint; no `Location` responses. |
| SSRF to AWS metadata (169.254.169.254) | ABSENT | No outbound HTTP from the route. |
| Cache poisoning | ABSENT | No `Cache-Control` set. Next.js API route returns `force-dynamic`; Vercel Edge does not cache POST. |
| Race condition on rotation | PRESENT (informational) | M3 — PREV remains accepted until operator unsets env. |
| Trusted-proxy XFF forgery | ABSENT | No `x-forwarded-for` read anywhere in `site/lib/router/**`. |
| Prototype pollution via body | ABSENT | Zod `.strict()` rejects `__proto__`, `constructor`, `prototype` unknown keys (see PoC 2.3). |
| Prototype-chain escape in internal map | PRESENT (L1) | `LOGICAL_TO_SHORT['toString']` yields `Object.prototype.toString`. Not reachable with current inputs. |

---

## Negative Findings (Coverage Proof — tried and defeated by existing controls)

1. **Body-level prototype pollution via `{ "__proto__": {...} }`** — Zod `.strict()` rejects at validation (PoC 2.3).
2. **Matcher-case bypass `/api/INTERNAL/router/pick`** — Next.js matcher is case-sensitive; route file only exists at lowercase path; path 404s before middleware bypass matters.
3. **CORS preflight bypass** — No `OPTIONS` handler; middleware checks token for all methods under matcher; no `Access-Control-Allow-*` leakage.
4. **NaN `opusPctMtd` fail-open (`NaN >= cap` is false → pass)** — Zod `.finite()` rejects NaN / Infinity before `pick()` sees it (PoC 2.3).
5. **Stringified number `"100"` coerced to `100`** — Zod v3 does not coerce by default; rejected.
6. **Float `output_tokens = 0.5`** — `.int()` rejects.
7. **Trailing zero-width space in `tier: "pro​"`** — `z.enum([...])` uses strict string equality; rejected.
8. **Negative `estimatedInputTokens: -1`** — `.nonnegative()` rejects.
9. **`requestId` 10 KB long** — `.max(256)` rejects.
10. **Duplicate `x-aether-internal` header via header injection** — `Request.headers.get()` returns the first value only; a second occurrence cannot spoof. (Edge/Node runtimes normalize.)
11. **Forged service-token inference via error body** — 401 response body is `{ "error": "unauthorized" }` constant; no echo of env, token prefix, length, or timestamp.
12. **Direct invocation via Vercel function URL bypassing custom-domain middleware** — Next.js bundles middleware with the route; the matcher is compiled into the deployment, not the hostname. A `*.vercel.app` preview URL still runs middleware.
13. **Anthropic SDK imported into `site/`** — `grep -rE "@anthropic-ai/sdk|api\.anthropic\.com" site/lib/ site/app/` returns no matches. The direct-call bypass does not exist.
14. **RLS bypass on `routing_decisions` via child-partition SELECT** — follow-up migration `20260422b_routing_decisions_partition_rls.sql` enables RLS + mirrors the `own rows` policy on each partition child. Verified by migration review.
15. **`rpc_opus_pct_mtd` exposed to `authenticated` role** — `REVOKE ALL ... FROM public; GRANT EXECUTE ... TO service_role;` — only service role can call; regular users cannot learn another user's Opus share.
16. **`INSERT` forging of audit rows by non-service-role** — parent table has RLS enabled with NO `for insert` policy; authenticated role therefore cannot insert. Partition children inherit the restriction.
17. **Opus leak to Free tier via table manipulation** — `DEFAULT_MODEL_BY_TIER_AND_TASK` is `Object.freeze`-wrapped; attacker cannot mutate at runtime. Table values for Free tier are all `claude-haiku-4`.
18. **JSON parse bomb with deeply nested object** — Zod `.strict()` + top-level object shape is flat; depth of user-reachable parsing is 1.

---

## Recommendations — Prioritized

**Must-fix before any move toward enforcement (blocks PR 2 flip):**
1. **C1/C2/C3 combined patch** — server-resolve `opusPctMtd`, `uvtBalance`, `activeConcurrentTasks`; drop from schema.
2. **C4** — wire `makeSupabaseAuditWriter` at boot; add CI integration test asserting the wired writer targets `routing_decisions`.
3. **H1** — update `lib/uvt_routes.py` shadow dispatch to pass real values (or remove the fields from the request entirely once C1-C3 land).
4. **H2** — migrate `predicted_uvt_cost*` columns to `bigint`; cap `estimatedInputTokens` at `2_000_000`.

**Fix within 30 days (audit-integrity + hardening):**
5. **H3** — add IP + user rate limits in middleware.
6. **H4** — wire `setAuditErrorHandler` to an alert-eligible counter.
7. **H5** — `getOpusPctMtd` fails closed, not open.
8. **M1** — ship partition-roll-forward migration now, not PR 2.
9. **M2** — replace hand-rolled `constantTimeEqual` with `crypto.timingSafeEqual`; extract into one module.
10. **M5** — ship `startupAssertions.ts` with DB parity checks.

**Backlog / defense-in-depth:**
11. M3 — PREV token TTL + alerting on PREV use.
12. M4 — regex-restrict `traceId` / `requestId`.
13. M6 — test-asserted `shadow_mode === true` in PR 1 main.
14. L1 — `Object.hasOwn`/`Map` guards on internal lookups (blocks PR 2 `requestedModel` escape).
15. L3 — 16 KB body size cap.

---

## Test Artifacts

All under `tests/security/policygate/`:

- `poc_2_1_token_length_oracle.ts` — Vitest, documents length-mismatch early return.
- `poc_2_2_e2e_curl.sh` — bash, end-to-end unauth'd 401 + auth'd triple-bypass against a local dev server.
- `poc_2_2_http_method_confusion.ts` — Vitest, method/matcher coverage.
- `poc_2_3_zod_number_edge_cases.ts` — Vitest, Zod rejection coverage (NaN/Infinity/float/string/proto/zero-width-space/overlength).
- `poc_2_4_client_opus_pct_mtd_bypass.ts` — Vitest, Opus gate bypass (C1).
- `poc_2_4_client_uvt_balance_bypass.ts` — Vitest, balance gate bypass (C2).
- `poc_2_4_client_concurrency_bypass.ts` — Vitest, concurrency gate bypass (C3).
- `poc_2_5_audit_writer_never_wired.ts` — Vitest, audit default-noop (C4).
- `poc_2_5_integer_overflow_audit_gap.ts` — Vitest, int32 overflow (H2).
- `poc_2_10_shadow_mode_flip_value_theft.ts` — Vitest, simple↔weighted gap documentation.
- `poc_2_11_model_id_map_prototype.ts` — Vitest, prototype-chain escape in plain-object map (L1).
- `poc_2_12_partition_exhaustion.sql` — commented-only documentation PoC, do not execute.

**Execution:** from `site/`, `npm test -- tests/security/policygate/`. The curl PoC requires `npm run dev` + `ATK_TOKEN=…`.

---

## Appendix — Boundary Findings (flag for red team #2)

- **H1** is a cross-layer bug — the TS gate side is fine *if* it resolves fields server-side; the Python side is fine *if* it passes real values. Neither side currently does. Red team #2 should confirm that `lib/uvt_routes.py:215-236` is the only shadow-dispatch call site and that no other Python caller passes stale inputs.
- The client-supplied field trust (C1-C3) is a function of the *TS route*, but any Python caller that imitates the orchestrator today (e.g. a leaked-service-token adversary calling PolicyGate directly) can exploit it just as cleanly. Red team #2's service-token exfil surface (TokenAccountant, Stage A) is the amplifier.

---

*End of report.*
