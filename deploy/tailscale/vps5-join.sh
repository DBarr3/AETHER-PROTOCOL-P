#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER MANAGEMENT PLANE — VPS5 Tailscale Join
# Purpose: Add VPS5 (MCP Worker) to the Aether Tailscale mesh
#
# Run on VPS5:
#   curl -fsSL https://tailscale.com/install.sh | sh
#   bash vps5-join.sh
#
# Or paste the whole script via SSH.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[VPS5-TS]${NC} $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}      $1"; }
fail() { echo -e "${RED}[FAIL]${NC}    $1"; exit 1; }

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER — VPS5 MCP Worker Tailscale Join"
echo "  Port 8095 will be reachable from VPS2 only"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Install Tailscale if not present ─────────────────
if ! command -v tailscale &>/dev/null; then
  info "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
  ok "Tailscale installed"
else
  ok "Tailscale already installed"
fi

# ── Configure daemon (management-only, no route injection) ─
info "Configuring Tailscale daemon..."
mkdir -p /etc/tailscale
cat > /etc/default/tailscaled << 'TSEOF'
# Tailscale daemon flags — management plane only
FLAGS="--state=/var/lib/tailscale/tailscaled.state"
TSEOF

systemctl enable tailscaled
systemctl restart tailscaled
ok "Tailscale daemon running"

# ── Prompt for auth key ───────────────────────────────
echo ""
echo "  Paste your Tailscale auth key (from tailscale.com/admin → Settings → Auth Keys):"
read -r -p "  Auth key: " TS_AUTHKEY

if [ -z "${TS_AUTHKEY}" ]; then
  fail "No auth key provided"
fi

# ── Join the mesh ─────────────────────────────────────
info "Joining Aether Tailscale mesh as aether-vps5..."
tailscale up \
  --authkey="${TS_AUTHKEY}" \
  --hostname=aether-vps5 \
  --advertise-tags=tag:aether-vps \
  --accept-routes=false \
  --shields-up

ok "VPS5 joined Tailscale mesh"

# ── Firewall: only allow 8095 from Tailscale interface ─
info "Configuring firewall — port 8095 Tailscale-only..."
if command -v ufw &>/dev/null; then
  # Allow 8095 only from Tailscale subnet (100.64.0.0/10)
  ufw allow in on tailscale0 to any port 8095 proto tcp comment "MCP worker — Tailscale only"
  # Block 8095 from public internet
  ufw deny 8095/tcp comment "MCP worker — block public"
  ok "UFW: port 8095 restricted to Tailscale interface"
else
  info "UFW not active — applying iptables rule instead"
  iptables -A INPUT -i tailscale0 -p tcp --dport 8095 -j ACCEPT
  iptables -A INPUT -p tcp --dport 8095 -j DROP
  ok "iptables: port 8095 restricted to Tailscale interface"
fi

# ── Verify ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS5 TAILSCALE JOIN COMPLETE${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
tailscale status
echo ""
echo "  VPS5 Tailscale IP:"
tailscale ip -4
echo ""
echo "  Next: update acl-policy.hujson in Tailscale admin"
echo "  to allow VPS2 → VPS5:8095"
echo ""
echo "  Test from VPS2:"
echo "    curl http://\$(tailscale ip -4):8095/health"
echo ""
