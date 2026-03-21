#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AetherCloud-L — VPS1 Deployment Script
# Server:  143.198.162.111
# Purpose: AETHER-SCRAMBLER Ghost Protocol + Nginx reverse proxy
# Proxy:   0.0.0.0:8080 → 198.211.115.41:8080 (VPS2 backend)
#
# Usage:   ssh root@143.198.162.111
#          bash vps1-deploy.sh
#
# Aether Systems LLC · Patent Pending
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# ── Config ────────────────────────────────────────────
INSTALL_DIR="/opt/aether-scrambler"
REPO_URL="https://github.com/DBarr3/AETHER-SCRAMBLER.git"
COMMIT="1c63637"
SERVICE_NAME="aether-scrambler"
SCRAMBLER_PORT=8077
NGINX_LISTEN_PORT=8080
VPS2_UPSTREAM="198.211.115.41:8080"
PYTHON_MIN="3.10"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER-SCRAMBLER — VPS1 Deployment"
echo "  Server: 143.198.162.111"
echo "  Proxy:  :${NGINX_LISTEN_PORT} → ${VPS2_UPSTREAM}"
echo "═══════════════════════════════════════════════════"
echo ""

# ══════════════════════════════════════════════════════
# STEP 1: System Update + Dependencies
# ══════════════════════════════════════════════════════
info "Step 1/7: Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  git curl nginx build-essential libffi-dev libssl-dev
ok "System packages updated"

# Verify Python version
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: ${PYTHON_VER}"
python3 -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'" || fail "Python ${PYTHON_MIN}+ required, found ${PYTHON_VER}"
ok "Python ${PYTHON_VER} meets minimum requirement"

# ══════════════════════════════════════════════════════
# STEP 2: Clone AETHER-SCRAMBLER
# ══════════════════════════════════════════════════════
info "Step 2/7: Cloning AETHER-SCRAMBLER..."
if [ -d "${INSTALL_DIR}" ]; then
  info "Directory exists — pulling latest..."
  cd "${INSTALL_DIR}"
  git fetch origin
  git checkout "${COMMIT}" 2>/dev/null || git checkout main
  ok "Repository updated"
else
  git clone "${REPO_URL}" "${INSTALL_DIR}"
  cd "${INSTALL_DIR}"
  git checkout "${COMMIT}" 2>/dev/null || info "Commit ${COMMIT} not found, using HEAD"
  ok "Repository cloned to ${INSTALL_DIR}"
fi

# ══════════════════════════════════════════════════════
# STEP 3: Python Virtual Environment + Dependencies
# ══════════════════════════════════════════════════════
info "Step 3/7: Setting up Python virtual environment..."
cd "${INSTALL_DIR}"

if [ ! -d "venv" ]; then
  python3 -m venv venv
  ok "Virtual environment created"
else
  info "Virtual environment already exists"
fi

source venv/bin/activate

# Upgrade pip first
pip install --upgrade pip setuptools wheel -q

# Install dependencies
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt -q
  ok "Dependencies installed from requirements.txt"
elif [ -f "pyproject.toml" ]; then
  pip install -e "." -q
  ok "Dependencies installed from pyproject.toml"
else
  fail "No requirements.txt or pyproject.toml found"
fi

deactivate
ok "Python environment ready"

# ══════════════════════════════════════════════════════
# STEP 4: Create .env file (if not exists)
# ══════════════════════════════════════════════════════
info "Step 4/7: Configuring environment..."
ENV_FILE="${INSTALL_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
  cat > "${ENV_FILE}" << 'ENVEOF'
# AETHER-SCRAMBLER Environment
# VPS1: Ghost Protocol + Proxy Node
AETHER_NODE_TYPE=proxy
AETHER_BIND_HOST=127.0.0.1
AETHER_BIND_PORT=8077
AETHER_UPSTREAM=http://198.211.115.41:8080
ENVEOF
  ok "Created ${ENV_FILE}"
else
  info ".env already exists — skipping"
fi

