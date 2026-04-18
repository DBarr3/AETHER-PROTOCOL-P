# Stripe webhook setup (60 seconds, dashboard)

After `deploy.sh` finishes, it prints your function URL. Use it here.

## Steps

1. Open **https://dashboard.stripe.com/webhooks**. Top-right toggle must show **Live mode** (not Test).
2. Click **+ Add endpoint**.
3. **Endpoint URL:** paste the URL from the end of `deploy.sh` output. It looks like:
   ```
   https://YOUR-PROJECT-REF.supabase.co/functions/v1/stripe-webhook
   ```
4. **Description:** `AetherCloud billing webhook`
5. **Events to send** → click **Select events** → pick exactly these four:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
6. Click **Add endpoint**.
7. On the endpoint detail page, click **Reveal** next to **Signing secret**. It starts with `whsec_`. Copy it.
8. In your terminal:
   ```bash
   supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_PASTED_VALUE_HERE
   ```

## Verify with a test event

1. Back on the webhook detail page, click **Send test webhook**.
2. Pick `checkout.session.completed` → **Send test**.
3. In a terminal, tail logs:
   ```bash
   supabase functions logs stripe-webhook --tail
   ```
4. Expect a **200** response. (A real welcome email won't fire from a fake test payload — that's fine. You're confirming signature verification and routing work.)

## If it fails

- **`signature verification failed`** — wrong `STRIPE_WEBHOOK_SECRET`. Re-copy from Stripe and re-run step 8.
- **`401 Unauthorized`** — you deployed without `--no-verify-jwt`. Re-run `supabase functions deploy stripe-webhook --no-verify-jwt`.
- **`500`** — one of the other secrets is missing or wrong. Check `supabase secrets list` and logs.
