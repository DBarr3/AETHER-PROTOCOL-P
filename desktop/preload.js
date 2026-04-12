/**
 * AetherCloud-L v0.9.3 — Preload (context bridge)
 * Aether Systems LLC · Patent Pending
 *
 * Two bridges:
 *   window.aether    — Electron IPC (navigation, window controls, keys)
 *   window.aetherAPI — VPS HTTP client (routes through VPS1 Ghost Proxy)
 */

const { contextBridge, ipcRenderer } = require('electron');

// ═══════════════════════════════════════════════════
// ELECTRON IPC BRIDGE
// ═══════════════════════════════════════════════════
contextBridge.exposeInMainWorld('aether', {
  apiBase: 'https://api.aethersystems.net/cloud',
  navigate:     (page) => ipcRenderer.send('navigate', page),
  minimize:     () => ipcRenderer.send('window:minimize'),
  maximize:     () => ipcRenderer.send('window:maximize'),
  close:        () => ipcRenderer.send('window:close'),
  openDirectory: () => ipcRenderer.invoke('dialog:openDirectory'),
  browseFolder:  () => ipcRenderer.invoke('browse-folder'),
  getVersion:    () => ipcRenderer.invoke('app:version'),
  getUpdateInfo: () => ipcRenderer.invoke('app:updateInfo'),
  openDownload:  () => ipcRenderer.invoke('app:openDownload'),
  getApiBase:    () => ipcRenderer.invoke('api:getBase'),
  isApiReady:    () => ipcRenderer.invoke('api:isReady'),
  openExternal:  (url) => ipcRenderer.send('shell:openExternal', url),
  openFile:      (p) => ipcRenderer.invoke('open-file', p),
  showInExplorer:(p) => ipcRenderer.invoke('show-in-explorer', p),
  requestFsPermission: () => ipcRenderer.invoke('request-fs-permission'),
  scanDirectory:  (dirPath, depth) => ipcRenderer.invoke('scan-directory', dirPath, depth || 2),
  readFilePreview: (filePath, maxLines) => ipcRenderer.invoke('read-file-preview', filePath, maxLines || 80),
  readDirectoryContext: (dirPath, maxFiles) => ipcRenderer.invoke('read-directory-context', dirPath, maxFiles || 20),
  keys: {
    set:      (name, value) => ipcRenderer.invoke('keys:set', name, value),
    has:      (name)        => ipcRenderer.invoke('keys:has', name),
    delete:   (name)        => ipcRenderer.invoke('keys:delete', name),
    validate: ()            => ipcRenderer.invoke('keys:validate'),
  },
  vault: {
    hasAccess:     () => ipcRenderer.invoke('vault:hasAccess'),
    getPath:       () => ipcRenderer.invoke('vault:getPath'),
    requestAccess: () => ipcRenderer.invoke('vault:requestAccess'),
  },
  cache: {
    get:   (dirPath) => ipcRenderer.invoke('cache:get', dirPath),
    set:   (dirPath, entry) => ipcRenderer.invoke('cache:set', dirPath, entry),
    list:  () => ipcRenderer.invoke('cache:list'),
    clear: (dirPath) => ipcRenderer.invoke('cache:clear', dirPath),
  },
  // Local file plan execution — runs agent action plans on the user's machine
  execPlan:    (actions) => ipcRenderer.invoke('fs:execPlan', actions),
  previewPlan: (actions) => ipcRenderer.invoke('fs:previewPlan', actions),
  // Agent Profile System
  agentLoadIcons:    () => ipcRenderer.invoke('agent:loadIcons'),
  agentLoadProfiles: () => ipcRenderer.invoke('agent:loadProfiles'),
  agentSaveProfile:  (profile) => ipcRenderer.invoke('agent:saveProfile', profile),
  agentDeleteProfile:(id) => ipcRenderer.invoke('agent:deleteProfile', id),
  // Tool Registry
  agentLoadToolRegistry:  () => ipcRenderer.invoke('agent:loadToolRegistry'),
  agentSaveToolRegistry:  (reg) => ipcRenderer.invoke('agent:saveToolRegistry', reg),
  // Terminal Windows
  terminalOpen:     (config) => ipcRenderer.invoke('terminal:open', config),
  terminalInit:     (cb) => ipcRenderer.on('terminal:init', (_e, config) => cb(config)),
  terminalMinimize: () => ipcRenderer.send('terminal:minimize'),
  terminalMaximize: () => ipcRenderer.send('terminal:maximize'),
  terminalClose:    () => ipcRenderer.send('terminal:close'),
});

// ═══════════════════════════════════════════════════
// VPS BACKEND API CLIENT (via VPS1 HTTPS proxy)
// ═══════════════════════════════════════════════════
const API_BASE = 'https://api.aethersystems.net/cloud';

// In-memory token cache — populated from electron-store on first call.
// We intentionally do NOT cache in localStorage: localStorage is accessible to
// all page JS (XSS risk). The encrypted electron-store is the single source
// of truth; memory cache avoids repeated IPC for every apiFetch call.
let _cachedToken = null;
let _tokenSetAt = null;
const SESSION_TIMEOUT_MS = 8 * 60 * 60 * 1000;     // 8 hours (match backend)
const SESSION_REFRESH_MS = 7.5 * 60 * 60 * 1000;   // refresh at 7.5h (30 min before expiry)

