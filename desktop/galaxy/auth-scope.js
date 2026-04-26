// auth-scope.js
// Per-repo allow/deny gating for agent cross-repo reads.
// Persisted in electron-store under name `aether-galaxy-scope`.
// Audit log appended to userData/aether-galaxy/audit.log (one JSON per line).
//
// Default policy: DENY. An agent must be explicitly granted access to a
// repoId before any read or query against that repo is permitted.

const fs = require('node:fs');
const path = require('node:path');
const Store = require('electron-store');

class AuthScope {
  /**
   * @param {object} opts
   * @param {string} opts.dataDir absolute path under userData (for audit log)
   */
  constructor(opts) {
    if (!opts || !opts.dataDir) throw new Error('AuthScope: dataDir required');
    this.dataDir = opts.dataDir;
    fs.mkdirSync(this.dataDir, { recursive: true });
    this.store = new Store({ name: 'aether-galaxy-scope' });
    this.auditPath = path.join(this.dataDir, 'audit.log');
  }

  // ─── public API ────────────────────────────────────────────────────

  /** Returns true if `agentId` may read `repoId`. */
  async canRead(agentId, repoId) {
    if (!agentId || !repoId) return false;
    const allow = this.store.get(`allow.${agentId}`, []);
    return Array.isArray(allow) && allow.includes(repoId);
  }

  /** Grant `agentId` access to `repoId`. Idempotent. */
  async grant(agentId, repoId) {
    if (!agentId || !repoId) return;
    const cur = this.store.get(`allow.${agentId}`, []);
    if (cur.includes(repoId)) return;
    cur.push(repoId);
    this.store.set(`allow.${agentId}`, cur);
  }

  /** Revoke `agentId`'s access to `repoId`. Idempotent. */
  async revoke(agentId, repoId) {
    if (!agentId || !repoId) return;
    const cur = this.store.get(`allow.${agentId}`, []);
    const next = cur.filter(r => r !== repoId);
    if (next.length === cur.length) return;
    this.store.set(`allow.${agentId}`, next);
  }

  /** All repos an agent may read. */
  async listAllowed(agentId) {
    return this.store.get(`allow.${agentId}`, []);
  }

  /** Append an audit record. Never throws — audit failures must never block reads. */
  audit(entry) {
    try {
      const line = JSON.stringify({ ts: Date.now(), ...entry }) + '\n';
      fs.appendFileSync(this.auditPath, line, 'utf8');
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('[AuthScope] audit append failed:', e && e.message);
    }
  }

  /** Recent audit lines (newest first). For the user-facing access log UI. */
  async recentAudit(limit) {
    if (!fs.existsSync(this.auditPath)) return [];
    const txt = await fs.promises.readFile(this.auditPath, 'utf8');
    const lines = txt.split('\n').filter(Boolean);
    const tail = lines.slice(-Math.max(1, limit || 200));
    const out = [];
    for (let i = tail.length - 1; i >= 0; i--) {
      try { out.push(JSON.parse(tail[i])); } catch { /* skip malformed */ }
    }
    return out;
  }
}

module.exports = { AuthScope };
