/**
 * AetherCloud-L v0.8.5 — Preload (context bridge)
 * Aether Systems LLC · Patent Pending
 *
 * Two bridges:
 *   window.aether    — Electron IPC (navigation, window controls, keys)
 *   window.aetherAPI — VPS2 backend HTTP client
 */

const { contextBridge, ipcRenderer } = require('electron');

// ═══════════════════════════════════════════════════
// ELECTRON IPC BRIDGE
// ═══════════════════════════════════════════════════
contextBridge.exposeInMainWorld('aether', {
  navigate:     (page) => ipcRenderer.send('navigate', page),
  minimize:     () => ipcRenderer.send('window:minimize'),
  maximize:     () => ipcRenderer.send('window:maximize'),
  close:        () => ipcRenderer.send('window:close'),
  openDirectory: () => ipcRenderer.invoke('dialog:openDirectory'),
  browseFolder:  () => ipcRenderer.invoke('browse-folder'),
  getVersion:    () => ipcRenderer.invoke('app:version'),
  getApiBase:    () => ipcRenderer.invoke('api:getBase'),
  isApiReady:    () => ipcRenderer.invoke('api:isReady'),
  openExternal:  (url) => ipcRenderer.send('shell:openExternal', url),
  openFile:      (p) => ipcRenderer.invoke('open-file', p),
  showInExplorer:(p) => ipcRenderer.invoke('show-in-explorer', p),
  requestFsPermission: () => ipcRenderer.invoke('request-fs-permission'),
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
});

// ═══════════════════════════════════════════════════
// VPS2 BACKEND API CLIENT
// ═══════════════════════════════════════════════════
const API_BASE = 'http://198.211.115.41:8743';

async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const token = sessionStorage.getItem('session_token');
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  try {
    const resp = await fetch(url, { ...options, headers });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      return { error: true, status: resp.status, message: body.detail || resp.statusText, ...body };
    }
    return await resp.json();
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
});
