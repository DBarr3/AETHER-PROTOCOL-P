#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "[1/5] Updating system..."
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq python3 python3-venv python3-pip python3-dev git curl build-essential libffi-dev libssl-dev
echo "[OK] System updated"

echo "[2/5] Cloning AETHER-SCRAMBLER..."
INSTALL_DIR="/opt/aether-scrambler"
if [ -d "$INSTALL_DIR" ]; then
  cd "$INSTALL_DIR" && git pull origin main
else
  git clone https://github.com/DBarr3/AETHER-SCRAMBLER.git "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
echo "[OK] Cloned"

echo "[3/5] Python venv..."
cd "$INSTALL_DIR"
test -d venv || python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel -q
test -f requirements.txt && pip install -r requirements.txt -q || pip install -e . -q
deactivate
echo "[OK] Deps installed"

echo "[4/5] Writing .env..."
printf 'AETHER_NODE_TYPE=dark\nAETHER_BIND_HOST=0.0.0.0\nAETHER_BIND_PORT=8077\nAETHER_NODE_ID=vps3-dark\n' > "$INSTALL_DIR/.env"
echo "[OK] .env written"

echo "[5/5] Creating systemd service..."
printf '[Unit]\nDescription=AETHER-SCRAMBLER Dark Node\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory=/opt/aether-scrambler\nEnvironment=PATH=/opt/aether-scrambler/venv/bin:/usr/bin:/bin\nEnvironmentFile=-/opt/aether-scrambler/.env\nExecStart=/opt/aether-scrambler/venv/bin/python -m scrambler.terminal_ui.server --host 0.0.0.0 --port 8077\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n' > /etc/systemd/system/aether-scrambler.service
systemctl daemon-reload
systemctl enable aether-scrambler
systemctl restart aether-scrambler
sleep 2
systemctl is-active --quiet aether-scrambler && echo "[OK] Service running" || echo "[WARN] Check: journalctl -u aether-scrambler -n 20"

command -v ufw >/dev/null 2>&1 && ufw status | grep -q active && ufw allow 8077/tcp && ufw allow 22/tcp || true

echo ""
echo "======================================="
echo "  VPS3 DARK NODE DEPLOYMENT COMPLETE"
echo "======================================="
systemctl is-active aether-scrambler && echo "  [OK] aether-scrambler" || echo "  [FAIL] aether-scrambler"
ss -tlnp | grep :8077 || true
echo ""
echo "Test: curl http://localhost:8077/api/status"
echo "External: curl http://161.35.109.243:8077/api/status"
