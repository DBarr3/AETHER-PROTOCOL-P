# Runbook: License Revocation

## When to Run
- Customer chargeback received
- Refund issued and service should be terminated
- Abuse detected (license sharing, ToS violation)

## Who to Ping
- Owner: lilbenxo@gmail.com

## Steps

### 1. Identify the license in Supabase
```sh
curl -s \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  "$SUPABASE_URL/rest/v1/licenses?email=eq.<customer@email.com>" | jq .
```
Note the `id`, `license_key`, and `stripe_subscription_id`.

### 2. Cancel the Stripe subscription
Go to Stripe Dashboard → Customers → find customer → Subscriptions → Cancel.

Or via Stripe CLI:
```sh
stripe subscriptions cancel <stripe_subscription_id>
```

### 3. Verify license status flipped in Supabase
The `stripe-webhook` edge function listens for `customer.subscription.deleted` and should auto-update `licenses.status` to `suspended`.
```sh
curl -s \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  "$SUPABASE_URL/rest/v1/licenses?id=eq.<license_id>" | jq '.[0].status'
```
Expected: `"suspended"`. Allow up to 60 seconds for webhook delivery.

### 4. If webhook doesn't update status automatically, update manually
```sh
curl -s -X PATCH \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  "$SUPABASE_URL/rest/v1/licenses?id=eq.<license_id>" \
  -d '{"status": "suspended"}'
```

### 5. Verify app enforces on next activate-license call
On next app launch, the desktop app calls activate-license. With status `suspended`, it should receive an error and block access.

Test by checking the activate-license endpoint behavior with the revoked key.

## Post-Incident
- Log the revocation reason in a GitHub issue or private note
- If chargeback: respond to chargeback with Stripe evidence tools
- If abuse: document abuse pattern for future detection
