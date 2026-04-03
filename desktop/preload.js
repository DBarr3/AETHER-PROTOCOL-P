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
});

// ═══════════════════════════════════════════════════
// VPS BACKEND API CLIENT (via VPS1 HTTPS proxy)
// ═══════════════════════════════════════════════════
const API_BASE = 'https://api.aethersystems.net/cloud';

// Cache token from electron-store so every apiFetch has it
let _cachedToken = null;
async function _resolveToken() {
  // Prefer localStorage (same-window), fall back to electron-store
  const local = localStorage.getItem('aether_session');
  if (local) return local;
  if (_cachedToken) return _cachedToken;
  try {
    const auth = await ipcRenderer.invoke('auth:get');
    if (auth && auth.sessionToken) {
      _cachedToken = auth.sessionToken;
      localStorage.setItem('aether_session', auth.sessionToken);
      return auth.sessionToken;
    }
  } catch (_) { /* electron-store unavailable */ }
  return null;
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

    // Auto re-login on 401 (server session expired / process restarted)
    if (resp.status === 401 && !endpoint.includes('/auth/login')) {
      console.warn('[apiFetch] 401 received, attempting re-login...');
      try {
        const auth = await ipcRenderer.invoke('auth:get');
        if (auth?.userId && auth?.accessKey) {
          const loginResp = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: auth.userId, password: auth.accessKey }),
          });
          const loginResult = await loginResp.json();
          if (loginResult.authenticated && loginResult.session_token) {
            _cachedToken = loginResult.session_token;
            localStorage.setItem('aether_session', loginResult.session_token);
            await ipcRenderer.invoke('auth:set', { ...auth, sessionToken: loginResult.session_token });
            headers['Authorization'] = `Bearer ${loginResult.session_token}`;
            console.log('[apiFetch] Re-login successful, retrying request...');
            resp = await fetch(url, { ...options, headers });
          }
        }
      } catch (reLoginErr) {
        console.error('[apiFetch] Re-login failed:', reLoginErr.message);
      }
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

  login: (username, password) =>
    apiFetch('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

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
