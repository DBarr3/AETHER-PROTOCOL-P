# Session A — Checkout → License → Download → Working App E2E Verification

**Branch:** `claude/verify-checkout-to-working-app-e2e`  
**Date:** 2026-04-24  
**Scope:** Verification-only. No production code changes. Follow-up tickets per gap.

---

## Confirmed UVT Quota Values (Live Supabase `public.plans`)

| tier | display_name | price | uvt_monthly | sub_agent_cap | concurrency_cap | overage (per 1M UVT) |
|------|-------------|-------|-------------|---------------|-----------------|----------------------|
| free | Free | $0 | **15,000** | 5 | 1 | — |
| solo | Starter | $19.99 | **400,000** | 8 | 1 | $49.00 |
| pro | Pro | $49.99 | **1,500,000** | 15 | 3 | $35.00 |
| team | Team | $89.99 | **3,000,000** | 25 | 10 | $32.00 |

Source: `SELECT * FROM public.plans ORDER BY price_usd_cents` — all 4 tiers active.  
Note: `solo` display_name in DB is `"Starter"`, not `"Solo"`.  
Note: `843k / 1.42M` UVT values referenced in spec do **not** appear anywhere in the codebase — UVT data is fully DB-driven.

---

## Live Supabase DB State

- `public.users`: 4 rows (free, solo, pro, team — all seeded 2026-04-23)
- All 4 rows: `subscription_status = 'active'`, `license_key = NULL`
- `public.profiles`: 0 rows
- `public.uvt_balances`: tracks consumption per user/period (quota comes from `public.plans`)
- Missing columns on `public.users`: `plan`, `uvt_quota`, `uvt_remaining`, `status`
  (Spec asserts these; they do not exist — see Gap #2 below)

---

## Step 1 — Checkout → Supabase User Row

**Status: ❌ FAIL — untestable + structural gaps**

- Real Stripe test-mode checkout was NOT run (requires browser automation outside this env)
- Spec asserts `uvt_quota`, `uvt_remaining`, `status` on `public.users` — **these columns do not exist**
- Correct columns are: `tier`, `license_key`, `subscription_status`, `current_period_end`
- `license_key` column exists but is NULL for all 4 existing users — webhook has never run successfully against this DB
- License key pattern would match: `AETH-CLD-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}` ✅ (in edge function code)
- `subscription_status = 'active'` ✅ (in edge function code)

**Gap #1:** Two competing webhook implementations target different tables:
- `aethercloud/supabase/functions/stripe-webhook/index.ts` → writes `public.users`
- `supabase/functions/stripe-webhook/index.ts` → writes `public.profiles` + `public.licenses`
- It is not known which URL is registered in the Stripe dashboard. If the newer path is active, `public.users` never gets written.

**Gap #2:** Spec assertions for `uvt_quota`, `uvt_remaining`, `status` must be rewritten:
- `uvt_quota` → query `public.plans WHERE tier = users.tier` → `uvt_monthly`
- `uvt_remaining` → `uvt_monthly - (SELECT total_uvt FROM uvt_balances WHERE user_id = ...)`
- `status` → column is named `subscription_status`

**Gap #3:** `create-checkout-session` edge function has no `aether_cloud_solo` entry in its `PLAN_TO_ENV` map. Solo/Starter checkout will 500 unless `STRIPE_PRICE_SOLO` env var is set with the legacy fallback name.

---

## Step 2 — License Email via Resend

**Status: ⚠️ UNVERIFIED — code exists, delivery unconfirmed**

- `aethercloud/supabase/functions/stripe-webhook/index.ts` calls Resend after upsert ✅ (in code)
- Email is expected to contain: license key + download link
- Cannot verify actual Resend delivery — no test-mode checkout was run
- Resend webhook logs and API cannot be queried without credentials in this env
- Download link in email points to `api.aethersystems.net/downloads/` — see Step 4 gap

---

## Step 3 — PostHog `checkout_completed` Event

**Status: ❌ FAIL — fires at wrong time, wrong identity**

- Event IS fired from `site/app/api/checkout/route.ts`
- Fires on **Stripe session creation**, not on payment completion — user may abandon without paying
- `distinctId` is hardcoded `"anonymous"` — no user identity attached
- Properties emitted: `tier`, `latency_ms`, `session_id_prefix` (8 chars only), `requestId`
- Spec asserts `plan`, `license_key_hash`, `amount` properties — **none of these exist on the event**
- `checkout_started` event fires **twice** on happy path (once client-side from PricingCard, once server-side)

**Gap #4:** `checkout_completed` must be moved to a real webhook handler (post-payment), not session creation. Spec's asserted properties (`license_key_hash`, `amount`) are not in the current event.

---

## Step 4 — Installer → Payload → Manifest Verification

**Status: ❌ FAIL — critical infrastructure missing**

- Windows VM/headless installer run was NOT performed (outside current env scope)

**Gap #5 (CRITICAL):** No `/downloads/` route exists in `api_server.py`. The Rust installer hardcodes:
  - `https://api.aethersystems.net/downloads/manifest-latest.json`
  - `https://api.aethersystems.net/downloads/manifest-latest.sig`
  No Python handler or nginx static-file mount serves these paths. Installer will fail on first run.

**Gap #6:** Spec says `payload_sha256 = 9d1e5d3b002fbe84baa513172c1576577acbb489b9f1b0e7dc55713816acbc19` and payload is `AetherCloud-L-Payload-0.9.7.exe`. Manifest in repo (worktree copy) shows:
  - `payload_filename: AetherCloud-L-Payload-0.9.8.exe` (0.9.8, not 0.9.7)
  - `payload_sha256: 878da3cf3c8e1bc7a27064cfa2a995a066656cc1b9c5215409d2161b210c6d4a` (hash mismatch)
  - Spec's hash and filename are stale/incorrect

**Gap #7:** `manifest-latest.json` only exists in a git worktree, not the main working tree. No canonical copy is checked in to main.

**Gap #8:** Tauri updater `pubkey` field in `desktop-installer/src-tauri/tauri.conf.json` is `""` (empty string) — update signature verification is disabled.

**Gap #9:** `manifest.pubkey_ed25519 = 787bfb057...` vs spec's `b9f4d6d5...`. Installer ignores the manifest's `pubkey_ed25519` field and uses a compile-time pinned key (`b9f4d6d5...`). The field in the manifest is misleading but not a functional bug.

---

## Step 5 — App Launch → License Activation → UVT Balance

**Status: ⚠️ PARTIAL — architecture correct, wiring incomplete**

- License activation endpoint exists: `POST https://license.aethersystems.net/api/license/license/cloud/validate` ✅
- Validates against `public.users.license_key` ✅
- Returns `{valid, plan, expires_at, client_id}` — `uvt_quota` NOT in response (spec asserts it is)
- UVT meter reads real data from `GET /account/usage` — no mocked values ✅
- All 4 existing DB users have `license_key = NULL` — activation would return `valid: false` for all

**Gap #10:** License validation response does not return `uvt_quota` or `signed_token`. Spec asserts both. `uvt_quota` is not derivable from the validate endpoint alone — client needs a separate `/account/usage` call.

**Gap #11:** UVT meter only mounts if `AETHER_UVT_ENABLED` feature flag returns true from `/healthz/flags`. If the flag is off (staged rollout), the meter silently does not appear — no user-visible explanation.

**Gap #12:** No plan badge widget in the dashboard. `result.plan` is stored in `auth-store` after login but is never rendered as a "Solo / Pro / Team" label in the sidebar. Tier only surfaces inside the UVT popover via `/account/usage`.

---

## Step 6 — Post-Activation Persistence (Relaunch)

**Status: ⚠️ PARTIAL — code correct, edge case gap**

- `auth-store.js` uses `electron-store` with machine-bound AES encryption ✅
- Persists: `sessionToken`, `userId`, `licenseKey`, `plan`, `rememberMe`, `lastLogin` ✅
- `tryRestoreSession()` in `login.html` restores session on relaunch via `POST /auth/verify` ✅
- Actual relaunch test was NOT run (requires the installed app)

**Gap #13:** `auth:clear` IPC handler (sign-out) deletes `sessionToken`, `userId`, `email` but leaves `licenseKey` and `plan` in the store. Stale plan value survives sign-out, causing incorrect plan data on next login if the server response is not read fresh.

---

## Step 7 — Free Tier Sanity Check

**Status: ⚠️ PARTIAL — backend correct, frontend upgrade flow broken**

- `free-signup/index.ts` edge function exists, creates users with `tier='free'` ✅
- `public.plans` has free tier: 15,000 UVT, concurrency=1, no overage ✅
- App can run without a license key (free tier path) ✅

**Gap #14:** No standalone upgrade prompt or modal exists in the app. The only upgrade CTA is inside the UVT meter popover, which:
  - Requires `AETHER_UVT_ENABLED` feature flag to be on
  - Calls `window.aetherUpgrade?.open(tier)` — this object is undefined in the codebase
  - Falls back to `window.location.hash = '#/upgrade?tier=...'` — no route handles this hash

Free users who never exhaust UVT will see no upgrade prompt at all.

---

## What Is NOT Yet Wired (Must Fix Before First Real Customer)

| # | Gap | Severity |
|---|-----|----------|
| 1 | Two competing Stripe webhooks (users vs profiles/licenses) — unclear which is active | CRITICAL |
| 2 | Spec assertions `uvt_quota`, `uvt_remaining`, `status` on `public.users` don't exist — rewrite spec | CRITICAL |
| 3 | All 4 existing DB users have NULL license_key — webhook never fired successfully | CRITICAL |
| 4 | No `/downloads/` route on api.aethersystems.net — installer will 404 on first run | CRITICAL |
| 5 | `checkout_completed` PostHog event fires on session create not payment; wrong identity | HIGH |
| 6 | `create-checkout-session` missing `aether_cloud_solo` — Starter checkout will 500 | HIGH |
| 7 | `manifest-latest.json` not in main repo tree; hash/filename in spec are stale | HIGH |
| 8 | License validate response omits `uvt_quota` and `signed_token` (spec expects both) | HIGH |
| 9 | No plan badge widget rendered in dashboard sidebar | MEDIUM |
| 10 | UVT meter silently absent when feature flag is off — no fallback message | MEDIUM |
| 11 | `window.aetherUpgrade` undefined — free-tier upgrade CTA is dead end | MEDIUM |
| 12 | `auth:clear` (sign-out) does not clear `licenseKey`/`plan` from auth-store | MEDIUM |
| 13 | Tauri updater pubkey is empty — update signature verification disabled | MEDIUM |
| 14 | `overage_usd_cents_used` always returns 0 (Stage H stub) | LOW |
| 15 | `checkout_started` event fires twice on happy path (client + server) | LOW |
| 16 | POSTHOG_KEY committed in `.env.example` plaintext | LOW |

---

## Verification Steps That Could NOT Be Fully Executed

The following require infrastructure outside this environment and must be completed by a human or CI runner:

- **Stripe test-mode checkout** (Steps 1, 2, 3): Requires browser + Stripe test card input
- **Resend delivery verification** (Step 2): Requires Resend API credentials
- **Windows installer run** (Step 4): Requires a Windows VM with the installer binary
- **App launch + license paste** (Steps 5, 6): Requires the installed Electron app running
- **Relaunch persistence** (Step 6): Requires the installed Electron app running twice
- **PostHog event confirmation** (Step 3): Requires PostHog API key + project ID

---

## Per-Tier Summary

| Step | Free | Solo | Pro | Team |
|------|------|------|-----|------|
| 1 — User row created | ⚠️ untested | ⚠️ untested | ⚠️ untested | ⚠️ untested |
| 1 — license_key in DB | ❌ NULL | ❌ NULL | ❌ NULL | ❌ NULL |
| 1 — uvt_quota column | ❌ col missing | ❌ col missing | ❌ col missing | ❌ col missing |
| 1 — subscription_status active | ✅ in DB | ✅ in DB | ✅ in DB | ✅ in DB |
| 2 — Resend email sent | ⚠️ untested | ⚠️ untested | ⚠️ untested | ⚠️ untested |
| 3 — PostHog event | ❌ wrong trigger | ❌ wrong trigger | ❌ wrong trigger | ❌ wrong trigger |
| 4 — /downloads/ endpoint | ❌ not wired | ❌ not wired | ❌ not wired | ❌ not wired |
| 4 — manifest SHA-256 | ❌ hash stale | ❌ hash stale | ❌ hash stale | ❌ hash stale |
| 5 — License activates | ⚠️ untested | ⚠️ untested | ⚠️ untested | ⚠️ untested |
| 5 — UVT meter shows quota | ⚠️ flag-gated | ⚠️ flag-gated | ⚠️ flag-gated | ⚠️ flag-gated |
| 5 — Plan badge shown | ❌ not wired | ❌ not wired | ❌ not wired | ❌ not wired |
| 6 — Relaunch activated | ⚠️ untested | ⚠️ untested | ⚠️ untested | ⚠️ untested |
| 7 — Free upgrade prompt | ❌ dead end | N/A | N/A | N/A |

**Legend:** ✅ Confirmed working · ⚠️ Not tested (infra required) · ❌ Confirmed broken/missing
