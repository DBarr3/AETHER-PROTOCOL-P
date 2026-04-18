# Vercel checkout site — design

**Status:** Approved with 5 additions (2026-04-17)
**Date:** 2026-04-17
**Companion doc:** `aethercloud/DEPLOY_WALKTHROUGH.md` (Supabase/Stripe webhook side)

---

## Context

The `aethercloud/` folder already contains Stripe-webhook + Supabase + Resend plumbing: when a customer pays, Stripe fires `checkout.session.completed` at a Supabase edge function, which generates an `AETH-CLD-XXXX-XXXX-XXXX` license, writes a `public.users` row, and emails the license.

What's missing is the front end: **no site exists for customers to click "Subscribe" on**. This spec defines a minimal Next.js app deployed to Vercel that presents four pricing tiers, routes paid tiers through Stripe Checkout, and routes the Free tier through a new Supabase edge function with abuse protection. PostHog analytics (project 386803, US cloud) is already set up in the repo root (`lib/posthog.ts`, `lib/track.ts`, `lib/server.ts`, `components/PostHogProvider.tsx`) and will be wired into every user-visible action.

All four Stripe products exist in Live mode; this spec does **not** re-create them.

---

## Scope

**In scope**

- `site/` folder at repo root: Next.js 14 App Router + Tailwind
- Pricing page with 4 tier cards (Free, Solo, Pro, Team)
- `/api/checkout` serverless route → Stripe Checkout Session for paid tiers
- `/success` and `/canceled` pages
- New Supabase edge function `free-signup` with CORS, IP rate limiting (3/hour), disposable-email blocking, PostHog server event
- Shared Supabase helpers at `aethercloud/supabase/functions/_shared/license.ts`
- PostHog wiring on every user-visible action + server-side revenue events
- New `public.signup_attempts` table for rate-limit tracking
- Corrections to previously-created `aethercloud/` files (tier CHECK constraint, env var naming, pricing, webhook PostHog events, deploy.sh pre-filled)
- Vercel deploy configuration

**Out of scope**

- Full marketing copy — cards have editable feature bullets
- Web auth / dashboard — license delivered by email, pasted into desktop app
- Custom domain DNS — `.vercel.app` URL works until later
- Token-usage metering for Free tier — enforced elsewhere (desktop / API server)
- Upgrade UI — v1 relies on signing up again with same email; webhook upsert handles the migration

---

## Tier structure

All four products already live in Stripe Live mode (account `acct_1TEceO3TqWOqdd87`). **Do not recreate.**

| Tier | Price | Stripe price ID | Checkout path |
|------|-------|-----------------|---------------|
| Free | $0/mo | `price_1TNKCm3TqWOqdd879Ih03NVe` | Skips Stripe — `free-signup` edge fn |
| Solo | $19/mo | `price_1TNKCm3TqWOqdd87AngxY9ks` | Stripe Checkout |
| Pro | $49/mo | `price_1TNKCm3TqWOqdd87vSXEHnVW` | Stripe Checkout |
| Team | $89/mo | `price_1TNKCm3TqWOqdd87FJIdQFI1` | Stripe Checkout |

`public.users.tier` stores one of `'free' | 'solo' | 'pro' | 'team'`. Existing migration's CHECK constraint (`'solo','team','pro'`) must be updated.

---

## Architecture

```
                                          PAID PATH
                                   (Solo / Pro / Team)
                                            │
                    track.checkoutStarted({tier, price_id: "unknown"})  ← PostHog (client)
                                            │
[Vercel site] ──POST /api/checkout──► [Vercel serverless]
                                            │
                                            ▼
                                    [Stripe hosted checkout]
                                            │
                         ┌──────────────────┼──────────────────┐
                         ▼                                      ▼
              [redirect to /success]               [webhook → stripe-webhook fn]
                                                             │
                                                             ├─► public.users upsert
                                                             ├─► Resend email license
                                                             └─► PostHog capture/ (fetch)
                                                                 checkout_completed
                                                                 (also subscription_canceled,
                                                                  payment_failed from their
                                                                  respective events)


                                          FREE PATH
                                          (Free tier)
                                              │
                                    track.signupStarted("pricing_page")    ← PostHog (client)
                                              │
[Vercel site] ──POST {email}──► [Supabase edge fn: free-signup]
 email field                           │
 "Get started free"                    ├─► CORS preflight handled
                                       ├─► IP rate-limit check (public.signup_attempts)
                                       ├─► Disposable-email domain block
                                       ├─► public.users upsert (tier='free')
                                       ├─► Resend email license
                                       └─► PostHog capture/ (fetch)  signup_completed
                                              │
                                              ▼
                                    browser receives {ok:true}
                                              │
                                    track.signupCompleted({method:"email"})  ← PostHog (client)
                                              │
                                   redirect to /success
```

