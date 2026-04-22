#!/usr/bin/env bash
# deploy.sh — one-command redeploy on VPS2.
#
# What it does:
#   1. git fetch + record the current SHA to .last-deployed-sha (rollback target)
#   2. git reset --hard to origin/main
#   3. pip install -r requirements.txt (idempotent)
#   4. systemctl restart aether
#   5. Wait 2s, then run healthcheck
#   6. If healthcheck fails: rollback automatically and exit 1
#
# Runbook steps that this does NOT cover:
#   - Supabase migrations (see deploy/vps2-runbook.md, "migrations" section)
#   - nginx config changes (manual reload)
#   - Env var changes (edit .env then `systemctl daemon-reload` + restart)
#
# Aether Systems LLC — Patent Pending

set -euo pipefail

AETHER_ROOT="${AETHER_ROOT:-/opt/aether}"
AETHER_SERVICE="${AETHER_SERVICE:-aether}"
AETHER_BRANCH="${AETHER_BRANCH:-main}"

cd "$AETHER_ROOT"

echo "[deploy] fetching origin/$AETHER_BRANCH..."
git fetch origin "$AETHER_BRANCH"

PREV_SHA="$(git rev-parse HEAD)"
NEW_SHA="$(git rev-parse origin/$AETHER_BRANCH)"

if [ "$PREV_SHA" = "$NEW_SHA" ]; then
  echo "[deploy] already at $NEW_SHA — nothing to deploy"
  exit 0
fi

# Record the pre-deploy SHA for rollback. rollback.sh reads this.
echo "$PREV_SHA" > .last-deployed-sha
echo "[deploy] prev SHA recorded: $PREV_SHA"

echo "[deploy] resetting to $NEW_SHA..."
git reset --hard "origin/$AETHER_BRANCH"

echo "[deploy] installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

# NOTE: Supabase DB migrations are applied out-of-band (via `supabase db push`
# from the operator's laptop), NOT from deploy.sh. Running schema changes
# from a deploy script mid-deploy makes rollback much harder — the SQL ran
# but we reverted the code that expects the new schema. Keep them separate.
echo "[deploy] (skipping migrations — run 'supabase db push' separately)"

echo "[deploy] restarting systemd unit..."
sudo systemctl restart "$AETHER_SERVICE"

# Give uvicorn a moment to bind :8000 before probing.
sleep 2

echo "[deploy] running healthcheck..."
if ! "$AETHER_ROOT/deploy/healthcheck.sh"; then
  echo "[deploy] HEALTHCHECK FAILED — rolling back to $PREV_SHA"
  "$AETHER_ROOT/deploy/rollback.sh"
  exit 1
fi

CURR="$(git rev-parse --short HEAD)"
echo "[deploy] OK — deployed $CURR"
