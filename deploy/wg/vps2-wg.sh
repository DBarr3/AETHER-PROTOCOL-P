#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER GHOST MESH — VPS2 WireGuard Setup (Data Plane)
# Node:    VPS2 — 198.211.115.41
# WG IP:   10.8.0.2/24
# Role:    Dark API — accepts traffic ONLY from VPS3 relay
#
# RUN ON:  ssh root@198.211.115.41
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[WG-VPS2]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}     $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}   $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}   $1"; exit 1; }

WG_IFACE="wg0"
WG_IP="10.8.0.2/24"
WG_PORT=51820
WG_CONF="/etc/wireguard/${WG_IFACE}.conf"
WG_DIR="/etc/wireguard"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER GHOST MESH — VPS2 WireGuard Setup"
echo "  Role: Dark API Node"
echo "  Mesh IP: 10.8.0.2"
echo "═══════════════════════════════════════════════════"
echo ""

info "Installing WireGuard..."
apt-get update -qq
apt-get install -y -qq wireguard wireguard-tools
ok "WireGuard installed"

mkdir -p "${WG_DIR}"
chmod 700 "${WG_DIR}"

if [ ! -f "${WG_DIR}/vps2.private" ]; then
  info "Generating VPS2 keypair..."
  wg genkey | tee "${WG_DIR}/vps2.private" | wg pubkey > "${WG_DIR}/vps2.public"
  chmod 600 "${WG_DIR}/vps2.private"
  ok "Keypair generated"
else
  warn "Keypair already exists — reusing"
fi

VPS2_PRIVKEY=$(cat "${WG_DIR}/vps2.private")
VPS2_PUBKEY=$(cat "${WG_DIR}/vps2.public")

info "Writing ${WG_CONF}..."
cat > "${WG_CONF}" << WGEOF
# AETHER GHOST MESH — VPS2 (Dark API)
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Single peer: VPS3 relay only. VPS2 is invisible to the internet.

[Interface]
Address    = ${WG_IP}
ListenPort = ${WG_PORT}
PrivateKey = ${VPS2_PRIVKEY}

# ── VPS3 (Ghost Relay — only allowed peer) ────────────
[Peer]
# VPS3 Ghost Relay
PublicKey           = PASTE_VPS3_PUBLIC_KEY_HERE
AllowedIPs          = 10.8.0.3/32
Endpoint            = 161.35.109.243:${WG_PORT}
PersistentKeepalive = 25

# NOTE: VPS2 only peers with VPS3.
# VPS1 cannot reach VPS2 directly — enforced at both WG and firewall level.
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
  ok "UFW: WireGuard port open"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS2 WireGuard READY${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo -e "  ${YELLOW}VPS2 PUBLIC KEY (save this):${NC}"
echo "  ${VPS2_PUBKEY}"
echo ""
echo "  IMPORTANT: Run vps2-lockdown.sh AFTER mesh-link.sh"
echo "  to close VPS2's public port 8080."
echo ""