Both paths converge on `public.users` + license email. `license_client.py` validates `AETH-CLD-*` regardless of origin.

---

## File structure

### `site/` at repo root

```
site/
├── package.json                    ← deps: next, react, tailwindcss, stripe, posthog-js, posthog-node
├── next.config.js
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── .env.example                    ← documents all env vars for local dev
├── app/
│   ├── layout.tsx                  ← wraps children in <PostHogProvider>
│   ├── globals.css                 ← Tailwind directives
│   ├── page.tsx                    ← hero + 4 PricingCard components
│   ├── success/page.tsx
│   ├── canceled/page.tsx
│   └── api/
│       └── checkout/route.ts       ← POST {tier} → Stripe Checkout Session URL
├── components/
│   ├── PostHogProvider.tsx         ← copied from repo root /components/
│   ├── PricingCard.tsx             ← paid-variant: calls track.checkoutStarted + POST /api/checkout
│   └── FreeSignupForm.tsx          ← email input, reads NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL from env
└── lib/
    ├── stripe.ts                   ← new — server Stripe client
    ├── tiers.ts                    ← new — tier metadata (name, price, features, priceId lookup by tier key)
    ├── posthog.ts                  ← copied from repo root /lib/
    ├── track.ts                    ← copied from repo root /lib/
    └── server.ts                   ← copied from repo root /lib/  (used in /api/checkout, not in Deno fns)
```

**Copy, don't symlink.** The four PostHog files currently live at repo root (`lib/posthog.ts`, `lib/track.ts`, `lib/server.ts`, `components/PostHogProvider.tsx`). They move to `site/lib/` and `site/components/` verbatim — no edits to their content. The originals at repo root can be deleted after the copy (they were a drop, not a shared module).

### Supabase functions — `aethercloud/supabase/functions/`

```
aethercloud/supabase/functions/
├── _shared/                        ← UNDERSCORE PREFIX IS LOAD-BEARING
│   └── license.ts                  ← NEW — shared helpers
├── stripe-webhook/
│   └── index.ts                    ← UPDATED — import from ../_shared/license.ts, add PostHog fetch calls
└── free-signup/                    ← NEW
    └── index.ts                    ← CORS, rate limit, disposable check, license, email, PostHog
```

