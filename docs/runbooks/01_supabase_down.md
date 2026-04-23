# Runbook: Supabase Down

## Symptom
5xx responses on `/api/internal/router/pick` with "audit writer" errors in Vercel logs. Routing decisions still work (noop writer fallback) but audit trail gaps appear in `routing_decisions` table.

## Who to Ping
- Owner: lilbenxo@gmail.com

## Diagnosis

### 1. Check Vercel logs for audit writer errors
```sh
npx vercel logs --app aethersystems --since 30m | grep -i "audit"
```

### 2. Check Supabase project status
```sh
# Open Supabase dashboard status page
open https://status.supabase.com
```

### 3. Verify Supabase connectivity from Vercel
```sh
# Test Supabase endpoint directly
curl -s -o /dev/null -w "%{http_code}" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  "$SUPABASE_URL/rest/v1/routing_decisions?limit=1"
```
Expected: `200`. If `5xx` or timeout, Supabase is unavailable.

### 4. Check audit writer error counter via OTel (if wired)
Look for `audit_writer_failed_total` metric spike in Vercel Observability.

## Mitigation (Stop the Bleeding)
The router uses a noop writer fallback by default — **routing continues normally, only audit logging is lost**. No immediate action required to keep service running.

To confirm noop is active:
```sh
npx vercel env ls --app aethersystems | grep SUPABASE
```
If `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` is missing/blank, noop is already active.

## Recovery

### 1. Wait for Supabase to recover
Monitor https://status.supabase.com. Most outages resolve within 15–30 minutes.

### 2. Once Supabase is back, verify env vars are intact on Vercel
```sh
npx vercel env ls --app aethersystems
```
Confirm `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are present.

### 3. Redeploy to restore audit writer connection
```sh
npx vercel --prod --force
```

### 4. Verify audit writes resuming
```sh
# Check recent rows in routing_decisions
curl -s \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  "$SUPABASE_URL/rest/v1/routing_decisions?order=created_at.desc&limit=5" | jq .
```

## Post-Incident
- Log gap duration and estimated rows lost in a GitHub issue
- Consider: add a dead-letter queue or retry buffer for audit writes during outages
