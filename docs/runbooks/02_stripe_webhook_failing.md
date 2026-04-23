# Runbook: Stripe Webhook Failing

## Symptom
Licenses not being created after Stripe checkout completion. Users complete payment but no license key appears. PostHog `checkout_completed` event not firing.

## Who to Ping
- Owner: lilbenxo@gmail.com

## Diagnosis

### 1. Check Stripe Dashboard → Webhooks
Go to https://dashboard.stripe.com/webhooks, select the endpoint, look for failed deliveries (red X rows).

### 2. Check Supabase Edge Function logs
```sh
npx supabase functions logs stripe-webhook --project-ref <your-project-ref>
```

### 3. Check Vercel deployment for the webhook endpoint
```sh
npx vercel logs --app aethersystems --since 1h | grep "stripe-webhook\|checkout"
```

### 4. Verify webhook signature secret is current
```sh
npx vercel env ls --app aethersystems | grep STRIPE_WEBHOOK_SECRET
```
Compare the value against Stripe Dashboard → Webhooks → endpoint → Signing secret.

## Common Causes

| Cause | Indicator | Fix |
|---|---|---|
| Signing secret rotated | 400 `Webhook signature verification failed` in logs | Update `STRIPE_WEBHOOK_SECRET` on Vercel |
| Endpoint returning 5xx | 5xx in Stripe delivery log | Check Supabase function for errors (see diagnosis) |
| Rate limit hit | 429 in Stripe delivery log | Reduce retry frequency or scale Supabase |
| Supabase down | Timeout in Stripe delivery log | See `01_supabase_down.md` runbook |

## Mitigation (Stop the Bleeding)
Stripe retries failed webhooks automatically for up to 72 hours. No immediate customer-facing action needed if issue resolves quickly.

For urgent cases (customer waiting for license):
1. Manually create license in Supabase dashboard → `licenses` table
2. Email license key to customer directly

## Recovery

### 1. Fix the root cause (see Common Causes table above)

### 2. If signing secret was rotated, update Vercel env and redeploy
```sh
npx vercel env add STRIPE_WEBHOOK_SECRET production
# Enter new secret when prompted
npx vercel --prod --force
```

### 3. Replay failed webhooks from Stripe Dashboard
Go to Stripe Dashboard → Webhooks → select endpoint → click "Resend" on each failed event. Or use Stripe CLI:
```sh
stripe events resend <event_id>
```

### 4. Verify license was created
```sh
curl -s \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  "$SUPABASE_URL/rest/v1/licenses?order=created_at.desc&limit=5" | jq .
```

## Post-Incident
- Ticket: document root cause and which events were replayed
- Consider: add PostHog `stripe_webhook_failed` server-side event on catch blocks in stripe-webhook edge function
