#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER GHOST RELAY — VPS3 Nginx Relay Setup
# Server:  161.35.109.243
# Purpose: Ghost relay — receives encrypted traffic from VPS1 via
#          WireGuard, strips/re-times headers, forwards to VPS2
#          on the dark WireGuard interface only.
#
# REQUIRES: vps3-wg.sh + mesh-link.sh completed first
# RUN ON:   ssh root@161.35.109.243
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[VPS3-RELAY]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}        $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}      $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}      $1"; exit 1; }

# Verify WireGuard is up before proceeding
ip addr show wg0 &>/dev/null || fail "wg0 interface not found — run vps3-wg.sh and mesh-link.sh first"
WG_IP=$(ip -4 addr show wg0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
[ "${WG_IP}" = "10.8.0.3" ] || fail "wg0 IP mismatch: expected 10.8.0.3, got ${WG_IP}"
ok "WireGuard interface verified: 10.8.0.3"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER GHOST RELAY — VPS3 Nginx Setup"
echo "  Listens: 10.8.0.3:8080 (WireGuard interface only)"
echo "  Forwards: 10.8.0.2:8080 (VPS2 dark API)"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Install nginx ─────────────────────────────
info "Installing nginx..."
apt-get update -qq
apt-get install -y -qq nginx
ok "nginx installed"

# ── Step 2: Write relay nginx config ─────────────────
info "Writing ghost relay nginx config..."
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/aether-relay << 'NGXEOF'
# AETHER GHOST RELAY — VPS3
# Listens ONLY on WireGuard interface (10.8.0.3)
# Forwards to VPS2 dark API (10.8.0.2:8080) via WireGuard mesh
# Public internet cannot reach this server on port 8080

upstream vps2_dark {
    server 10.8.0.2:8080;
    keepalive 16;
}

server {
    # CRITICAL: bind ONLY to the WireGuard interface IP
    # This means the public IP 161.35.109.243:8080 is NOT served
    listen 10.8.0.3:8080;
    server_name _;

    client_max_body_size 10m;

    # ── Ghost header stripping ──────────────────────────
    # Strip identifying headers before forwarding to VPS2
    proxy_set_header X-Real-IP        "";
    proxy_set_header X-Forwarded-For  "";
    proxy_set_header X-Forwarded-Host "";

    # ── Re-inject clean headers ─────────────────────────
    proxy_set_header Host              $host;
    proxy_set_header X-Ghost-Relay     "vps3";
    proxy_set_header X-Relay-Timestamp $msec;

    location / {
        proxy_pass         http://vps2_dark;
        proxy_http_version 1.1;
        proxy_set_header   Connection "";

        proxy_connect_timeout 10s;
        proxy_read_timeout    120s;
        proxy_send_timeout    60s;

        proxy_buffering    on;
        proxy_buffer_size  4k;
        proxy_buffers      8 4k;

        # CORS — relay passes through app-level CORS
        add_header 'Access-Control-Allow-Origin'  '*' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Requested-With' always;

        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin'  '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Requested-With';
            add_header 'Access-Control-Max-Age' 86400;
            add_header 'Content-Length' 0;
            add_header 'Content-Type' 'text/plain';
            return 204;
        }
    }

    location /relay-health {
        access_log off;
        return 200 '{"status":"relay_active","node":"vps3","upstream":"10.8.0.2:8080"}';
        add_header Content-Type application/json;
    }

    error_page 502 503 504 /relay-50x;
    location = /relay-50x {
        internal;
        return 502 '{"error":"dark_api_unreachable","relay":"vps3","upstream":"10.8.0.2:8080"}';
        add_header Content-Type application/json;
    }
}
NGXEOF

ln -sf /etc/nginx/sites-available/aether-relay /etc/nginx/sites-enabled/aether-relay

nginx -t || fail "nginx config test failed"
systemctl enable nginx
systemctl restart nginx
ok "Ghost relay nginx running on 10.8.0.3:8080"

# ── Step 3: Firewall — block 8080 on public interface ─
info "Applying firewall rules..."
if command -v ufw &>/dev/null; then
  ufw --force enable 2>/dev/null || true
  ufw default deny incoming
  ufw allow 22/tcp   comment "SSH"
  ufw allow 51820/udp comment "WireGuard data plane"
  # Allow 8080 ONLY from WireGuard mesh (10.8.0.x)
  ufw allow from 10.8.0.0/24 to any port 8080 comment "WG mesh relay traffic"
  # Explicitly block 8080 from public internet
  ufw deny 8080/tcp comment "Block public relay access"
  ok "UFW: port 8080 blocked on public IP, open on WG mesh only"
fi

# ── Step 4: Aether Scrambler service (dark node mode) ─
info "Configuring AETHER-SCRAMBLER in relay mode..."
SCRAMBLER_ENV="/opt/aether-scrambler/.env"
if [ -f "${SCRAMBLER_ENV}" ]; then
  sed -i 's/AETHER_NODE_TYPE=.*/AETHER_NODE_TYPE=relay/' "${SCRAMBLER_ENV}"
  systemctl restart aether-scrambler 2>/dev/null || warn "Scrambler not running — deploy it separately"
  ok "Scrambler set to relay mode"
else
  warn "Scrambler .env not found — run vps3-deploy.sh first"
fi

# ── Verification ──────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS3 GHOST RELAY ACTIVE${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Verification:"
echo "  curl http://10.8.0.3:8080/relay-health   # from VPS1 via WG"
echo "  curl http://10.8.0.3:8080/status         # proxied VPS2 response"
echo ""
echo "  Public 8080 should be BLOCKED:"
echo "  curl http://161.35.109.243:8080/         # must time out"
echo ""
