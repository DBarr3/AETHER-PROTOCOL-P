# Vercel environment variables

Paste these into your Vercel project (**Settings → Environment Variables**) so the Subscribe buttons and Checkout Session creation work. Scope every row to **Production + Preview + Development** unless otherwise noted.

| Name | Value | Where to get it |
|---|---|---|
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | `pk_live_...` | Stripe dashboard → **Developers → API keys** → *Publishable key* |
| `STRIPE_SECRET_KEY` | `sk_live_...` | Stripe dashboard → **Developers → API keys** → *Secret key*. Used by your serverless function that creates Checkout Sessions. |
| `NEXT_PUBLIC_PRICE_SOLO` | `price_...` | Stripe dashboard → **Products** → Solo product → copy price ID |
| `NEXT_PUBLIC_PRICE_TEAM` | `price_...` | Stripe dashboard → **Products** → Team product → copy price ID |
| `NEXT_PUBLIC_PRICE_PRO` | `price_...` | Stripe dashboard → **Products** → Pro product → copy price ID |
| `APP_URL` | `https://aethersystems.net` | Your production domain — used for Checkout success/cancel URLs |

## Checklist

- [ ] All six rows added
- [ ] Every row scoped to Production, Preview, and Development
- [ ] Stripe account toggle was set to **Live** when copying keys (not Test)
- [ ] Project redeployed after saving (env changes don't take effect until redeploy)

## Via CLI

```bash
vercel env add NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY production
vercel env add STRIPE_SECRET_KEY production
vercel env add NEXT_PUBLIC_PRICE_SOLO production
vercel env add NEXT_PUBLIC_PRICE_TEAM production
vercel env add NEXT_PUBLIC_PRICE_PRO production
vercel env add APP_URL production
# repeat for `preview` and `development` environments, or use `--environment all`
```

## Notes

- `NEXT_PUBLIC_*` vars are bundled into the client JavaScript — safe to expose (publishable keys and price IDs are public by design).
- `STRIPE_SECRET_KEY` is **not** `NEXT_PUBLIC_*` — it must only be read by server-side code (API routes / serverless functions). Never prefix it with `NEXT_PUBLIC_`.
- `APP_URL` is used by your Checkout Session creator as `success_url` and `cancel_url`. Keep it in sync with the `APP_URL` secret on Supabase (they should match).