The `_` prefix tells Supabase not to deploy `_shared` as its own function. Sibling functions import via `../_shared/license.ts` — relative paths only (Supabase doesn't resolve `@/` aliases in edge functions).

### `_shared/license.ts`

Exports:

```ts
export function generateLicenseKey(): string   // AETH-CLD-XXXX-XXXX-XXXX
export async function sendWelcomeEmail(to: string, licenseKey: string, tier: string, opts: {
  fromEmail: string; resendKey: string; appUrl: string;
}): Promise<void>
export async function captureServerEvent(opts: {
  posthogKey: string; posthogHost: string; distinctId: string; event: string; properties: Record<string, unknown>;
}): Promise<void>
```

`captureServerEvent` is a fetch POST to `${POSTHOG_HOST}/capture/` — works in Deno runtime where `posthog-node` does not. Payload shape:

```json
{"api_key":"phc_...","event":"checkout_completed","distinct_id":"user@example.com","properties":{"tier":"solo","price_id":"price_...","mrr":19}}
```

Swallows fetch errors (logs to console but never throws) — analytics must never break the webhook.

---

## free-signup/index.ts — detail

Deno edge function. Deploy with `--no-verify-jwt` (public endpoint).

**Responsibilities**

1. **CORS preflight.** On `OPTIONS`, respond 200 with:
   - `Access-Control-Allow-Origin: <match request Origin against allowlist>`
   - `Access-Control-Allow-Methods: POST, OPTIONS`
   - `Access-Control-Allow-Headers: Content-Type`
   - `Access-Control-Max-Age: 86400`

   Allowlist, in order:
   - `https://aethersystems.net`
   - The current Vercel deployment URL (configured via env var `ALLOWED_ORIGIN_VERCEL`, set at deploy time — can be either `.vercel.app` or custom)
   - `http://localhost:3000` (dev only — include if `Deno.env.get("ALLOW_LOCALHOST") === "true"`)

   Requests from unknown origins get 403 on OPTIONS. Non-OPTIONS requests from unknown origins still proceed (no Origin header check on POST, since CORS is a browser enforcement mechanism; the allowlist only controls preflight response).

2. **Method guard.** Non-POST returns 405.

3. **Body parse + email validation.** Read JSON, extract `email`, validate with `/^[^\s@]+@[^\s@]+\.[^\s@]+$/`. Reject empty / malformed with 400.

4. **Disposable-email block.** Hardcoded Set of ~60 common throwaway domains (`mailinator.com`, `guerrillamail.com`, `10minutemail.com`, `tempmail.org`, `trashmail.com`, `yopmail.com`, `throwawaymail.com`, etc.). Case-insensitive match on the domain portion. Reject with 400 "disposable email addresses are not accepted".

5. **IP rate limit.** Extract client IP:
   ```
   req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? req.headers.get("x-real-ip") ?? "unknown"
   ```
   Query `public.signup_attempts`: if ≥ 3 rows for this IP in the last hour, respond 429 "too many signups — please try again in an hour". Otherwise insert a new `signup_attempts` row.

6. **License issue.** Generate key, upsert `public.users` row (`onConflict: email`) with `tier='free'`, `subscription_status='active'`, `license_key=<generated>`. If the upsert collides with an existing non-free tier, still update the license_key but do NOT downgrade the tier — check existing row first.

7. **Welcome email.** `sendWelcomeEmail(email, licenseKey, 'free', ...)`.

8. **PostHog server event.** `captureServerEvent({ event: 'signup_completed', distinctId: email, properties: { tier: 'free', method: 'email' } })`. Fire-and-forget, but await before response so it flushes.

9. **Respond.** 200 with `{ ok: true }` + CORS headers echoing origin.

---

## stripe-webhook/index.ts — updates

Beyond the refactor to use `_shared/license.ts`:

- **PostHog events via fetch.** After every successful Supabase write:
  - `checkout.session.completed` → `captureServerEvent({ event: 'checkout_completed', distinctId: email, properties: { tier, price_id: priceId, mrr: priceAmountInDollars } })` where `priceAmountInDollars = (session.amount_total ?? 0) / 100`.
  - `customer.subscription.updated` → (no PostHog event — tier changes only, not revenue-relevant for v1).
  - `customer.subscription.deleted` → `captureServerEvent({ event: 'subscription_canceled', distinctId: customerEmail, properties: { stripe_customer_id: customerId } })`. Customer email must be looked up from the existing `public.users` row keyed on `stripe_customer_id`.
  - `invoice.payment_failed` → `captureServerEvent({ event: 'payment_failed', distinctId: customerEmail, properties: { stripe_customer_id: customerId, attempt_count: invoice.attempt_count } })`.

- **`PRICE_TO_TIER` map.** Keys for Solo / Pro / Team only — Free never triggers this webhook.

- **Env vars read:** existing set + `POSTHOG_KEY`, `POSTHOG_HOST`.

---

## Database migration updates

**File:** `aethercloud/supabase/migrations/20260417_users_billing.sql`

Append:

```sql
-- Allow 'free' tier (CHECK constraint correction) ------------------
alter table public.users drop constraint if exists users_tier_check;
alter table public.users add constraint users_tier_check
  check (tier in ('free','solo','pro','team'));
alter table public.users alter column tier set default 'free';

-- Signup attempts (rate limit table) --------------------------------
create table if not exists public.signup_attempts (
  id uuid primary key default gen_random_uuid(),
  ip text not null,
  created_at timestamptz not null default now()
);
create index if not exists signup_attempts_ip_created_idx
  on public.signup_attempts(ip, created_at desc);

alter table public.signup_attempts enable row level security;
-- Service role only; no user-facing policies.
```

Rationale for `ip` as `text` rather than `inet`: simplest cross-runtime compat; `inet` parsing is stricter and we may receive IPv6 in bracket-notation from forwarded headers.

**Alternative considered:** since this is one migration file and it hasn't shipped to prod yet, we could edit it in place. But treating it as append-only (drop + re-add the constraint, add the new table below) is safer if the migration has been applied to any env already.

---

## Environment variables

### Vercel (Production + Preview + Development)

| Name | Scope | Value | Purpose |
|------|-------|-------|---------|
| `STRIPE_SECRET_KEY` | Server | `sk_live_...` | `/api/checkout` creates Checkout Sessions |
| `STRIPE_PRICE_SOLO` | Server | `price_1TNKCm3TqWOqdd87AngxY9ks` | Solo checkout |
| `STRIPE_PRICE_PRO` | Server | `price_1TNKCm3TqWOqdd87vSXEHnVW` | Pro checkout |
| `STRIPE_PRICE_TEAM` | Server | `price_1TNKCm3TqWOqdd87FJIdQFI1` | Team checkout |
| `NEXT_PUBLIC_APP_URL` | Client | `https://aether-cloud-xxxxx.vercel.app` → later `https://aethersystems.net` | success/cancel redirect |
| `NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL` | Client | `https://<PROJECT_REF>.supabase.co/functions/v1/free-signup` | Free button POST target |
| `NEXT_PUBLIC_POSTHOG_KEY` | Client | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` | Browser PostHog init |
| `NEXT_PUBLIC_POSTHOG_HOST` | Client | `https://us.i.posthog.com` | Browser PostHog host |
| `POSTHOG_KEY` | Server | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` | `/api/checkout` server events (if any added later) |
| `POSTHOG_HOST` | Server | `https://us.i.posthog.com` | Server PostHog host |

Note the PostHog key is the same value on client and server — PostHog uses the project API key for both write paths. `NEXT_PUBLIC_` prefix is only about which runtime reads it.

### Supabase (new via `supabase secrets set`)

Appended to the existing set:

| Name | Value |
|------|-------|
| `POSTHOG_KEY` | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` |
| `POSTHOG_HOST` | `https://us.i.posthog.com` |
| `ALLOWED_ORIGIN_VERCEL` | `https://aether-cloud-xxxxx.vercel.app` (set after first Vercel deploy) |
| `ALLOW_LOCALHOST` | `true` (dev only; omit or set `false` in prod) |

---

## Corrections to existing `aethercloud/` files

1. **`supabase/migrations/20260417_users_billing.sql`** — append tier CHECK correction + `signup_attempts` table (see Migration section above).

2. **`supabase/functions/stripe-webhook/index.ts`** —
   - Extract `generateLicenseKey` + `sendWelcomeEmail` into `_shared/license.ts`; import from `../_shared/license.ts`.
   - Update `PRICE_TO_TIER` union type: `'solo' | 'pro' | 'team'`.
   - Add PostHog fetch calls per event type (see stripe-webhook section above).
   - Add `POSTHOG_KEY` / `POSTHOG_HOST` env reads.

3. **`VERCEL_ENV_VARS.md`** —
   - Rename `NEXT_PUBLIC_PRICE_*` → `STRIPE_PRICE_*` (drop `NEXT_PUBLIC_`, reorder Solo/Pro/Team).
   - Remove `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.
   - Replace `APP_URL` with `NEXT_PUBLIC_APP_URL`.
   - Add `NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL`, 4 PostHog vars.
   - Replace pricing text with 4-tier table + real price IDs.

4. **`DEPLOY_WALKTHROUGH.md`** — change "3 tiers" mentions to "4 tiers"; Step 2 example updated to use real Solo/Pro/Team price IDs and add the new Supabase secrets (`POSTHOG_KEY`, `POSTHOG_HOST`, `ALLOWED_ORIGIN_VERCEL`).

5. **`deploy.sh`** —
   - Replace `PRICE_*` REPLACE_ME placeholders with real IDs pre-filled.
   - Add new secrets to the `supabase secrets set` call (POSTHOG_KEY, POSTHOG_HOST, ALLOWED_ORIGIN_VERCEL).
   - Reorder to Solo → Pro → Team.
   - Add `supabase functions deploy free-signup --no-verify-jwt` after `stripe-webhook`.

6. **`STRIPE_WEBHOOK_SETUP.md`** — no change. Webhook endpoint registration step remains required and separate; without it, paid checkouts succeed but no licenses issued.

---

## Stripe dashboard step — still required

Even with the site live, one manual Stripe step remains: **register the webhook endpoint** per `aethercloud/STRIPE_WEBHOOK_SETUP.md`. Without it, payments succeed but the webhook never fires, so no license is generated. This is independent of anything Vercel-related.

Products/prices are **not** created — they already exist.

---

## Vercel deploy

### Phase A — Import

1. [vercel.com/new](https://vercel.com/new) → pick the `AETHER-CLOUD` repo.
2. **Configure project:**
   - **Root Directory** → Edit → select `site`. Critical.
   - **Framework Preset** auto-detects Next.js. Leave.
3. **Environment Variables** — paste all 10 Vercel vars. `NEXT_PUBLIC_APP_URL` can be blank on first deploy.
4. Deploy.

### Phase B — Close the loop

1. Copy the `*.vercel.app` URL Vercel assigned. Set `NEXT_PUBLIC_APP_URL` = that URL → redeploy Vercel.
2. Update Supabase secrets:
   ```bash
   supabase secrets set \
     APP_URL=https://aether-cloud-xxxxx.vercel.app \
     ALLOWED_ORIGIN_VERCEL=https://aether-cloud-xxxxx.vercel.app
   ```
   `APP_URL` is for the welcome email; `ALLOWED_ORIGIN_VERCEL` is for the CORS allowlist in `free-signup`.

### Phase C — Custom domain (later)

Vercel → Settings → Domains → add `aethersystems.net`. Update both `NEXT_PUBLIC_APP_URL` (Vercel) and `APP_URL` (Supabase) to the new domain. `ALLOWED_ORIGIN_VERCEL` can stay at the Vercel URL or be updated — both are safe to allowlist.

---

## Verification

1. **Build.** `cd site && npm install && npm run build` exits 0.
2. **Pricing page.** Preview URL loads; four cards at $0 / $19 / $49 / $89; PostHog `$pageview` event visible in Live Events.
3. **Paid flow.** Click Subscribe on Solo incognito → `track.checkoutStarted` event in PostHog → Stripe Checkout → pay $19 → `/success` → within 5s: `public.users` row (tier='solo', valid license), Resend email received, PostHog `checkout_completed` event with `tier: solo, mrr: 19`, Stripe webhook dashboard shows 200. Refund.
4. **Free flow.** Enter email in Free card → submit → `track.signupStarted('pricing_page')` event, then `track.signupCompleted({method:'email'})` event → `/success` → within 5s: `public.users` row (tier='free', license), Resend email, PostHog server-side `signup_completed` event (same distinctId as the client events — the email address).
5. **Rate limit.** Submit the Free form 4× rapidly from the same IP. 4th returns 429. Verify `signup_attempts` rows exist.
6. **Disposable email.** Submit `x@mailinator.com` → 400. No `users` row created. No `signup_attempts` row either (check rejection happens before insert).
7. **CORS.** `curl -X OPTIONS -H "Origin: https://evil.com" <free-signup-url>` → 403. Same with the real Vercel origin → 200 with allow headers.
8. **No events lost.** Monitor PostHog Live Events tab for ~1min during steps 3–4 — no dropped events, no spikes in capture errors.

---

## Future considerations

- **Desktop app analytics proxy.** `track.licenseActivated` is defined in `track.ts` but fires from the desktop app via a Vercel `/api/events` proxy that hasn't been built. Add it when the desktop app starts reporting activations.
- **Billing portal link.** Stripe Billing Portal self-serve cancel page — enable in dashboard + expose a link on future account page.
- **Fraud sophistication.** If disposable-email list becomes a cat-and-mouse game, swap for Turnstile or hCaptcha on the Free form.
- **Token metering enforcement** for Free tier — responsibility of the desktop app + `api_server.py`, not this site.
