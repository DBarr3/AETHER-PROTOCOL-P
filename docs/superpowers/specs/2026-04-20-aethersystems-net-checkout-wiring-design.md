# aethersystems.net marketing + checkout wiring — Design

**Status:** Approved by user 2026-04-20 (sections 1-5, M1, domain swap, edge function backend)
**Worktree:** `.claude/worktrees/aethersystems-web` (branch `claude/aethersystems-web`)

## End-to-end flow

```
[aethersystems.net/aether-cloud]
       │  user clicks Free "Download free"
       ├──▶ /download  (direct installer download, no signup)
       │
       │  user clicks Solo/Professional/Team
       ▼
[POST https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1/create-checkout-session]
       │  { plan: "aether_cloud_solo|pro|team", success_url, cancel_url, utm }
       │  → { ok, url, id }
       ▼
[Stripe hosted checkout]
       │  user pays
       ├──▶ Stripe fires checkout.session.completed webhook
       │    → supabase/functions/stripe-webhook
       │    → generates AETH-CLD-XXXX-XXXX-XXXX license key
       │    → upserts public.users { email, tier, license_key, stripe_customer_id }
       │    → sends welcome email via Resend (no-reply@aethersystems.net)
       │    → fires PostHog checkout_completed event
       │
       │  Stripe redirects browser back
       ▼
[aethersystems.net/welcome?session=cs_test_...]
       │  "Check your email for license key AETH-CLD-*"
       │  user clicks Download AetherCloud Installer
       ▼
[https://api.aethersystems.net/downloads/AetherCloud-Setup.exe]  (already live on vps1)
       │  user runs Tauri wizard → NSIS → AetherCloud-L.exe installs
       ▼
[AetherCloud-L login screen]
       │  user pastes license key from email
       ▼
[POST {SUPABASE}/functions/v1/activate-license]
       │  → validates key, records install in public.installs
       ▼
[App unlocked, user signed in]
```

## Architecture decisions

### M1 — Monorepo layout
`aethersecurity/website/` (Vite React SPA) was copied into
`AETHER-CLOUD/web/` alongside the existing `/site/` (Next.js) and
`/desktop-installer/` (Tauri wizard). Single repo, one CI, shared commit
history for the consumer-facing chain.

Cruft removed on import: raw PNG sources (kept `.webp` in `public/`),
`aethersecurity-website.zip` that was sitting in source, `.env` (had a
`KIE_API_KEY` — user to rotate if exposed in aethersecurity repo history),
`.claude/` dev tooling dir.

### Backend — Supabase edge functions (pre-existing, verified via MCP)
User had the entire billing backend deployed before this work:

| Function | Purpose | Version |
|---|---|---|
| `create-checkout-session` | Website → Stripe checkout session | **bumped to v4 today** — added `aether_cloud_solo` to PLAN_TO_ENV |
| `stripe-webhook` | Stripe → `public.users` + Resend email + PostHog | v4 (unchanged) |
| `free-signup` | Email-only free tier, rate-limited, disposable block | v2 (unchanged) |
| `activate-license` | Desktop app sign-in (JWT-gated) | v3 (unchanged) |
| `ingest-install-event` | Installer funnel telemetry → `public.install_events` (11 rows seen) | v3 (unchanged) |
| `contact-submit` | Contact form → `public.contact_submissions` | v4 (unchanged) |

The Next.js `/site/api/checkout` path I started wiring earlier is **legacy/duplicate** — the React SPA now calls the edge function directly. `/site/` still builds and can deploy, but is no longer the critical path.

### Domain swap
All 9 files referencing `aethersecurity.io` updated to `aethersystems.net`:
- `web/index.html` × 4 (canonical, og:url, og:image, twitter:image, structured data)
- `web/src/pages/contact/index.jsx` × 3 (email addresses)
- `web/src/pages/home/index.jsx` × 1 (email)
- `web/src/pages/documentation/components/Content27.jsx` × 3 (aspirational subdomains: `get.`, `api.`, `charts.`)

### Tier → plan mapping
Lives in `web/src/lib/config.js`:

