# AetherCloud billing — deploy walkthrough (plain English)

You're wiring together four tiers so a customer hitting "Subscribe" on your site ends up with a license key in their inbox:

```
[Vercel site / checkout button]
        │  creates Stripe Checkout Session
        ▼
[Stripe]  ← customer pays here
        │  sends webhook event to...
        ▼
[Supabase Edge Function: stripe-webhook]
        │  writes row, generates license, sends email
        ▼
[Supabase users table]      [Resend → customer inbox]
```

Each deploy step below sets up one link in that chain.

---

## Step 1 — Run the SQL migration

**What this does:** Creates the `public.users` table in Supabase where every paying customer gets a row (email, tier, license key, subscription status).

**Why it's needed:** The webhook has nowhere to write customer data until this table exists.

**How:**

1. Open your Supabase project → **SQL Editor** → **New query**
2. Paste the contents of `supabase/migrations/20260417_users_billing.sql`
3. Click **Run**

You should see "Success. No rows returned." Verify by going to **Table Editor** → you'll see `users` in the list.

Or via CLI (if you've run `supabase link` already):
```bash
supabase db push
```

---

## Step 2 — Set secrets on Supabase

**What this does:** Gives the edge function runtime access to your Stripe key, Resend key, etc. Secrets are encrypted and only readable by your function at runtime.

**Why it's needed:** The webhook code reads these via `Deno.env.get(...)`. Without them set, the function will crash on the first request.

**How:** Run this locally (one line, fill in your real values):

```bash
supabase secrets set \
  STRIPE_SECRET_KEY=sk_live_REPLACE_ME \
  RESEND_API_KEY=re_REPLACE_ME \
  SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=sb_secret_REPLACE_ME \
  APP_URL=https://aethersystems.net \
  FROM_EMAIL=no-reply@aethersystems.net \
  PRICE_SOLO=price_1TNKCm3TqWOqdd87AngxY9ks \
  PRICE_PRO=price_1TNKCm3TqWOqdd87vSXEHnVW \
  PRICE_TEAM=price_1TNKCm3TqWOqdd87FJIdQFI1 \
  POSTHOG_KEY=phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR \
  POSTHOG_HOST=https://us.i.posthog.com \
  ALLOWED_ORIGIN_VERCEL=https://your-vercel-url.vercel.app
```

**Where to grab each one:**
- `STRIPE_SECRET_KEY` → https://dashboard.stripe.com/apikeys → **Secret key** (starts `sk_live_`). Make sure the account toggle shows **Aether Systems LLC**.
- `RESEND_API_KEY` → https://resend.com/api-keys (if you don't have Resend yet, sign up free, verify `aethersystems.net` domain via DNS, create an API key).
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` → Supabase project → **Settings → API**.
- `PRICE_SOLO` / `PRICE_TEAM` / `PRICE_PRO` → Stripe dashboard → **Products** → each product's price → copy the `price_...` ID.

**Note:** We'll set `STRIPE_WEBHOOK_SECRET` in step 4 — you don't have it yet because the webhook endpoint doesn't exist.

(Or just run `./deploy.sh` after filling in the values at the top — it does steps 1–3 in one shot.)

---

## Step 3 — Deploy the edge function

**What this does:** Uploads `supabase/functions/stripe-webhook/index.ts` to Supabase's edge runtime. After this, the URL `https://YOUR-REF.supabase.co/functions/v1/stripe-webhook` becomes live and Stripe can POST to it.

**Why the `--no-verify-jwt` flag:** Supabase edge functions, by default, reject any request without a logged-in Supabase user's JWT. Stripe is a random external service — it has no idea what a Supabase JWT is. This flag turns that check off. Security isn't lost: the function verifies Stripe's own cryptographic signature (`stripe-signature` header) instead, which is stronger.

**How:**
```bash
cd /path/to/aethercloud
supabase functions deploy stripe-webhook --no-verify-jwt
supabase functions deploy free-signup --no-verify-jwt
```

Output ends with the function URL. Copy it — you need it in the next step.

---

## Step 4 — Register the webhook in Stripe (60 seconds, dashboard)

**What this does:** Tells Stripe "when one of these 4 things happens on my account, POST the event to this URL."

**Why it's manual:** The Stripe connector we've been using doesn't expose the `/v1/webhook_endpoints` API endpoint. So this one step we do by hand — takes under a minute.

**How:**

1. Open https://dashboard.stripe.com/webhooks (make sure top-right shows **Live** mode, not Test)
2. Click **+ Add endpoint**
3. **Endpoint URL:** paste the URL from step 3
4. **Description:** `AetherCloud billing webhook`
5. **Events to send:** click "Select events" and pick exactly these four:
   - `checkout.session.completed` (fires when someone finishes paying)
   - `customer.subscription.updated` (fires on plan changes, renewals)
   - `customer.subscription.deleted` (fires on cancellation)
   - `invoice.payment_failed` (fires on failed charges)
6. Click **Add endpoint**
7. On the next page, click **Reveal** next to "Signing secret". It starts with `whsec_...`. Copy it.

---

## Step 5 — Give Supabase the signing secret

**What this does:** Hands the `whsec_...` value to the edge function so it can verify every request it receives actually came from Stripe.

**Why it's needed:** Without this, your webhook has no way to tell a real Stripe event from an attacker spoofing events (e.g. trying to fake a `checkout.session.completed` to get a free license). The function will refuse to run without this secret.

**How:**
```bash
supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_REPLACE_ME
```

---

## Step 6 — Send a test event

**What this does:** Makes Stripe fire a fake event at your endpoint so you can confirm it's reachable and the signature verification passes.

**How:**

1. Back on the webhook detail page in Stripe, click **Send test webhook**
2. Pick `checkout.session.completed`
3. Click **Send test**
4. In another terminal, tail the logs:
   ```bash
   supabase functions logs stripe-webhook --tail
   ```

You want to see a **200** response. A fake test payload may not produce a real email (because the customer in the payload is fake) — that's fine. You're validating that signature verification and routing work.

If you see `signature verification failed`: the `STRIPE_WEBHOOK_SECRET` is wrong. Re-copy it from Stripe and re-run step 5.

---

## Step 7 — Paste env vars into Vercel

**What this does:** Lets your site's checkout button know which price IDs to charge and which Stripe publishable key to use.

**How:** Vercel project → **Settings → Environment Variables**. Add each row from `VERCEL_ENV_VARS.md`. Scope all to **Production + Preview + Development**. Redeploy after saving.

Or CLI (from your project root):
```bash
vercel env add NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY production
# paste value when prompted, repeat for each
```

---

## Step 8 — Real end-to-end test

This is the one that actually matters. Drive the whole flow once as if you were a customer:

1. Open your site in an incognito window
2. Click **Subscribe** on the Solo tier
3. Complete Checkout with a real card (charge yourself $19 — you can refund from the Stripe dashboard after)

**Expected outcome within ~5 seconds:**
- A row appears in `public.users` with your email and a license like `AETH-CLD-XXXX-XXXX-XXXX`
- The welcome email lands in your inbox from `no-reply@aethersystems.net`
- The webhook shows a **200** response in Stripe's dashboard (webhook detail → **Recent deliveries**)

If any of those three things doesn't happen, `supabase functions logs stripe-webhook --tail` will show you exactly what failed.

Then refund yourself in Stripe → dashboard → **Payments** → your charge → **Refund**.

---

## Mental model recap

| You do this | Because |
|---|---|
| Run SQL migration | Create the table the webhook writes into |
| Set Supabase secrets | Give the function its credentials |
| Deploy the function | Make the URL live on the internet |
| Register webhook in Stripe | Tell Stripe where to send events |
| Set webhook signing secret | Let the function verify events are real |
| Send test event | Confirm plumbing works before real money moves |
| Set Vercel env vars | Let your site's Subscribe buttons work |
| Real checkout test | Prove the whole chain end-to-end |

Each step unlocks the next. If you hit a snag on any one of them, stop there and fix it — don't keep going, or you'll confuse which step broke.
