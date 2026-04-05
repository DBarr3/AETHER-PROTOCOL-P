#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Aether VPS2 Backup Script
# Backs up critical data to VPS5 over Tailscale daily.
#
# What gets backed up:
#   - config/credentials.json   (user password hashes)
#   - data/audit/               (audit logs)
#   - vault_data/               (user vault files)
#   - /etc/aethercloud/.env     (environment config, secrets excluded)
#
# Schedule: daily at 2am via /etc/cron.d/aether-backup
# Retention: last 7 daily backups kept on VPS5
#
# Run manually:
#   bash /opt/aether-cloud/scripts/backup.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────
APP_DIR="/opt/aether-cloud"
BACKUP_DEST="root@100.84.205.12:/opt/aether-mcp/data/backups/vps2"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="vps2_backup_${TIMESTAMP}"
TMP_DIR="/tmp/${BACKUP_NAME}"
LOG_FILE="/var/log/aether-backup.log"
RETENTION_DAYS=7

# Load env if available
if [ -f /etc/aethercloud/.env ]; then
  set -a && . /etc/aethercloud/.env && set +a
fi

# ── Logging ───────────────────────────────────────────────────────
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [BACKUP] $1" | tee -a "$LOG_FILE"; }

log "Starting backup: ${BACKUP_NAME}"

# ── Create temp staging dir ───────────────────────────────────────
mkdir -p "${TMP_DIR}"

# ── Copy critical files ───────────────────────────────────────────
# Credentials (password hashes)
if [ -f "${APP_DIR}/config/credentials.json" ]; then
  mkdir -p "${TMP_DIR}/config"
  cp "${APP_DIR}/config/credentials.json" "${TMP_DIR}/config/"
  log "Copied credentials.json"
fi

# Audit logs
if [ -d "${APP_DIR}/data/audit" ]; then
  cp -r "${APP_DIR}/data/audit" "${TMP_DIR}/"
  log "Copied audit logs"
fi

# Vault data
if [ -d "${APP_DIR}/vault_data" ]; then
  cp -r "${APP_DIR}/vault_data" "${TMP_DIR}/"
  log "Copied vault_data"
fi

# Env file — strip secrets before backup
if [ -f /etc/aethercloud/.env ]; then
  mkdir -p "${TMP_DIR}/config"
  # Remove sensitive keys — keep structure only
  grep -v -E 'ANTHROPIC_API_KEY|AETHER_ADMIN_KEY|AETHER_DEV_KEY|MCP_ALERT_KEY|GITHUB_WEBHOOK_SECRET' \
    /etc/aethercloud/.env > "${TMP_DIR}/config/env.redacted" || true
  log "Copied redacted env config"
fi

# ── Create tarball ────────────────────────────────────────────────
TARBALL="/tmp/${BACKUP_NAME}.tar.gz"
tar -czf "${TARBALL}" -C /tmp "${BACKUP_NAME}"
SIZE=$(du -sh "${TARBALL}" | cut -f1)
log "Created tarball: ${TARBALL} (${SIZE})"

# ── Transfer to VPS5 over Tailscale ──────────────────────────────
log "Transferring to VPS5..."
ssh -i /root/.ssh/deploy_key -o StrictHostKeyChecking=no \
  root@100.84.205.12 "mkdir -p /opt/aether-mcp/data/backups/vps2"

scp -i /root/.ssh/deploy_key -o StrictHostKeyChecking=no \
  "${TARBALL}" "${BACKUP_DEST}/"

log "Transfer complete"

# ── Enforce retention on VPS5 ────────────────────────────────────
log "Enforcing ${RETENTION_DAYS}-day retention on VPS5..."
ssh -i /root/.ssh/deploy_key -o StrictHostKeyChecking=no \
  root@100.84.205.12 \
  "find /opt/aether-mcp/data/backups/vps2 -name 'vps2_backup_*.tar.gz' \
   -mtime +${RETENTION_DAYS} -delete && \
   echo 'Retention cleanup done' && \
   ls /opt/aether-mcp/data/backups/vps2/ | wc -l | xargs echo 'Backups on VPS5:'"

# ── Cleanup local temp files ──────────────────────────────────────
rm -rf "${TMP_DIR}" "${TARBALL}"
log "Cleanup done"

log "Backup complete: ${BACKUP_NAME}"