# ══════════════════════════════════════════════════════
# STEP 5: Create systemd Service
# ══════════════════════════════════════════════════════
info "Step 5/7: Creating systemd service..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << SVCEOF
[Unit]
Description=AETHER-SCRAMBLER Ghost Protocol Terminal
Documentation=https://github.com/DBarr3/AETHER-SCRAMBLER
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${INSTALL_DIR}
Environment=PATH=${INSTALL_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/python -m scrambler.terminal_ui.server --host 127.0.0.1 --port ${SCRAMBLER_PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}

# Wait for service to start
sleep 2
if systemctl is-active --quiet ${SERVICE_NAME}; then
  ok "Service ${SERVICE_NAME} is running"
else
  info "Service may still be starting — check: journalctl -u ${SERVICE_NAME} -n 20"
fi

# ══════════════════════════════════════════════════════
# STEP 6: Configure Nginx Reverse Proxy
# ══════════════════════════════════════════════════════
info "Step 6/7: Configuring Nginx reverse proxy..."

# Remove default site
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/aether-proxy << 'NGXEOF'
# AETHER-SCRAMBLER — Nginx Reverse Proxy
# Listens on :8080, proxies to VPS2 (198.211.115.41:8080)
# Also serves local SCRAMBLER terminal on /terminal

upstream vps2_backend {
    server 198.211.115.41:8080;
    keepalive 16;
}

upstream scrambler_local {
    server 127.0.0.1:8077;
    keepalive 8;
}

server {
    listen 8080 default_server;
    listen [::]:8080 default_server;
    server_name _;

    # ── CORS Headers ──────────────────────────────
    # Allow Electron app (file://), localhost, and VPS origins
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
    add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Requested-With' always;
    add_header 'Access-Control-Allow-Credentials' 'true' always;

    # Handle CORS preflight
    if ($request_method = 'OPTIONS') {
        add_header 'Access-Control-Allow-Origin' '*';
        add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
        add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, X-Requested-With';
        add_header 'Access-Control-Max-Age' 86400;
        add_header 'Content-Length' 0;
        add_header 'Content-Type' 'text/plain';
        return 204;
    }

    # ── Ghost Protocol Terminal (local) ───────────
    location /terminal {
        proxy_pass http://scrambler_local/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    location /terminal/api/ {
        proxy_pass http://scrambler_local/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # ── VPS2 Backend Proxy (all other routes) ─────
    location / {
        proxy_pass http://vps2_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        # Timeouts for long-running agent requests
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;
        proxy_send_timeout 60s;

        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # ── Health check ──────────────────────────────
    location /nginx-health {
        access_log off;
        return 200 '{"status":"ok","node":"vps1","proxy":"active"}';
        add_header Content-Type application/json;
    }

    # ── Error pages ───────────────────────────────
    error_page 502 503 504 /50x.html;
    location = /50x.html {
        internal;
        return 502 '{"error":"upstream_unavailable","node":"vps1","upstream":"198.211.115.41:8080"}';
        add_header Content-Type application/json;
    }
}
NGXEOF

# Enable site
ln -sf /etc/nginx/sites-available/aether-proxy /etc/nginx/sites-enabled/aether-proxy

# Test Nginx config
nginx -t || fail "Nginx configuration test failed"

# Restart Nginx
systemctl enable nginx
systemctl restart nginx
ok "Nginx reverse proxy configured and running"

# ══════════════════════════════════════════════════════
# STEP 7: Firewall (if UFW is active)
# ══════════════════════════════════════════════════════
info "Step 7/7: Configuring firewall..."
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
  ufw allow 8080/tcp comment "AetherCloud proxy"
  ufw allow 22/tcp comment "SSH"
  ok "Firewall rules added"
else
  info "UFW not active — skipping firewall config"
fi

# ══════════════════════════════════════════════════════
# VERIFICATION
# ══════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS1 DEPLOYMENT COMPLETE${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Services:"
systemctl is-active ${SERVICE_NAME} && echo -e "  ${GREEN}✓${NC} ${SERVICE_NAME}" || echo -e "  ${RED}✗${NC} ${SERVICE_NAME}"
systemctl is-active nginx && echo -e "  ${GREEN}✓${NC} nginx" || echo -e "  ${RED}✗${NC} nginx"
echo ""
echo "Ports:"
ss -tlnp | grep -E ":(8077|8080)" | awk '{print "  " $1 " " $4}' || echo "  (checking...)"
echo ""
echo "Verification commands:"
echo "  curl http://localhost:8080/status           # VPS2 backend via proxy"
echo "  curl http://localhost:8080/nginx-health     # Nginx health check"
echo "  curl http://localhost:8077/api/status        # Local SCRAMBLER"
echo "  journalctl -u ${SERVICE_NAME} -n 20         # SCRAMBLER logs"
echo "  journalctl -u nginx -n 20                   # Nginx logs"
echo "  sudo systemctl status ${SERVICE_NAME}       # Service status"
echo "  sudo systemctl status nginx                 # Nginx status"
echo ""
echo "External test (from Windows):"
echo "  curl http://143.198.162.111:8080/status"
echo "  curl http://143.198.162.111:8080/nginx-health"
echo ""