async function _resolveToken() {
  if (_cachedToken) return _cachedToken;
  try {
    const auth = await ipcRenderer.invoke('auth:get');
    if (auth && auth.sessionToken) {
      _cachedToken = auth.sessionToken;
      _tokenSetAt = Date.now();
      return auth.sessionToken;
    }
  } catch (_) { /* electron-store unavailable */ }
  return null;
}

// Proactively refresh the session token 30 minutes before it expires.
// Called once after login and again after each successful refresh.
async function _scheduleTokenRefresh() {
  const delay = SESSION_REFRESH_MS;
  setTimeout(async () => {
    try {
      const token = _cachedToken;
      if (!token) return;
      const resp = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.session_token) {
          _cachedToken = data.session_token;
          _tokenSetAt = Date.now();
          try {
            const auth = await ipcRenderer.invoke('auth:get');
            if (auth?.rememberMe) {
              await ipcRenderer.invoke('auth:set', { sessionToken: data.session_token });
            }
          } catch (_) {}
          _scheduleTokenRefresh();  // schedule next refresh
        }
      }
    } catch (_) { /* network error — let session expire naturally */ }
  }, delay);
}

async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };

  // Only resolve token if the caller didn't already provide Authorization
  if (!headers['Authorization'] && !headers['authorization']) {
    const token = await _resolveToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    let resp = await fetch(url, { ...options, headers });

    // On 401: clear cached token and redirect to login (never store/replay passwords)
    if (resp.status === 401 && !endpoint.includes('/auth/login')) {
      console.warn('[apiFetch] 401 — session expired, redirecting to login');
      _cachedToken = null;
      try {
        // Clear stored session token so restore attempt doesn't loop
        await ipcRenderer.invoke('auth:set', { sessionToken: null });
      } catch (_) { /* ignore */ }
      ipcRenderer.send('navigate', 'login');
    }

    if (!resp.ok) {
      const text = await resp.text().catch(() => '');
      let body = {};
      try { body = JSON.parse(text); } catch {
        // nginx returned HTML instead of JSON (502/504 gateway error)
        if (text.includes('<html') || text.includes('<!DOCTYPE')) {
          return { error: true, status: resp.status, message: `Backend unreachable (${resp.status}). Server may be restarting.` };
        }
        return { error: true, status: resp.status, message: text.substring(0, 200) || resp.statusText };
      }
      return { error: true, status: resp.status, message: body.detail || resp.statusText, ...body };
    }
    const text = await resp.text();
    try { return JSON.parse(text); } catch {
      return { error: true, message: `Invalid JSON response: ${text.substring(0, 120)}` };
    }
  } catch (err) {
    return { error: true, message: err.message };
  }
}

contextBridge.exposeInMainWorld('aetherAPI', {
  getStatus: () => apiFetch('/status'),

  login: async (username, password, licenseKey) => {
    const body = { username, password };
    if (licenseKey) body.license_key = licenseKey;
    const result = await apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    // Schedule proactive token refresh after successful login
    if (result && result.authenticated && result.session_token) {
      _cachedToken = result.session_token;
      _tokenSetAt = Date.now();
      _scheduleTokenRefresh();
    }
    return result;
  },

  chat: (query, sessionToken) =>
    apiFetch('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ query }),
      headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
    }),

  analyze: (filePath, sessionToken) =>
    apiFetch('/agent/analyze', {
      method: 'POST',
      body: JSON.stringify({ file_path: filePath }),
      headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
    }),

  setContext: (context, sessionToken) =>
    apiFetch('/agent/context', {
      method: 'POST',
      body: JSON.stringify({ context }),
      headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
    }),

  getContext: (sessionToken) =>
    apiFetch('/agent/context', {
      method: 'GET',
      headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
    }),

  browseVault: (dirPath) =>
    apiFetch(`/vault/browse?path=${encodeURIComponent(dirPath || '')}`),

  scanVault: (rootPath, sessionToken) =>
    apiFetch('/vault/scan', {
      method: 'POST',
      body: JSON.stringify({ root_path: rootPath }),
      headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
    }),

  // ── Admin License Server ──────────────────────
  adminOverview:       () => ipcRenderer.invoke('admin:overview'),
  adminScramblerList:  (params) => ipcRenderer.invoke('admin:scrambler:list', params),
  adminScramblerIssue: (data) => ipcRenderer.invoke('admin:scrambler:issue', data),
  adminScramblerRevoke:(data) => ipcRenderer.invoke('admin:scrambler:revoke', data),
  adminScramblerExtend:(data) => ipcRenderer.invoke('admin:scrambler:extend', data),
  adminCloudList:      (params) => ipcRenderer.invoke('admin:cloud:list', params),
  adminCloudIssue:     (data) => ipcRenderer.invoke('admin:cloud:issue', data),
  adminCloudRevoke:    (data) => ipcRenderer.invoke('admin:cloud:revoke', data),
  adminApiKeyList:     (params) => ipcRenderer.invoke('admin:apikey:list', params),
  adminApiKeyIssue:    (data) => ipcRenderer.invoke('admin:apikey:issue', data),
  adminApiKeyRevoke:   (data) => ipcRenderer.invoke('admin:apikey:revoke', data),

  // ── Auth Persistence ──────────────────────────
  authGet:    () => ipcRenderer.invoke('auth:get'),
  authSet:    (data) => ipcRenderer.invoke('auth:set', data),
  authClear:  () => ipcRenderer.invoke('auth:clear'),
  authClearAll: () => ipcRenderer.invoke('auth:clearAll'),
});
