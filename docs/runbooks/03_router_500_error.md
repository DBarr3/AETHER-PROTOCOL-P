# Runbook: Router Pick 500 Error

## Symptom
`/api/internal/router/pick` returning 500 with empty body or `{"error":"internal"}`. Desktop app shows "routing unavailable" or falls back to default model. PostHog 5xx rate alert fires.

## Who to Ping
- Owner: lilbenxo@gmail.com

## Diagnosis

### 1. Check Vercel logs immediately
```sh
npx vercel logs --app aethersystems --since 15m | grep "500\|router\|pick"
```

### 2. Verify env vars on Vercel — this is the #1 cause
```sh
npx vercel env ls --app aethersystems
```
Confirm ALL of these are present and non-empty:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `AETHER_INTERNAL_SERVICE_TOKEN`

Missing or blank env vars cause immediate 500s on cold starts.

### 3. Curl test the endpoint directly (PowerShell)
```powershell
$body = @{
  userId = "00000000-0000-0000-0000-000000000001"
  tier = "pro"
  taskKind = "chat"
  estimatedInputTokens = 1000
  estimatedOutputTokens = 500
  requestId = "test-$(Get-Random)"
  traceId = "trace-$(Get-Random)"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method POST `
  -Uri "https://aethersystems.net/api/internal/router/pick" `
  -Headers @{ "x-aether-internal" = $env:AETHER_INTERNAL_SERVICE_TOKEN } `
  -Body $body `
  -ContentType "application/json"
```
Expected: 200 with `chosen_model`, `reason_code`. If 401: token mismatch. If 500: check env vars.

### 4. Unix curl equivalent
```sh
curl -s -X POST https://aethersystems.net/api/internal/router/pick \
  -H "Content-Type: application/json" \
  -H "x-aether-internal: $AETHER_INTERNAL_SERVICE_TOKEN" \
  -d '{"userId":"00000000-0000-0000-0000-000000000001","tier":"pro","taskKind":"chat","estimatedInputTokens":1000,"estimatedOutputTokens":500,"requestId":"test-1","traceId":"trace-1"}'
```

## Mitigation (Stop the Bleeding)
If env vars are confirmed wrong, add/fix them immediately:
```sh
npx vercel env add SUPABASE_URL production
npx vercel env add SUPABASE_SERVICE_ROLE_KEY production
```
Then redeploy (Step 2 below).

## Recovery

### 1. Verify env vars (see Diagnosis step 2)

### 2. Redeploy without build cache
```sh
npx vercel --prod --force --build-env NEXT_TELEMETRY_DISABLED=1
```
Uncheck "Use build cache" in Vercel dashboard, or use `--force` flag.

### 3. Curl verify after deploy (see Diagnosis step 3/4)
Confirm 200 response with valid routing decision.

### 4. Check routing_decisions table for resumed writes
```sh
curl -s \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  "$SUPABASE_URL/rest/v1/routing_decisions?order=created_at.desc&limit=3" | jq .
```

## Post-Incident
- Document which env var was missing/wrong and how it happened
- Consider: add a startup health check that validates required env vars at deploy time
