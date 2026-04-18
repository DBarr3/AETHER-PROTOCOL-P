# Vercel environment variables

Paste these into your Vercel project (**Settings → Environment Variables**) so the Subscribe buttons and Checkout Session creation work. Scope every row to **Production + Preview + Development**.

## Required

| Name | Scope | Value |
|---|---|---|
| `STRIPE_SECRET_KEY` | Server | `sk_live_...` |
| `STRIPE_PRICE_SOLO` | Server | `price_1TNKCm3TqWOqdd87AngxY9ks` ($19/mo) |
| `STRIPE_PRICE_PRO` | Server | `price_1TNKCm3TqWOqdd87vSXEHnVW` ($49/mo) |
| `STRIPE_PRICE_TEAM` | Server | `price_1TNKCm3TqWOqdd87FJIdQFI1` ($89/mo) |
| `NEXT_PUBLIC_APP_URL` | Client | `https://<your-vercel-url>.vercel.app` → later `https://aethersystems.net` |
| `NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL` | Client | `https://<PROJECT_REF>.supabase.co/functions/v1/free-signup` |
| `NEXT_PUBLIC_POSTHOG_KEY` | Client | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` |
| `NEXT_PUBLIC_POSTHOG_HOST` | Client | `https://us.i.posthog.com` |
| `POSTHOG_KEY` | Server | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` |
| `POSTHOG_HOST` | Server | `https://us.i.posthog.com` |

## Where to get each value

- **`STRIPE_SECRET_KEY`** → Stripe dashboard → **Developers → API keys** → *Secret key*. Live mode only.
- **`STRIPE_PRICE_*`** → Already listed above. Don't re-create — they exist in Live mode.
- **`NEXT_PUBLIC_APP_URL`** → Blank on first deploy; Vercel gives you a `.vercel.app` URL. Paste it back as `NEXT_PUBLIC_APP_URL` and redeploy. Later swap for `https://aethersystems.net` after adding the custom domain.
- **`NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL`** → After running `aethercloud/deploy.sh`, the script prints this URL.
- **`POSTHOG_*`** → Already listed above. Project 386803 (US cloud).

## Security notes

- `NEXT_PUBLIC_*` variables are bundled into client JavaScript — safe to expose. The PostHog project key, publishable Stripe price IDs, and public Supabase function URL are all designed for browser exposure.
- `STRIPE_SECRET_KEY` must stay server-only. Never prefix it with `NEXT_PUBLIC_`.
- `POSTHOG_KEY` is the same value on client and server; PostHog uses the project API key for both. The `NEXT_PUBLIC_` distinction only controls which runtime reads it.

## Checklist

- [ ] All 10 rows added
- [ ] Every row scoped to Production, Preview, and Development
- [ ] Stripe account toggle was set to **Live** when copying the secret key
- [ ] Project redeployed after saving (env changes don't take effect until redeploy)
- [ ] After first deploy, ran `supabase secrets set ALLOWED_ORIGIN_VERCEL=https://<your-vercel-url>.vercel.app` so CORS on `free-signup` allows the site
