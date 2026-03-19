/**
 * AetherCloud-L Desktop — Preload (context bridge)
 * Exposes a minimal, secure API to renderer pages.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aether', {
  // ── Navigation ─────────────────────────────────────
  navigate: (page) => ipcRenderer.send('navigate', page),

  // ── Window controls ────────────────────────────────
  minimize:   () => ipcRenderer.send('window:minimize'),
  maximize:   () => ipcRenderer.send('window:maximize'),
  close:      () => ipcRenderer.send('window:close'),

  // ── Dialogs ────────────────────────────────────────
  openDirectory: () => ipcRenderer.invoke('dialog:openDirectory'),

  // ── App info ───────────────────────────────────────
  getVersion:    () => ipcRenderer.invoke('app:version'),
  isInstalled:   () => ipcRenderer.invoke('app:isInstalled'),

  // ── Shell ──────────────────────────────────────────
  openExternal: (url) => ipcRenderer.send('shell:openExternal', url),
});
