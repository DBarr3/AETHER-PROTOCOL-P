#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER GHOST MESH — Key Exchange + Peer Linking
#
# Run this AFTER vps1-wg.sh, vps2-wg.sh, vps3-wg.sh are all done.
# SSH into each VPS and copy the public key it printed.
# Then run this script with the 3 public keys as arguments.
#
# USAGE (run locally or from any VPS with SSH access to all 3):
#   bash mesh-link.sh \
#     <VPS1_PUBKEY> \
#     <VPS2_PUBKEY> \
#     <VPS3_PUBKEY>
#
# Example:
#   bash mesh-link.sh \
#     "abc123...VPS1key...xyz" \
#     "def456...VPS2key...uvw" \
#     "ghi789...VPS3key...rst"
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[MESH-LINK]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}       $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}     $1"; exit 1; }

[ "$#" -ne 3 ] && fail "Usage: bash mesh-link.sh <VPS1_PUBKEY> <VPS2_PUBKEY> <VPS3_PUBKEY>"

VPS1_PUB="$1"
VPS2_PUB="$2"
VPS3_PUB="$3"

VPS1_SSH="root@143.198.162.111"
VPS2_SSH="root@198.211.115.41"
VPS3_SSH="root@161.35.109.243"

WG_PORT=51820

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER GHOST MESH — Key Exchange"
echo "═══════════════════════════════════════════════════"
echo ""

# ── VPS1: inject VPS3 public key ─────────────────────
info "Configuring VPS1 peer (VPS3)..."
ssh "${VPS1_SSH}" "
  sed -i 's|PASTE_VPS3_PUBLIC_KEY_HERE|${VPS3_PUB}|g' /etc/wireguard/wg0.conf
  systemctl restart wg-quick@wg0
  wg show wg0
"
ok "VPS1 peer configured"

# ── VPS3: inject VPS1 and VPS2 public keys ───────────
info "Configuring VPS3 peers (VPS1 + VPS2)..."
ssh "${VPS3_SSH}" "
  sed -i 's|PASTE_VPS1_PUBLIC_KEY_HERE|${VPS1_PUB}|g' /etc/wireguard/wg0.conf
  sed -i 's|PASTE_VPS2_PUBLIC_KEY_HERE|${VPS2_PUB}|g' /etc/wireguard/wg0.conf
  systemctl restart wg-quick@wg0
  wg show wg0
"
ok "VPS3 peers configured"

# ── VPS2: inject VPS3 public key ─────────────────────
info "Configuring VPS2 peer (VPS3)..."
ssh "${VPS2_SSH}" "
  sed -i 's|PASTE_VPS3_PUBLIC_KEY_HERE|${VPS3_PUB}|g' /etc/wireguard/wg0.conf
  systemctl restart wg-quick@wg0
  wg show wg0
"
ok "VPS2 peer configured"

# ── Verify mesh connectivity ──────────────────────────
echo ""
info "Testing mesh connectivity..."

echo -n "  VPS1 → VPS3 (10.8.0.3): "
ssh "${VPS1_SSH}" "ping -c 2 -W 3 10.8.0.3 > /dev/null 2>&1 && echo OK || echo FAIL"

echo -n "  VPS3 → VPS1 (10.8.0.1): "
ssh "${VPS3_SSH}" "ping -c 2 -W 3 10.8.0.1 > /dev/null 2>&1 && echo OK || echo FAIL"

echo -n "  VPS3 → VPS2 (10.8.0.2): "
ssh "${VPS3_SSH}" "ping -c 2 -W 3 10.8.0.2 > /dev/null 2>&1 && echo OK || echo FAIL"

echo -n "  VPS2 → VPS3 (10.8.0.3): "
ssh "${VPS2_SSH}" "ping -c 2 -W 3 10.8.0.3 > /dev/null 2>&1 && echo OK || echo FAIL"

echo -n "  VPS1 → VPS2 direct (should FAIL — relay enforced): "
ssh "${VPS1_SSH}" "ping -c 2 -W 3 10.8.0.2 > /dev/null 2>&1 && echo WARN_REACHABLE || echo OK_BLOCKED"

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}MESH LINKED${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo "  1. Run vps3-relay.sh on VPS3"
echo "  2. Run vps2-lockdown.sh on VPS2"
echo "  3. Run updated vps1-deploy.sh on VPS1"
echo ""
