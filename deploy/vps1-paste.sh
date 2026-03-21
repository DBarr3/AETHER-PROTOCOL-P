#!/usr/bin/env bash
# VPS1 Deploy — paste-safe (no heredocs)
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "[1/7] Updating system..."
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq python3 python3-venv python3-pip python3-dev git curl nginx build-essential libffi-dev libssl-dev
echo "[OK] System updated"

echo "[2/7] Cloning AETHER-SCRAMBLER..."
INSTALL_DIR="/opt/aether-scrambler"
if [ -d "$INSTALL_DIR" ]; then
  cd "$INSTALL_DIR" && git pull origin main
else
  git clone https://github.com/DBarr3/AETHER-SCRAMBLER.git "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi
echo "[OK] Cloned"

echo "[3/7] Python venv..."
cd "$INSTALL_DIR"
test -d venv || python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel -q
test -f requirements.txt && pip install -r requirements.txt -q || pip install -e . -q
deactivate
echo "[OK] Deps installed"

echo "[4/7] Writing .env..."
printf 'AETHER_NODE_TYPE=proxy\nAETHER_BIND_HOST=127.0.0.1\nAETHER_BIND_PORT=8077\n' > "$INSTALL_DIR/.env"
echo "[OK] .env written"

echo "[5/7] Creating systemd service..."
printf '[Unit]\nDescription=AETHER-SCRAMBLER Ghost Protocol\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory=/opt/aether-scrambler\nEnvironment=PATH=/opt/aether-scrambler/venv/bin:/usr/bin:/bin\nEnvironmentFile=-/opt/aether-scrambler/.env\nExecStart=/opt/aether-scrambler/venv/bin/python -m scrambler.terminal_ui.server --host 127.0.0.1 --port 8077\nRestart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n' > /etc/systemd/system/aether-scrambler.service
systemctl daemon-reload
systemctl enable aether-scrambler
systemctl restart aether-scrambler
sleep 2
systemctl is-active --quiet aether-scrambler && echo "[OK] Service running" || echo "[WARN] Check: journalctl -u aether-scrambler -n 20"

echo "[6/7] Configuring Nginx..."
rm -f /etc/nginx/sites-enabled/default
printf 'upstream vps2_backend { server 198.211.115.41:8080; keepalive 16; }\nupstream scrambler_local { server 127.0.0.1:8077; keepalive 8; }\nserver {\n    listen 8080 default_server;\n    listen [::]:8080 default_server;\n    server_name _;\n    add_header Access-Control-Allow-Origin * always;\n    add_header Access-Control-Allow-Methods \"GET, POST, PUT, DELETE, OPTIONS\" always;\n    add_header Access-Control-Allow-Headers \"Authorization, Content-Type\" always;\n    location /terminal { proxy_pass http://scrambler_local/; proxy_http_version 1.1; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; }\n    location /terminal/api/ { proxy_pass http://scrambler_local/api/; proxy_http_version 1.1; proxy_set_header Host $host; }\n    location / { proxy_pass http://vps2_backend; proxy_http_version 1.1; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header Connection \"\"; proxy_read_timeout 120s; }\n    location /nginx-health { access_log off; return 200 \"{\\\"status\\\":\\\"ok\\\",\\\"node\\\":\\\"vps1\\\"}\";\n add_header Content-Type application/json; }\n}\n' > /etc/nginx/sites-available/aether-proxy
ln -sf /etc/nginx/sites-available/aether-proxy /etc/nginx/sites-enabled/aether-proxy
nginx -t && systemctl enable nginx && systemctl restart nginx
echo "[OK] Nginx running"

echo "[7/7] Firewall..."
command -v ufw >/dev/null 2>&1 && ufw status | grep -q active && ufw allow 8080/tcp && ufw allow 22/tcp || true

echo ""
echo "======================================="
echo "  VPS1 DEPLOYMENT COMPLETE"
echo "======================================="
systemctl is-active aether-scrambler && echo "  [OK] aether-scrambler" || echo "  [FAIL] aether-scrambler"
systemctl is-active nginx && echo "  [OK] nginx" || echo "  [FAIL] nginx"
ss -tlnp | grep -E ":(8077|8080)" || true
echo ""
echo "Test: curl http://localhost:8080/nginx-health"
echo "External: curl http://143.198.162.111:8080/nginx-health"
