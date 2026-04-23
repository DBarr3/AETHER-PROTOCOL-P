# Cloudflare Pages deploy — aethersystems.net

This folder builds to a plain static SPA. `dist/` is a drop-in artifact
for Cloudflare Pages. Two deploy options below; pick whichever matches
how you already manage Cloudflare.

## Prerequisites — same for both paths

- Cloudflare account with the `aethersystems.net` zone already attached
  (DNS is already on Cloudflare per the operator).
- Node 18+ locally if you're going to run the build yourself.

## Option A — one-time drag-drop (fastest, no CLI)

1. **Build locally:**
   ```bash
   cd web
   npm install
   npm run build
   ```
2. In the **Cloudflare dashboard** go to **Workers & Pages → Create
   application → Pages → Upload assets**. Project name:
   `aethersystems-net`.
3. Upload **the contents of `web/dist/`** — not the `dist/` folder
   itself. (Drag every file + `assets/` + `_redirects` + `_headers`.)
   A pre-made zip is at `web/aethersystems-net-cloudflare-pages.zip`
   (see build script below) if you prefer to drop one file.
4. Once deployed, under **Custom domains** attach:
   - `aethersystems.net` (apex)
   - `www.aethersystems.net`
5. Cloudflare will provision a cert within a couple of minutes. Once
   active, hitting `https://aethersystems.net/aether-cloud` and clicking
   **Start solo** will deep-link to `https://app.aethersystems.net/#tier-solo`
   (the existing Vercel Next.js app) and complete the Stripe loop.

## Option B — wrangler CLI (for repeat deploys / CI)

```bash
cd web
npm install
npm run build
npx wrangler pages deploy dist --project-name aethersystems-net
```

First run will prompt you to authenticate with Cloudflare. After that
the same command re-deploys — swap `--branch production` in for prod
promotions once you've set up a preview branch.

To wire this into a push-on-main workflow, add a GitHub Action that
runs the same three commands with `CLOUDFLARE_API_TOKEN` in the env.

## What's in the build

- `index.html` — entry, preloads CSS + JS chunks by content hash
- `assets/*` — hashed JS + CSS + webp bundles, safe to cache forever
  (`_headers` sets `Cache-Control: public, max-age=31536000, immutable`)
- `_redirects` — SPA fallback: every non-asset URL serves `index.html`
  so react-router handles client-side routing (no 404 on refresh)
- `_headers` — security headers + cache control:
  - CSP allows `self`, `app.aethersystems.net` (for checkout navigation),
    Supabase (for `free-signup` edge function), Google Fonts, CloudFront
    (legacy image host)
  - HSTS 2 years + preload, X-Frame DENY, no-sniff, strict referrer
  - HTML revalidates every request, assets cache forever

## Checkout flow after deploy

```
aethersystems.net/aether-cloud
   ├─ Free           → api.aethersystems.net/downloads/AetherCloud-Setup.exe
   ├─ Solo $19.99    → app.aethersystems.net/#tier-solo  (auto-scroll + focus Subscribe)
   ├─ Professional   → app.aethersystems.net/#tier-pro
   └─ Team           → app.aethersystems.net/#tier-team

[app.aethersystems.net]   (Vercel "aether-cloud" project, Next.js)
   └─ Subscribe → /api/checkout → Stripe session → hosted checkout
        └─ paid → stripe-webhook (Supabase)
             ├─ public.users upsert + license_key AETH-CLD-…
             ├─ Resend: welcome email from no-reply@aethersystems.net
             └─ PostHog: checkout_completed
        └─ redirect → app.aethersystems.net/success?session_id=…&tier=solo
```

## Env overrides (rare)

Everything lives in `src/lib/config.js` with production-safe defaults.
Override only if you need to point a preview build at a staging
checkout host:

| Vite var | Default | When to override |
|---|---|---|
| `VITE_CHECKOUT_URL` | `https://app.aethersystems.net` | Staging checkout deploy |
| `VITE_DOWNLOAD_URL` | `https://api.aethersystems.net/downloads/AetherCloud-Setup.exe` | Staging installer |
| `VITE_SUPABASE_FUNCTIONS_URL` | `https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1` | Separate Supabase project |

Set these in Cloudflare Pages → Project → Settings → Environment
Variables → **Production** before the next build.

## DNS sanity check after deploy

```bash
dig +short aethersystems.net
dig +short www.aethersystems.net
curl -I https://aethersystems.net/ | grep -i server
```

Cloudflare Pages hostnames typically show `Server: cloudflare` in the
response headers. If you still see a different origin, the custom
domain hasn't propagated yet — wait 2-3 minutes and retry.
