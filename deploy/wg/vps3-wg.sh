#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER GHOST MESH — VPS3 WireGuard Setup (Data Plane)
# Node:    VPS3 — 161.35.109.243
# WG IP:   10.8.0.3/24
# Role:    Ghost Relay — bridges VPS1 ingress to VPS2 dark API
#
# RUN ON:  ssh root@161.35.109.243
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[WG-VPS3]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}     $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}   $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}   $1"; exit 1; }

WG_IFACE="wg0"
WG_IP="10.8.0.3/24"
WG_PORT=51820
WG_CONF="/etc/wireguard/${WG_IFACE}.conf"
WG_DIR="/etc/wireguard"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER GHOST MESH — VPS3 WireGuard Setup"
echo "  Role: Ghost Relay"
echo "  Mesh IP: 10.8.0.3"
echo "═══════════════════════════════════════════════════"
echo ""

info "Installing WireGuard..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools
ok "WireGuard installed"

mkdir -p "${WG_DIR}"
chmod 700 "${WG_DIR}"

if [ ! -f "${WG_DIR}/vps3.private" ]; then
  info "Generating VPS3 keypair..."
  wg genkey | tee "${WG_DIR}/vps3.private" | wg pubkey > "${WG_DIR}/vps3.public"
  chmod 600 "${WG_DIR}/vps3.private"
  ok "Keypair generated"
else
  warn "Keypair already exists — reusing"
fi

VPS3_PRIVKEY=$(cat "${WG_DIR}/vps3.private")
VPS3_PUBKEY=$(cat "${WG_DIR}/vps3.public")

info "Writing ${WG_CONF}..."
cat > "${WG_CONF}" << WGEOF
# AETHER GHOST MESH — VPS3 (Ghost Relay)
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Bridges VPS1 ingress to VPS2 dark API — central relay node

[Interface]
Address    = ${WG_IP}
ListenPort = ${WG_PORT}
PrivateKey = ${VPS3_PRIVKEY}

# Enable routing between peers (VPS1 ↔ VPS2 through VPS3)
PostUp   = iptables -A FORWARD -i ${WG_IFACE} -j ACCEPT; iptables -A FORWARD -o ${WG_IFACE} -j ACCEPT; iptables -t nat -A POSTROUTING -o ${WG_IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i ${WG_IFACE} -j ACCEPT; iptables -D FORWARD -o ${WG_IFACE} -j ACCEPT; iptables -t nat -D POSTROUTING -o ${WG_IFACE} -j MASQUERADE

# ── VPS1 (Ingress) ────────────────────────────────────
[Peer]
# VPS1 Ingress Node
PublicKey           = PASTE_VPS1_PUBLIC_KEY_HERE
AllowedIPs          = 10.8.0.1/32
Endpoint            = 143.198.162.111:${WG_PORT}
PersistentKeepalive = 25

# ── VPS2 (Dark API) ───────────────────────────────────
[Peer]
# VPS2 Dark API
PublicKey           = PASTE_VPS2_PUBLIC_KEY_HERE
AllowedIPs          = 10.8.0.2/32
Endpoint            = 198.211.115.41:${WG_PORT}
PersistentKeepalive = 25
WGEOF

chmod 600 "${WG_CONF}"
ok "wg0.conf written"

info "Enabling IP forwarding..."
grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p -q
ok "IP forwarding enabled"

systemctl enable "wg-quick@${WG_IFACE}"
systemctl restart "wg-quick@${WG_IFACE}" || warn "WG start failed — run mesh-link.sh first"

if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
  ufw allow ${WG_PORT}/udp comment "WireGuard data plane"
  ufw allow from 10.8.0.1 to any port 8080 comment "VPS1 relay traffic"
  ok "UFW rules applied"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS3 WireGuard READY${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo -e "  ${YELLOW}VPS3 PUBLIC KEY (save this):${NC}"
echo "  ${VPS3_PUBKEY}"
echo ""
