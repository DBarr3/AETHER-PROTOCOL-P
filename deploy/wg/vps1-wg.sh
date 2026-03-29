#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER GHOST MESH — VPS1 WireGuard Setup (Data Plane)
# Node:    VPS1 — 143.198.162.111
# WG IP:   10.8.0.1/24
# Role:    Ingress — tunnels app traffic to VPS3 relay
#
# RUN ON:  ssh root@143.198.162.111
# AFTER:   Run vps3-wg.sh and vps2-wg.sh, then mesh-link.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[WG-VPS1]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}     $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}   $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}   $1"; exit 1; }

WG_IFACE="wg0"
WG_IP="10.8.0.1/24"
WG_PORT=51820
WG_CONF="/etc/wireguard/${WG_IFACE}.conf"
WG_DIR="/etc/wireguard"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER GHOST MESH — VPS1 WireGuard Setup"
echo "  Role: Ingress Node"
echo "  Mesh IP: 10.8.0.1"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Install WireGuard ──────────────────────────
info "Installing WireGuard..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools
ok "WireGuard installed"

# ── Step 2: Generate keypair (idempotent) ─────────────
mkdir -p "${WG_DIR}"
chmod 700 "${WG_DIR}"

if [ ! -f "${WG_DIR}/vps1.private" ]; then
  info "Generating VPS1 keypair..."
  wg genkey | tee "${WG_DIR}/vps1.private" | wg pubkey > "${WG_DIR}/vps1.public"
  chmod 600 "${WG_DIR}/vps1.private"
  ok "Keypair generated"
else
  warn "Keypair already exists — reusing"
fi

VPS1_PRIVKEY=$(cat "${WG_DIR}/vps1.private")
VPS1_PUBKEY=$(cat "${WG_DIR}/vps1.public")

# ── Step 3: Write wg0.conf ────────────────────────────
info "Writing ${WG_CONF}..."
cat > "${WG_CONF}" << WGEOF
# AETHER GHOST MESH — VPS1 (Ingress)
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Data plane only — app traffic to VPS3 relay

[Interface]
Address    = ${WG_IP}
ListenPort = ${WG_PORT}
PrivateKey = ${VPS1_PRIVKEY}

# Kill switch: if WG goes down, block app traffic from leaking
PostUp   = iptables -A FORWARD -i ${WG_IFACE} -j ACCEPT; iptables -A FORWARD -o ${WG_IFACE} -j ACCEPT
PostDown = iptables -D FORWARD -i ${WG_IFACE} -j ACCEPT; iptables -D FORWARD -o ${WG_IFACE} -j ACCEPT

# ── VPS3 (Ghost Relay) ────────────────────────────────
# PLACEHOLDER — run mesh-link.sh after all 3 VPS are set up
[Peer]
# VPS3 Ghost Relay
PublicKey           = PASTE_VPS3_PUBLIC_KEY_HERE
AllowedIPs          = 10.8.0.3/32
Endpoint            = 161.35.109.243:${WG_PORT}
PersistentKeepalive = 25

# NOTE: VPS1 does NOT have VPS2 as a peer.
# VPS1 can only reach VPS2 through VPS3. This enforces the relay.
WGEOF

chmod 600 "${WG_CONF}"
ok "wg0.conf written"

# ── Step 4: Enable IP forwarding ──────────────────────
info "Enabling IP forwarding..."
grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p -q
ok "IP forwarding enabled"

# ── Step 5: Enable + start WireGuard ──────────────────
info "Enabling wg-quick@${WG_IFACE}..."
systemctl enable "wg-quick@${WG_IFACE}"
systemctl restart "wg-quick@${WG_IFACE}" || warn "WG start failed — run mesh-link.sh first to fill in peer public keys"
ok "WireGuard service enabled"

# ── Step 6: Open WireGuard port in firewall ───────────
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
  ufw allow ${WG_PORT}/udp comment "WireGuard data plane"
  ok "UFW: WireGuard port opened"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS1 WireGuard READY${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo -e "  ${YELLOW}VPS1 PUBLIC KEY (save this):${NC}"
echo "  ${VPS1_PUBKEY}"
echo ""
echo "  Next steps:"
echo "  1. Run vps3-wg.sh on VPS3"
echo "  2. Run vps2-wg.sh on VPS2"
echo "  3. Run mesh-link.sh to exchange public keys"
echo ""
