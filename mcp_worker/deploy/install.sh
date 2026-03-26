#!/bin/bash
# ═══════════════════════════════════════════════════
# AETHER MCP WORKER — VPS5 Installation Script
# Run as root on VPS5 (104.248.48.130) after cloning repo.
# ═══════════════════════════════════════════════════
set -e

INSTALL_DIR="/opt/aether-mcp"

echo "═══════════════════════════════════════════════════"
echo "  AETHER MCP WORKER — VPS5 Installation"
echo "═══════════════════════════════════════════════════"

echo "[1/5] Creating directories..."
mkdir -p "$INSTALL_DIR/certs"
mkdir -p "$INSTALL_DIR/data"

echo "[2/5] Setting up Python venv..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/mcp_worker/requirements.txt"

echo "[3/5] Checking .env..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "  ⚠ No .env file. Copy and edit:"
    echo "    cp $INSTALL_DIR/mcp_worker/.env.example $INSTALL_DIR/.env"
    echo "    nano $INSTALL_DIR/.env"
    echo "    chmod 600 $INSTALL_DIR/.env"
    echo "  Then re-run this script."
    exit 1
fi
chmod 600 "$INSTALL_DIR/.env"

echo "[4/5] Installing systemd service..."
cp "$INSTALL_DIR/mcp_worker/deploy/aether-mcp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable aether-mcp

echo "[5/5] Installation complete."
echo ""
echo "Next steps:"
echo "  1. Run: bash $INSTALL_DIR/mcp_worker/deploy/bootstrap_vps5.sh"
echo "  2. Copy VPS5 public key to VPS2"
echo "  3. Copy VPS2 public key to $INSTALL_DIR/certs/VPS2.pub"
echo "  4. Start: systemctl start aether-mcp"
echo "  5. Verify: curl http://localhost:8095/health"
echo "═══════════════════════════════════════════════════"
