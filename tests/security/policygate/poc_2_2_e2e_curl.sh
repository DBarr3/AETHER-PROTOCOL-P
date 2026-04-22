#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# §2.2 + §2.4 E2E PoC (curl) — bypass opus/balance/concurrency gates
# against a locally-running dev server.
#
# Prereqs:
#   1. `cd site && AETHER_INTERNAL_SERVICE_TOKEN=<REDACTED-TOKEN> npm run dev`
#   2. export ATK_TOKEN=<REDACTED-TOKEN>  (same value)
#
# This script:
#   * proves the 401 path without the token header
#   * demonstrates the triple gate bypass in one POST — Pro tier user
#     gets claude-opus-4 at 99% lied-MTD-usage, 50 concurrent lied,
#     and Number.MAX_SAFE_INTEGER balance lied.
#
# Do NOT run against production. Use a preview deploy at most.
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

URL="${URL:-http://localhost:3000/api/internal/router/pick}"
TOKEN="${ATK_TOKEN:-REDACTED-TOKEN-DEV-ONLY}"
UID_VALUE="00000000-0000-0000-0000-0000deadbeef"

echo "== A. unauthenticated POST → expect 401 =="
curl -sS -o - -w "\nHTTP %{http_code}\n" -X POST "$URL" \
  -H "content-type: application/json" \
  --data '{}' || true

echo
echo "== B. authenticated POST with triple-gate bypass =="
curl -sS -o - -w "\nHTTP %{http_code}\n" -X POST "$URL" \
  -H "content-type: application/json" \
  -H "x-aether-internal: $TOKEN" \
  --data "$(cat <<EOF
{
  "userId": "$UID_VALUE",
  "tier": "pro",
  "taskKind": "agent_plan",
  "estimatedInputTokens": 1000,
  "estimatedOutputTokens": 1000,
  "opusPctMtd": 0,
  "activeConcurrentTasks": 0,
  "uvtBalance": 9007199254740991,
  "requestId": "poc-e2e-1",
  "traceId": "poc-e2e-1"
}
EOF
)"