| UI tier name | Plan slug | Stripe env var |
|---|---|---|
| Free         | `free` (no checkout) | n/a |
| Solo         | `aether_cloud_solo`  | **`STRIPE_PRICE_AETHER_CLOUD_SOLO`** — *needs to be set on Supabase project before Solo button works* |
| Professional | `aether_cloud_pro`   | `STRIPE_PRICE_AETHER_CLOUD_PRO` |
| Team         | `aether_cloud_team`  | `STRIPE_PRICE_AETHER_CLOUD_TEAM` |

Note: `stripe-webhook` uses a separate set of env vars (`PRICE_SOLO`,
`PRICE_PRO`, `PRICE_TEAM`) to map prices back to tiers when the
checkout completes. Operator must ensure the two variable sets point at
the same Stripe price IDs per tier.

## Files created / modified

**New files:**
- `web/src/lib/config.js`
- `web/src/lib/checkoutApi.js`
- `web/src/pages/welcome/index.jsx`
- `web/src/pages/download/index.jsx`
- `site/app/api/session/route.ts` *(legacy/duplicate now; kept for reference)*

**Modified:**
- `web/src/App.jsx` — add `/welcome` and `/download` routes
- `web/src/pages/aether-cloud/index.jsx` — replaced inline CTA placeholders
  with `PricingCard` component that wires to `startCheckout(plan)`
- `site/app/api/checkout/route.ts` — added CORS for aethersystems.net origin,
  tier hint in success_url *(duplicate infra — not the critical path)*

**Remote (Supabase):**
- `create-checkout-session` edge function → deployed v4 with
  `aether_cloud_solo` added to PLAN_TO_ENV

## What ships today

- [x] `/web/` compiles and serves the marketing site
- [x] `/aether-cloud` page's paid tier buttons create real Stripe sessions
- [x] `/welcome` page receives Stripe redirect, shows download CTA
- [x] `/download` page serves the free tier direct-download flow
- [x] All domain refs point at `aethersystems.net`

## What's deferred to later this week

- Deploy `/web/` as a Vercel project attached to `aethersystems.net` DNS
  (current prod site `DBarr3/aethersystems.net` gets replaced)
- Set `STRIPE_PRICE_AETHER_CLOUD_SOLO` secret on the Supabase project if
  Solo tier is being offered
- Verify `stripe-webhook`'s `PRICE_SOLO / PRICE_PRO / PRICE_TEAM` env
  vars all point at the same Stripe prices as `STRIPE_PRICE_AETHER_CLOUD_*`
- Normalize the env var naming (the two sets should be unified in a
  future cleanup pass — too much churn to change webhook today)
- Wire a `Download` CTA on `/home` (currently the `aether-cloud` product
  page is the only entry point)
- Azure Trusted Signing — still pending from last week's wizard work

## Testing today

- Local `vite build` passes
- Stripe will be tested in TEST mode once Vercel deploy is set up
- `/free-signup` path testable via `curl -X POST` against the edge
  function with an email

## Risk / rollback

- `create-checkout-session` v3 → v4: the ONLY diff is adding one plan
  key. If v4 misbehaves, revert is a single MCP call to redeploy v3
  content (v3 source captured in the function's history).
- `/web/` is a new directory — committing it doesn't affect any
  existing deploy. DNS stays on the current `DBarr3/aethersystems.net`
  static site until operator updates it.
- The Next.js `/site/` changes are CORS additions + new session
  endpoint — additive, non-breaking for the existing deploy (if any).

## Follow-ups flagged for operator

1. **`.env` rotation**: the imported aethersecurity repo had a
   `KIE_API_KEY` in plaintext `.env`. If that `.env` was ever committed
   to the aethersecurity git history, rotate the key now.
2. **Stripe price config**: confirm all four prices (solo/pro/team/ent)
   exist in Stripe AND their IDs are set as both `PRICE_*` (for webhook)
   and `STRIPE_PRICE_AETHER_CLOUD_*` (for checkout creation) secrets.
3. **Legacy `/site/api/checkout`**: now unused. Can be deleted in a
   followup PR, or kept as a backup redirect path.
