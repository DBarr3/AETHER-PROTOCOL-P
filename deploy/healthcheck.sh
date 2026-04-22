#!/usr/bin/env bash
# healthcheck.sh — cron-friendly probe of /healthz, /healthz/deep, /healthz/flags.
#
# Exit 0 = all three probes succeeded within budget.
# Exit 1 = something failed. Crontab uses this to trigger alerting.
#
# Crontab example (paste with `sudo crontab -e -u aether`):
#   * * * * * /opt/aether/deploy/healthcheck.sh || curl -s -X POST "$SLACK_WEBHOOK" -d '{"text":"AetherCloud healthcheck failed"}'
#
# Aether Systems LLC — Patent Pending

set -euo pipefail

BASE="${AETHER_HEALTH_BASE:-http://127.0.0.1:8000}"

# 1. Liveness — must be fast + always respond
if ! curl -fsS --max-time 5 "$BASE/healthz" > /dev/null; then
    echo "[healthcheck] /healthz FAILED"
    exit 1
fi

# 2. Deep — DB reachable
if ! curl -fsS --max-time 5 "$BASE/healthz/deep" > /dev/null; then
    echo "[healthcheck] /healthz/deep FAILED"
    exit 1
fi

# 3. Flags — confirms feature_flags module imported and env is readable.
# We grep for the literal key name because deploy/vps2-runbook.md tells
# operators to paste it into alerting; the grep catches structure drift.
if ! curl -fsS --max-time 5 "$BASE/healthz/flags" | grep -q "AETHER_UVT_ENABLED"; then
    echo "[healthcheck] /healthz/flags missing expected key"
    exit 1
fi

echo "OK"
