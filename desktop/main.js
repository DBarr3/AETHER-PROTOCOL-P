/**
 * AetherCloud-L v0.8.7 — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * Fresh minimal launcher: login.html → dashboard.html
 * Backend: VPS2 at 198.211.115.41:8080
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const http = require('http');

const keyManager = require('./key-manager');

// ── Constants ────────────────────────────────────────
const PAGES_DIR = path.join(__dirname, 'pages');
const API_BASE  = 'http://198.211.115.41:8080';

let mainWindow = null;
let appQuitting = false;

// ── Window configs per page ──────────────────────────
const WINDOW_CONFIGS = {
  login:     { width: 480, height: 620, resizable: false },
  dashboard: { width: 1280, height: 820, resizable: true, minWidth: 900, minHeight: 600 },
};

// ── Create window ────────────────────────────────────
function createWindow(page) {
  const cfg = WINDOW_CONFIGS[page] || WINDOW_CONFIGS.login;

  const oldWindow = mainWindow;
  mainWindow = null;

  const win = new BrowserWindow({
    width: cfg.width,
    height: cfg.height,
    minWidth: cfg.minWidth || cfg.width,
    minHeight: cfg.minHeight || cfg.height,
    resizable: cfg.resizable ?? false,
    frame: false,
    transparent: false,
    backgroundColor: '#0a0a0a',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow = win;

  win.loadFile(path.join(PAGES_DIR, `${page}.html`));
  win.once('ready-to-show', () => {
    if (mainWindow === win) win.show();
    // Destroy old window AFTER new one is visible
    if (oldWindow && !oldWindow.isDestroyed()) {
      oldWindow.removeAllListeners('close');
      oldWindow.destroy();
    }
  });

  win.on('close', (e) => {
    if (!appQuitting && mainWindow === win) {
      e.preventDefault();
      win.hide();
    }
  });
}

// ── Wait for VPS backend ─────────────────────────────
function waitForBackend(retries = 10) {
  return new Promise((resolve) => {
    let attempt = 0;
    function check() {
      attempt++;
      const req = http.get(`${API_BASE}/status`, (res) => {
        let body = '';
        res.on('data', (d) => (body += d));
        res.on('end', () => {
          try {
            const data = JSON.parse(body);
            resolve({ ready: true, ...data });
          } catch {
            resolve({ ready: true });
          }
        });
      });
      req.on('error', () => {
        if (attempt < retries) setTimeout(check, 1500);
        else resolve({ ready: false, error: 'VPS unreachable after ' + retries + ' attempts' });
      });
      req.setTimeout(4000, () => {
        req.destroy();
        if (attempt < retries) setTimeout(check, 1500);
        else resolve({ ready: false, error: 'VPS timeout' });
      });
    }
    check();
  });
}

// ── App lifecycle ────────────────────────────────────
app.whenReady().then(() => {
  keyManager.hydrate();
  createWindow('login');
});

app.on('before-quit', () => { appQuitting = true; });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (!mainWindow) createWindow('login'); });

// ── IPC: Navigation ──────────────────────────────────
ipcMain.on('navigate', (_e, page) => {
  const allowed = ['login', 'dashboard'];
  if (allowed.includes(page)) createWindow(page);
});

// ── IPC: Window controls ─────────────────────────────
ipcMain.on('window:minimize', () => mainWindow?.minimize());
ipcMain.on('window:maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on('window:close', () => {
  appQuitting = true;
  mainWindow?.close();
  app.quit();
});

// ── IPC: API ─────────────────────────────────────────
ipcMain.handle('api:getBase', () => API_BASE);
ipcMain.handle('api:isReady', async () => waitForBackend());
ipcMain.handle('app:version', () => app.getVersion());

// ── IPC: Dialogs ─────────────────────────────────────
ipcMain.handle('dialog:openDirectory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('browse-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select folder to connect',
  });
  return result.canceled ? null : result.filePaths[0];
});

// ── IPC: Shell ───────────────────────────────────────
ipcMain.on('shell:openExternal', (_e, url) => shell.openExternal(url));
ipcMain.handle('open-file', async (_e, filePath) => {
  try { await shell.openPath(filePath); return { success: true }; }
  catch (err) { return { success: false, error: err.message }; }
});
ipcMain.handle('show-in-explorer', async (_e, filePath) => {
  shell.showItemInFolder(filePath);
  return { success: true };
});

// ── IPC: Key management ──────────────────────────────
ipcMain.handle('keys:set', (_e, name, value) => keyManager.setKey(name, value));
ipcMain.handle('keys:has', (_e, name) => keyManager.hasKey(name));
ipcMain.handle('keys:delete', (_e, name) => keyManager.deleteKey(name));
ipcMain.handle('keys:validate', () => keyManager.validate());

// ── IPC: Vault ───────────────────────────────────────
ipcMain.handle('vault:hasAccess', () => false);
ipcMain.handle('vault:getPath', () => null);
ipcMain.handle('vault:requestAccess', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Vault Root',
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('request-fs-permission', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Grant filesystem access',
  });
  return result.canceled ? null : result.filePaths[0];
});
