#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AETHER DARK NODE — VPS2 Lockdown
# Server:  198.211.115.41
# Purpose: Remove all public access to VPS2. After this runs,
#          VPS2 accepts ONLY WireGuard traffic from VPS3 (10.8.0.3).
#          Port 8080 is firewalled from the entire internet.
#
# WARNING: Run mesh-link.sh FIRST. If WireGuard is not working
#          before you run this, you will lose access to VPS2 API.
#
# REQUIRES: vps2-wg.sh + mesh-link.sh completed + verified
# RUN ON:   ssh root@198.211.115.41
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[VPS2-LOCK]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}       $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}     $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}     $1"; exit 1; }

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${RED}AETHER DARK NODE — VPS2 LOCKDOWN${NC}"
echo "  WARNING: This closes all public access to :8080"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Pre-flight: verify WireGuard + VPS3 reachable ────
info "Pre-flight: verifying WireGuard mesh..."
ip addr show wg0 &>/dev/null || fail "wg0 not up — run vps2-wg.sh and mesh-link.sh first"
ping -c 2 -W 5 10.8.0.3 > /dev/null 2>&1 || fail "Cannot ping VPS3 (10.8.0.3) — do NOT lockdown until mesh is verified"
ok "WireGuard mesh verified — VPS3 reachable at 10.8.0.3"

# ── Pre-flight: verify FastAPI is running ─────────────
info "Pre-flight: verifying FastAPI is running..."
curl -sf http://127.0.0.1:8080/health > /dev/null 2>&1 || warn "FastAPI not responding on localhost:8080 — check service"

# ── UFW lockdown ──────────────────────────────────────
info "Applying UFW lockdown rules..."
apt-get install -y -qq ufw

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# SSH — always keep open
ufw allow 22/tcp comment "SSH"

# WireGuard — must stay open for the mesh
ufw allow 51820/udp comment "WireGuard data plane"

# FastAPI — ONLY accept from VPS3 WireGuard IP
ufw allow from 10.8.0.3 to any port 8080 proto tcp comment "VPS3 relay only"

# Explicitly deny 8080 from everywhere else
ufw deny 8080/tcp comment "Block all public API access"

# Enable UFW
ufw --force enable
ok "UFW lockdown applied"

# ── Update FastAPI bind address ───────────────────────
# FastAPI should listen on WG interface + localhost only
# Find the service file and update bind address
info "Checking FastAPI bind configuration..."
FASTAPI_SERVICE=$(systemctl list-units --type=service --state=running | grep -iE "aether|fastapi|api" | awk '{print $1}' | head -1)

if [ -n "${FASTAPI_SERVICE}" ]; then
  SERVICE_FILE=$(systemctl show "${FASTAPI_SERVICE}" -p FragmentPath | cut -d= -f2)
  if grep -q "0.0.0.0" "${SERVICE_FILE}" 2>/dev/null; then
    warn "FastAPI binding to 0.0.0.0 — UFW will enforce access control"
    info "Optionally update ExecStart to bind 10.8.0.2:8080 for defense in depth"
  fi
fi

# ── Verify lockdown ───────────────────────────────────
echo ""
info "Verifying lockdown state..."
ufw status verbose

echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}VPS2 LOCKDOWN COMPLETE${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  VPS2 is now dark to the public internet."
echo "  Port 8080 accepts ONLY from 10.8.0.3 (VPS3 WG IP)"
echo ""
echo "  Verify from VPS3 (should work):"
echo "    curl http://10.8.0.2:8080/health"
echo ""
echo "  Verify from internet (should FAIL/timeout):"
echo "    curl http://198.211.115.41:8080/health"
echo ""
echo "  CRITICAL: Keep your Tailscale connection live for SSH fallback."
echo ""
