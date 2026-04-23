# Runbook: Internal Token Rotation

## When to Run
- Quarterly scheduled rotation
- Any suspected compromise of `AETHER_INTERNAL_SERVICE_TOKEN`
- Employee/contractor offboarding who had access to the token

## Who to Ping
- Owner: lilbenxo@gmail.com

## Steps

### 1. Generate a new secure token
```sh
# Generate 32-byte hex token
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```
Save the output — you won't see it again.

### 2. Set the new token on Vercel
```sh
npx vercel env rm AETHER_INTERNAL_SERVICE_TOKEN production
npx vercel env add AETHER_INTERNAL_SERVICE_TOKEN production
# Paste new token when prompted
```

### 3. Redeploy production
```sh
npx vercel --prod --force
```

### 4. Curl verify with new token
```sh
curl -s -X POST https://aethersystems.net/api/internal/router/pick \
  -H "Content-Type: application/json" \
  -H "x-aether-internal: <NEW_TOKEN>" \
  -d '{"userId":"00000000-0000-0000-0000-000000000001","tier":"pro","taskKind":"chat","estimatedInputTokens":100,"estimatedOutputTokens":50,"requestId":"rotation-test","traceId":"rotation-trace"}'
```
Expected: 200. If 401: redeploy didn't pick up new token — wait 30s and retry.

### 5. Update all internal callers (desktop app, agent, etc.)
Since we currently have no external clients, only internal callers need updating.
```sh
# Find all references to the old token in codebase
grep -r "AETHER_INTERNAL" . --include="*.ts" --include="*.py" --include="*.env*"
```
Update env vars on each service that calls the router.

## Token Rotation with Grace Period (Optional)
If callers may have the old token cached, use the prev-token approach:

```sh
# Set old token as PREV (allows both old and new during transition)
npx vercel env add AETHER_INTERNAL_SERVICE_TOKEN_PREV production
# Paste OLD token when prompted
npx vercel env add AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT production
# Paste expiry timestamp (Unix ms, e.g. now + 1 hour)
npx vercel --prod --force
```

After all callers are updated, remove the prev token:
```sh
npx vercel env rm AETHER_INTERNAL_SERVICE_TOKEN_PREV production
npx vercel env rm AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT production
npx vercel --prod --force
```

## Rollback
If the new token causes issues:
```sh
npx vercel env rm AETHER_INTERNAL_SERVICE_TOKEN production
npx vercel env add AETHER_INTERNAL_SERVICE_TOKEN production
# Paste OLD token
npx vercel --prod --force
```

## Post-Incident
- Log rotation in a private note (date, reason, who performed it)
- Do NOT log the token value itself anywhere
