#!/usr/bin/env bash
# rollback.sh — revert to the SHA deploy.sh recorded before the last deploy.
#
# Called automatically by deploy.sh when its post-restart healthcheck fails.
# Can also be invoked manually: `ssh aether@vps2 /opt/aether/deploy/rollback.sh`.
#
# For a faster rollback of UVT-stack behavior specifically, don't use this —
# flip AETHER_UVT_ENABLED=false in /opt/aether/.env and restart. That reverts
# /agent/run to the legacy path in ~3 seconds without touching git.
#
# Aether Systems LLC — Patent Pending

set -euo pipefail

AETHER_ROOT="${AETHER_ROOT:-/opt/aether}"
AETHER_SERVICE="${AETHER_SERVICE:-aether}"

cd "$AETHER_ROOT"

if [ ! -f .last-deployed-sha ]; then
  echo "[rollback] no .last-deployed-sha file — nothing to roll back to"
  echo "[rollback] (if you need to manually revert, run:"
  echo "    git reset --hard <sha> && .venv/bin/pip install -r requirements.txt && sudo systemctl restart $AETHER_SERVICE"
  echo ")"
  exit 1
fi

PREV="$(cat .last-deployed-sha)"
if [ -z "$PREV" ]; then
  echo "[rollback] .last-deployed-sha is empty"
  exit 1
fi

echo "[rollback] reverting to $PREV..."
git reset --hard "$PREV"

echo "[rollback] reinstalling dependencies (in case they changed)..."
.venv/bin/pip install -q -r requirements.txt

echo "[rollback] restarting systemd unit..."
sudo systemctl restart "$AETHER_SERVICE"

# Don't re-run healthcheck here — if rollback also fails, the loop is
# infinite. Just report and exit; operator decides next steps.
echo "[rollback] OK — reverted to $PREV"
echo "[rollback] run deploy/healthcheck.sh manually to confirm recovery"
