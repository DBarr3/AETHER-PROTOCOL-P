#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AetherCloud-L — VPS3 Deployment Script
# Server:  161.35.109.243
# Purpose: AETHER-SCRAMBLER Dark Node / Failover
#
# Usage:   ssh root@161.35.109.243
#          bash vps3-deploy.sh
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

echo ""
echo "═══════════════════════════════════════════════════"
echo "  AETHER-SCRAMBLER — VPS3 Dark Node Deployment"
echo "  Server: 161.35.109.243"
echo "  Port:   ${SCRAMBLER_PORT}"
echo "═══════════════════════════════════════════════════"
echo ""

# ══════════════════════════════════════════════════════
# STEP 1: System Update + Dependencies
# ══════════════════════════════════════════════════════
info "Step 1/5: Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  git curl build-essential libffi-dev libssl-dev
ok "System packages updated"

# Verify Python version
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: ${PYTHON_VER}"
python3 -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'" || fail "Python 3.10+ required, found ${PYTHON_VER}"
ok "Python ${PYTHON_VER} meets minimum requirement"

# ══════════════════════════════════════════════════════
# STEP 2: Clone AETHER-SCRAMBLER
# ══════════════════════════════════════════════════════
info "Step 2/5: Cloning AETHER-SCRAMBLER..."
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
info "Step 3/5: Setting up Python virtual environment..."
cd "${INSTALL_DIR}"

if [ ! -d "venv" ]; then
  python3 -m venv venv
  ok "Virtual environment created"
else
  info "Virtual environment already exists"
fi

source venv/bin/activate

pip install --upgrade pip setuptools wheel -q

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
info "Step 4/5: Configuring environment..."
ENV_FILE="${INSTALL_DIR}/.env"
if [ ! -f "${ENV_FILE}" ]; then
  cat > "${ENV_FILE}" << 'ENVEOF'
# AETHER-SCRAMBLER Environment
# VPS3: Dark Node / Failover
AETHER_NODE_TYPE=dark
AETHER_BIND_HOST=0.0.0.0
AETHER_BIND_PORT=8077
AETHER_NODE_ID=vps3-dark
ENVEOF
  ok "Created ${ENV_FILE}"
else
  info ".env already exists — skipping"
fi

# ══════════════════════════════════════════════════════
# STEP 5: Create systemd Service
# ══════════════════════════════════════════════════════
info "Step 5/5: Creating systemd service..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << SVCEOF
[Unit]
Description=AETHER-SCRAMBLER Dark Node
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
ExecStart=${INSTALL_DIR}/venv/bin/python -m scrambler.terminal_ui.server --host 0.0.0.0 --port ${SCRAMBLER_PORT}
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
# FIREWALL (if UFW is active)
# ══════════════════════════════════════════════════════
if command -v ufw &>/dev/null && ufw status | grep -q "active"; then
  ufw allow 8077/tcp comment "AETHER-SCRAMBLER dark node"
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
echo -e "  ${GREEN}VPS3 DARK NODE DEPLOYMENT COMPLETE${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Service:"
systemctl is-active ${SERVICE_NAME} && echo -e "  ${GREEN}✓${NC} ${SERVICE_NAME}" || echo -e "  ${RED}✗${NC} ${SERVICE_NAME}"
echo ""
echo "Port:"
ss -tlnp | grep ":${SCRAMBLER_PORT}" | awk '{print "  " $1 " " $4}' || echo "  (checking...)"
echo ""
echo "Verification commands:"
echo "  curl http://localhost:${SCRAMBLER_PORT}/api/status   # SCRAMBLER status"
echo "  journalctl -u ${SERVICE_NAME} -n 20                 # Service logs"
echo "  sudo systemctl status ${SERVICE_NAME}               # Service status"
echo "  ps aux | grep scrambler                             # Process check"
echo ""
echo "External test (from Windows):"
echo "  curl http://161.35.109.243:${SCRAMBLER_PORT}/api/status"
echo ""
