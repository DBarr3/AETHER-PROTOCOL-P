#!/bin/bash
# AetherCloud-L — VPS2 Health Check
# Run on VPS2 after deployment to confirm everything is wired.
# Usage: bash scripts/verify_vps2.sh
#
# Aether Systems LLC — Patent Pending

echo "AetherCloud-L — VPS2 Health Check"
echo "==================================="

PASS=0
FAIL=0
WARN=0

ok()   { echo "[OK] $1"; PASS=$((PASS+1)); }
fail() { echo "[!!] $1"; FAIL=$((FAIL+1)); }
warn() { echo "[??] $1"; WARN=$((WARN+1)); }

# Check api_server is running
if pgrep -f "api_server.py" > /dev/null; then
    ok "api_server.py is running"
else
    fail "api_server.py NOT running — start with: python api_server.py"
fi

# Check port 8080 is open
if ss -tlnp 2>/dev/null | grep -q ":8080"; then
    ok "Port 8080 is listening"
elif netstat -tlnp 2>/dev/null | grep -q ":8080"; then
    ok "Port 8080 is listening"
else
    fail "Port 8080 NOT listening"
fi

# Check env keys loaded
if [ -f /etc/aethercloud/.env ]; then
    ok "/etc/aethercloud/.env exists"

    PERMS=$(stat -c '%a' /etc/aethercloud/.env 2>/dev/null)
    if [ "$PERMS" = "600" ]; then
        ok ".env permissions are 600 (owner read/write only)"
    else
        fail ".env permissions are $PERMS — should be 600"
    fi

    if grep -q "ANTHROPIC_API_KEY" /etc/aethercloud/.env; then
        ok "ANTHROPIC_API_KEY present in .env"
    else
        fail "ANTHROPIC_API_KEY missing from .env"
    fi
    if grep -q "IBM_QUANTUM_API_KEY" /etc/aethercloud/.env; then
        ok "IBM_QUANTUM_API_KEY present in .env"
    else
        warn "IBM_QUANTUM_API_KEY not set — quantum fallback will be used"
    fi
else
    fail "/etc/aethercloud/.env not found — run: sudo bash scripts/setup_keys.sh"
fi

# Test /status endpoint
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/status 2>/dev/null)
if [ "$STATUS" = "200" ]; then
    ok "/status endpoint responding (HTTP 200)"
else
    fail "/status returned HTTP $STATUS"
fi

# Test /auth/health endpoint
AUTH=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/auth/health 2>/dev/null)
if [ "$AUTH" = "200" ]; then
    ok "/auth/health endpoint responding (HTTP 200)"
else
    fail "/auth/health returned HTTP $AUTH"
fi

# Test /routing-check endpoint
ROUTE=$(curl -s http://localhost:8080/routing-check 2>/dev/null)
if echo "$ROUTE" | grep -q '"server":"VPS2"'; then
    ok "/routing-check confirms VPS2 identity"

    if echo "$ROUTE" | grep -q '"anthropic_key_set":true'; then
        ok "Anthropic API key is loaded"
    else
        fail "Anthropic API key NOT loaded on VPS2"
    fi
else
    fail "/routing-check not responding correctly"
fi

# Check no env.py exists in repo
REPO_DIR=$(dirname "$(dirname "$(readlink -f "$0")")")
if [ -f "$REPO_DIR/env.py" ]; then
    fail "env.py exists in repo — DELETE IT"
else
    ok "No env.py in repo directory"
fi

# Check no hardcoded keys in settings.py
if grep -q "sk-ant-" "$REPO_DIR/config/settings.py" 2>/dev/null; then
    fail "Hardcoded API key found in config/settings.py"
else
    ok "No hardcoded API keys in settings.py"
fi

echo "==================================="
echo "Results: $PASS passed, $FAIL failed, $WARN warnings"
if [ "$FAIL" -gt 0 ]; then
    echo "FIX FAILURES BEFORE PRODUCTION USE"
else
    echo "ALL CHECKS PASSED"
fi
echo "==================================="
