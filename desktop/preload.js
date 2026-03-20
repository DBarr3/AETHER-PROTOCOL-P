/**
 * AetherCloud-L Desktop — Preload (context bridge)
 * Exposes a minimal, secure API to renderer pages.
 *
 * Two bridges:
 *   window.aether    — Electron IPC (navigation, window controls, key management)
 *   window.aetherAPI — Python backend HTTP API on localhost:8741
 */

const { contextBridge, ipcRenderer } = require('electron');

// ═══════════════════════════════════════════════════
// ELECTRON IPC BRIDGE
// ═══════════════════════════════════════════════════
contextBridge.exposeInMainWorld('aether', {
  // ── Navigation ─────────────────────────────────────
  navigate: (page) => ipcRenderer.send('navigate', page),

  // ── Window controls ────────────────────────────────
  minimize:   () => ipcRenderer.send('window:minimize'),
  maximize:   () => ipcRenderer.send('window:maximize'),
  close:      () => ipcRenderer.send('window:close'),

  // ── Dialogs ────────────────────────────────────────
  openDirectory: () => ipcRenderer.invoke('dialog:openDirectory'),
  browseFolder:  () => ipcRenderer.invoke('browse-folder'),

  // ── App info ───────────────────────────────────────
  getVersion:    () => ipcRenderer.invoke('app:version'),
  isInstalled:   () => ipcRenderer.invoke('app:isInstalled'),

  // ── Shell ──────────────────────────────────────────
  openExternal: (url) => ipcRenderer.send('shell:openExternal', url),

  // ── API ────────────────────────────────────────────
  getApiBase:    () => ipcRenderer.invoke('api:getBase'),
  isApiReady:    () => ipcRenderer.invoke('api:isReady'),

  // ── Key Management ─────────────────────────────────
  keys: {
    set:      (name, value) => ipcRenderer.invoke('keys:set', name, value),
    has:      (name)        => ipcRenderer.invoke('keys:has', name),
    delete:   (name)        => ipcRenderer.invoke('keys:delete', name),
    validate: ()            => ipcRenderer.invoke('keys:validate'),
  },

  // ── Vault Access ──────────────────────────────────
  vault: {
    hasAccess:     () => ipcRenderer.invoke('vault:hasAccess'),
    getPath:       () => ipcRenderer.invoke('vault:getPath'),
    requestAccess: () => ipcRenderer.invoke('vault:requestAccess'),
  },

  // ── Filesystem Permission ───────────────────────
  requestFsPermission: () => ipcRenderer.invoke('request-fs-permission'),

  // ── File Actions ────────────────────────────────
  openFile: (filePath) => ipcRenderer.invoke('open-file', filePath),
  showInExplorer: (filePath) => ipcRenderer.invoke('show-in-explorer', filePath),
});

// ═══════════════════════════════════════════════════
// PYTHON BACKEND API CLIENT
// ═══════════════════════════════════════════════════
const API_BASE = 'http://127.0.0.1:8741';

/**
 * Internal fetch wrapper with error handling.
 */
async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return await response.json();
  } catch (err) {
    // Return structured error so renderer can handle gracefully
    return { error: true, message: err.message, endpoint };
  }
}

/**
 * Build Authorization header from session token.
 */
function authHeader(sessionToken) {
  return { Authorization: `Bearer ${sessionToken}` };
}

contextBridge.exposeInMainWorld('aetherAPI', {

  // ── Auth ───────────────────────────────────────────
  async login(username, password) {
    return apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },

  async logout(sessionToken) {
    return apiFetch('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ session_token: sessionToken }),
    });
  },

  // ── Vault ──────────────────────────────────────────
  async listVault(sessionToken) {
    return apiFetch('/vault/list', {
      headers: authHeader(sessionToken),
    });
  },

  // ── Agent ──────────────────────────────────────────
  async chat(query, sessionToken) {
    return apiFetch('/agent/chat', {
      method: 'POST',
      headers: authHeader(sessionToken),
      body: JSON.stringify({ query }),
    });
  },

  async analyze(filename, extension, directory, sessionToken) {
    return apiFetch('/agent/analyze', {
      method: 'POST',
      headers: authHeader(sessionToken),
      body: JSON.stringify({ filename, extension, directory }),
    });
  },

  async scan(sessionToken) {
    return apiFetch('/agent/scan', {
      method: 'POST',
      headers: authHeader(sessionToken),
    });
  },

  // ── Audit ──────────────────────────────────────────
  async getAudit(sessionToken, limit = 50) {
    return apiFetch(`/audit/trail?limit=${limit}`, {
      headers: authHeader(sessionToken),
    });
  },

  // ── Status ─────────────────────────────────────────
  async getStatus() {
    return apiFetch('/status');
  },

  // ── Vault Scan ──────────────────────────────────
  async scanVault(vaultPath, sessionToken) {
    try {
      const response = await fetch(`${API_BASE}/vault/scan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${sessionToken}`,
        },
        body: JSON.stringify({ vault_path: vaultPath }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Scan failed');
      }
      return await response.json();
    } catch (e) {
      console.warn('vault scan failed:', e);
      return null;
    }
  },
});
