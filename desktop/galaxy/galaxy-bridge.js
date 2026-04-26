// galaxy-bridge.js
// Main-process IPC bridge for the Galaxy multi-repo subsystem.
// Wires VectorIndex + AuthScope behind ipcMain.handle channels and
// exposes process.memoryUsage for the renderer-side memory watchdog.
//
// Channel naming matches the project's existing convention:
//   galaxy:vector:*   — VectorIndex methods
//   galaxy:auth:*     — AuthScope methods
//   galaxy:memory:*   — heap / RSS reporting
//   galaxy:repo:*     — repo manifest endpoints (which repos exist on this user's disk)
//
// Install once from main.js inside app.whenReady():
//   const { installGalaxyBridge } = require('./galaxy/galaxy-bridge');
//   installGalaxyBridge(app);

const fs = require('node:fs');
const path = require('node:path');
const { ipcMain } = require('electron');
const { VectorIndex } = require('./vector-index');
const { AuthScope } = require('./auth-scope');

let _installed = false;
let _vector = null;
let _auth = null;
let _dataDir = null;

// Strip the conventional namespace prefix from a repo id to get a friendly
// name. Keeps the id stable for identity, but the renderer shows the name.
//   "demo:trading"        → "trading"
//   "vault:my-project"    → "my-project"
//   "raw-id-no-prefix"    → "raw-id-no-prefix"
function stripIdPrefix(id) {
  if (typeof id !== 'string') return String(id);
  const i = id.indexOf(':');
  return i >= 0 ? id.slice(i + 1) : id;
}

// Longest common directory prefix across a list of POSIX-style paths.
// Walks segment-by-segment so we don't half-truncate a directory name.
function longestCommonDir(paths) {
  if (!paths || paths.length === 0) return null;
  const split = paths.map(p => String(p).split(/[\/\\]/).filter(Boolean));
  const min = Math.min(...split.map(s => s.length));
  const out = [];
  for (let i = 0; i < min - 1; i++) {  // -1: never claim the filename itself
    const seg = split[0][i];
    if (split.every(s => s[i] === seg)) out.push(seg);
    else break;
  }
  return out.length ? out.join('/') : null;
}

function installGalaxyBridge(app) {
  if (_installed) return { vector: _vector, auth: _auth };
  _installed = true;

  _dataDir = path.join(app.getPath('userData'), 'aether-galaxy');
  fs.mkdirSync(_dataDir, { recursive: true });

  _vector = new VectorIndex({ dataDir: _dataDir });
  _auth = new AuthScope({ dataDir: _dataDir });

  // ─── VectorIndex ─────────────────────────────────────────────────
  ipcMain.handle('galaxy:vector:embed', async (_e, text) => {
    const v = await _vector.embed(text);
    // IPC serializes Float32Array as Uint8Array of underlying bytes; convert
    // to a plain array on the wire so the renderer reconstructs cleanly.
    return Array.from(v);
  });
  ipcMain.handle('galaxy:vector:listRepos', async () => _vector.listRepos());
  ipcMain.handle('galaxy:vector:hasRepo', async (_e, repoId) => _vector.hasRepo(repoId));
  ipcMain.handle('galaxy:vector:indexRepo', async (_e, repoId, files) => {
    return _vector.indexRepo(repoId, files);
  });
  ipcMain.handle('galaxy:vector:searchRepo', async (_e, repoId, embedding, k) => {
    const v = embedding instanceof Float32Array
      ? embedding
      : Float32Array.from(embedding || []);
    return _vector.searchRepo(repoId, v, k);
  });
  ipcMain.handle('galaxy:vector:readFileSlice', async (_e, repoId, fileId, maxBytes) => {
    return _vector.readFileSlice(repoId, fileId, maxBytes || 4096);
  });
  ipcMain.handle('galaxy:vector:closeRepo', async (_e, repoId) => {
    _vector.closeRepo(repoId);
    return true;
  });

  // ─── AuthScope ───────────────────────────────────────────────────
  ipcMain.handle('galaxy:auth:canRead', async (_e, agentId, repoId) => {
    return _auth.canRead(agentId, repoId);
  });
  ipcMain.handle('galaxy:auth:grant', async (_e, agentId, repoId) => {
    await _auth.grant(agentId, repoId);
    return true;
  });
  ipcMain.handle('galaxy:auth:revoke', async (_e, agentId, repoId) => {
    await _auth.revoke(agentId, repoId);
    return true;
  });
  ipcMain.handle('galaxy:auth:listAllowed', async (_e, agentId) => {
    return _auth.listAllowed(agentId);
  });
  ipcMain.handle('galaxy:auth:audit', async (_e, entry) => {
    _auth.audit(entry);
    return true;
  });
  ipcMain.handle('galaxy:auth:recentAudit', async (_e, limit) => {
    return _auth.recentAudit(limit);
  });

  // ─── Memory + repo manifest ──────────────────────────────────────
  ipcMain.handle('galaxy:memory:usage', async () => {
    const u = process.memoryUsage();
    return {
      rss: u.rss,
      heapTotal: u.heapTotal,
      heapUsed: u.heapUsed,
      external: u.external,
      arrayBuffers: u.arrayBuffers,
    };
  });

  // List all repo manifests on this user's disk. Renderer uses this on
  // boot to populate the universe star field.
  //
  // Returned shape (Galaxy v6):
  //   { id, name, path?, fileCount, builtAt, lastTouchedAt }
  // - `name` is the human-friendly repo name (id with the optional
  //   "demo:" / "vault:" prefix stripped).
  // - `path` is the project root inferred from meta.path (set by indexRepo
  //   if the indexer included it) or the longest common dir of file paths
  //   in the meta. May be null for legacy manifests.
  // - `lastTouchedAt` is the most recent of `meta.lastTouchedAt` (if the
  //   indexer wrote one) and `meta.builtAt`. Used by the renderer for
  //   recency-glow on the universe sprites.
  ipcMain.handle('galaxy:repo:manifests', async () => {
    const ids = await _vector.listRepos();
    const out = [];
    for (const id of ids) {
      try {
        const metaPath = path.join(_dataDir, `${id.replace(/[^\w.-]+/g, '_')}.meta.json`);
        const meta = JSON.parse(await fs.promises.readFile(metaPath, 'utf8'));
        const files = Array.isArray(meta.files) ? meta.files : [];
        let projectPath = meta.path || null;
        if (!projectPath && files.length > 0) {
          projectPath = longestCommonDir(files.map(f => f.path).filter(Boolean));
        }
        const builtAt = meta.builtAt || 0;
        const lastTouchedAt = Math.max(meta.lastTouchedAt || 0, builtAt);
        out.push({
          id,
          name: stripIdPrefix(id),
          path: projectPath || null,
          fileCount: files.length,
          builtAt,
          lastTouchedAt,
        });
      } catch { /* skip malformed */ }
    }
    return out;
  });

  return { vector: _vector, auth: _auth };
}

module.exports = { installGalaxyBridge };
