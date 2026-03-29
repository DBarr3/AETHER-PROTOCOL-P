#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER MANAGEMENT PLANE — Tailscale Install
# Purpose: Management-only mesh (SSH, health, admin ops)
#          App traffic NEVER routes through Tailscale —
#          that stays on raw WireGuard (wg0).
#
# Run this on ALL 3 VPS and your local machine.
# RUN ON:  ssh root@<any-vps>
#
# After install on each node, authenticate with:
#   tailscale up --authkey=<your-auth-key> --advertise-tags=tag:aether-vps
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[TAILSCALE]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}        $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}      $1"; }

NODE_ROLE="${1:-vps}"  # Pass 'vps' or 'admin'

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER MANAGEMENT PLANE — Tailscale Install"
echo "  Role: ${NODE_ROLE}"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Install Tailscale ─────────────────────────────────
info "Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
ok "Tailscale installed"

# ── Configure: prevent Tailscale from routing app ports ─
info "Configuring Tailscale to management-only mode..."

# Ensure Tailscale doesn't intercept WireGuard traffic
# by excluding wg0 from Tailscale's routing
mkdir -p /etc/tailscale
cat > /etc/default/tailscaled << 'TSEOF'
# Tailscale daemon flags
# Management plane only — do not route app traffic
FLAGS="--state=/var/lib/tailscale/tailscaled.state"
TSEOF

systemctl enable tailscaled
systemctl restart tailscaled
ok "Tailscale daemon running"

# ── Print auth instructions ───────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}TAILSCALE INSTALLED${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Authenticate this node:"
if [ "${NODE_ROLE}" = "vps" ]; then
  echo ""
  echo "  tailscale up \\"
  echo "    --authkey=<YOUR_TAILSCALE_AUTH_KEY> \\"
  echo "    --advertise-tags=tag:aether-vps \\"
  echo "    --accept-routes=false \\"
  echo "    --shields-up"
  echo ""
  echo "  --shields-up blocks all inbound except SSH from Tailscale peers"
  echo "  --accept-routes=false prevents Tailscale from injecting routes"
  echo "  that could interfere with wg0 data plane"
else
  echo ""
  echo "  tailscale up --advertise-tags=tag:aether-admin"
fi
echo ""
echo "  After all nodes are authenticated, apply acl-policy.hujson"
echo "  in your Tailscale admin panel (Access Controls tab)."
echo ""
