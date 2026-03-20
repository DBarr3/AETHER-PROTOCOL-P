/**
 * AetherCloud-L Desktop — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * Flow: installer.html → login.html → app.html
 * Backend runs on VPS2 at 198.211.115.41:8742 — no local Python spawn.
 * Each page transition uses IPC so the main process controls window
 * geometry, frameless chrome, and secure context isolation.
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path  = require('path');
const fs    = require('fs');

const keyManager = require('./key-manager');

// ── State ────────────────────────────────────────────
const PAGES_DIR    = path.join(__dirname, 'pages');
const PROJECT_ROOT = path.join(__dirname, '..');
const INSTALL_FLAG = path.join(app.getPath('userData'), '.installed');
const isDev        = process.argv.includes('--dev');
const API_BASE     = 'http://198.211.115.41:8742';

let mainWindow     = null;
let appQuitting    = false;

// ── Window geometry per page ─────────────────────────
const WINDOW_CONFIGS = {
  installer: { width: 640,  height: 480,  resizable: false },
  login:     { width: 480,  height: 620,  resizable: false },
  app:       { width: 1280, height: 800,  resizable: true,  minWidth: 960, minHeight: 640 },
};

// ── Helpers ──────────────────────────────────────────
function pagePath(name) {
  return path.join(PAGES_DIR, `${name}.html`);
}

function isInstalled() {
  return fs.existsSync(INSTALL_FLAG);
}

function markInstalled() {
  fs.mkdirSync(path.dirname(INSTALL_FLAG), { recursive: true });
  fs.writeFileSync(INSTALL_FLAG, JSON.stringify({
    installed_at: new Date().toISOString(),
    version: app.getVersion(),
  }));
}

// ═══════════════════════════════════════════════════
// VPS BACKEND CHECK
// ═══════════════════════════════════════════════════

/**
 * Check if VPS backend is reachable.
 * Returns a promise that resolves when server responds,
 * or resolves true after timeout (show app anyway).
 */
async function waitForBackend() {
  const http = require('http');
  for (let i = 0; i < 10; i++) {
    try {
      const ok = await new Promise((resolve, reject) => {
        const req = http.get(`${API_BASE}/status`, (res) => {
          let body = '';
          res.on('data', (chunk) => { body += chunk; });
          res.on('end', () => {
            try {
              const data = JSON.parse(body);
              console.log(`[VPS] Backend ready — Protocol-L: ${data.protocol_l}, Agent: ${data.agent}`);
              resolve(true);
            } catch (e) {
              resolve(false);
            }
          });
        });
        req.on('error', () => resolve(false));
        req.setTimeout(2000, () => { req.destroy(); resolve(false); });
      });
      if (ok) {
        console.log('[VPS] Backend ready');
        return true;
      }
    } catch (e) {
      console.log(`[VPS] Waiting for backend... attempt ${i + 1}`);
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  console.warn('[VPS] Backend timeout — showing app anyway');
  return true;
}

// ═══════════════════════════════════════════════════
// WINDOW MANAGEMENT
// ═══════════════════════════════════════════════════
function createWindow(page) {
  const cfg = WINDOW_CONFIGS[page] || WINDOW_CONFIGS.app;

  if (mainWindow) {
    // Resize existing window for the new page
    mainWindow.setResizable(true);
    mainWindow.setSize(cfg.width, cfg.height, true);
    mainWindow.center();
    mainWindow.setResizable(cfg.resizable !== false);
    if (cfg.minWidth) {
      mainWindow.setMinimumSize(cfg.minWidth, cfg.minHeight);
    } else {
      mainWindow.setMinimumSize(cfg.width, cfg.height);
    }
    mainWindow.loadFile(pagePath(page));
    return;
  }

  mainWindow = new BrowserWindow({
    width:  cfg.width,
    height: cfg.height,
    resizable: cfg.resizable !== false,
    minWidth:  cfg.minWidth  || cfg.width,
    minHeight: cfg.minHeight || cfg.height,
    frame: false,                     // Frameless — custom title bar
    titleBarStyle: 'hidden',
    backgroundColor: '#010409',       // --void
    show: false,
    webPreferences: {
      preload:            path.join(__dirname, 'preload.js'),
      contextIsolation:   true,
      nodeIntegration:    false,
      sandbox:            false,       // Disabled so preload can use fetch
      devTools:           isDev,
    },
    icon: path.join(__dirname, 'assets', 'icon.png'),
  });

  mainWindow.loadFile(pagePath(page));
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.center();
  });

  if (isDev) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ═══════════════════════════════════════════════════
// IPC HANDLERS
// ═══════════════════════════════════════════════════

// Navigation between pages
ipcMain.on('navigate', (_event, page) => {
  if (['installer', 'login', 'app'].includes(page)) {
    if (page === 'app' && !isInstalled()) {
      markInstalled();
    }
    createWindow(page);
  }
});

// Window controls (frameless)
ipcMain.on('window:minimize', () => mainWindow?.minimize());
ipcMain.on('window:maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on('window:close', () => mainWindow?.close());

// Browse folder dialog (installer location picker)
ipcMain.handle('dialog:openDirectory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

// Open external links
ipcMain.on('shell:openExternal', (_event, url) => {
  shell.openExternal(url);
});

// Get app version
ipcMain.handle('app:version', () => app.getVersion());

// Get install status
ipcMain.handle('app:isInstalled', () => isInstalled());

// ── Filesystem permission dialog (installer) ──
ipcMain.handle('request-fs-permission', async () => {
  const Store = require('electron-store');
  const store = new Store();

  // Skip if already granted
  if (store.get('fs_permission_granted')) return true;

  const result = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: 'AetherCloud-L — File Access',
    message: 'Allow AetherCloud-L to access your files?',
    detail: 'AetherCloud-L needs permission to view and organize files in your selected vault folder. Your files never leave your machine.\n\nAll file access is logged to a tamper-proof audit trail secured by Protocol-L.',
    buttons: ['Allow Access', 'Cancel'],
    defaultId: 0,
    cancelId: 1,
    noLink: true
  });

  const granted = result.response === 0;
  if (granted) {
    store.set('fs_permission_granted', true);
    store.set('fs_permission_date', new Date().toISOString());
  }
  return granted;
});

// ── File access permission (one-time after install) ──
const VAULT_PATH_FLAG = path.join(app.getPath('userData'), '.vault_path');

function getStoredVaultPath() {
  try {
    if (fs.existsSync(VAULT_PATH_FLAG)) {
      return JSON.parse(fs.readFileSync(VAULT_PATH_FLAG, 'utf-8')).path;
    }
  } catch { /* not set yet */ }
  return null;
}

function storeVaultPath(vaultPath) {
  fs.writeFileSync(VAULT_PATH_FLAG, JSON.stringify({
    path: vaultPath,
    granted_at: new Date().toISOString(),
  }));
}

ipcMain.handle('vault:hasAccess', () => {
  return !!getStoredVaultPath();
});

ipcMain.handle('vault:getPath', () => {
  return getStoredVaultPath();
});

ipcMain.handle('vault:requestAccess', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'AetherCloud-L — Select Vault Folder',
    message: 'Choose the folder AetherCloud will monitor and protect.',
    properties: ['openDirectory', 'createDirectory'],
    buttonLabel: 'Grant Access',
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const selectedPath = result.filePaths[0];
  storeVaultPath(selectedPath);
  // Set env var so Python backend picks it up
  process.env.AETHER_VAULT_ROOT = selectedPath;
  return selectedPath;
});

// Browse folder dialog (connect vault)
ipcMain.handle('browse-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select Vault Root',
    properties: ['openDirectory'],
    buttonLabel: 'Connect Vault',
  });
  return result.canceled ? null : result.filePaths[0];
});

// Open a real file
ipcMain.handle('open-file', async (_event, filePath) => {
  try {
    await shell.openPath(filePath);
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
});

// Show file in Windows Explorer
ipcMain.handle('show-in-explorer', async (_event, filePath) => {
  shell.showItemInFolder(filePath);
  return { success: true };
});

// Get API base URL
ipcMain.handle('api:getBase', () => API_BASE);

// Check if VPS backend is ready
ipcMain.handle('api:isReady', async () => {
  try {
    return await waitForBackend();
  } catch {
    return false;
  }
});

// ═══════════════════════════════════════════════════
// KEY MANAGEMENT IPC HANDLERS
// ═══════════════════════════════════════════════════

// Store a key securely
ipcMain.handle('keys:set', (_event, name, value) => {
  return keyManager.setKey(name, value);
});

// Check if a key exists
ipcMain.handle('keys:has', (_event, name) => {
  return keyManager.hasKey(name);
});

// Remove a key
ipcMain.handle('keys:delete', (_event, name) => {
  return keyManager.deleteKey(name);
});

// Validate which keys are configured
ipcMain.handle('keys:validate', () => {
  return keyManager.validate();
});

// ═══════════════════════════════════════════════════
// APP LIFECYCLE
// ═══════════════════════════════════════════════════
app.whenReady().then(async () => {
  // Hydrate keys from secure store into env and filesystem
  keyManager.hydrate();

  // Skip installer if already installed
  const startPage = isInstalled() ? 'login' : 'installer';
  createWindow(startPage);

  // Check VPS backend (non-blocking — window shows immediately)
  try {
    await waitForBackend();
    console.log('[Electron] VPS backend ready');
  } catch (e) {
    console.warn('[Electron] VPS backend not reachable:', e.message);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow(isInstalled() ? 'login' : 'installer');
    }
  });
});

app.on('before-quit', () => {
  appQuitting = true;
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// Security: prevent new windows / navigation to external URLs
app.on('web-contents-created', (_event, contents) => {
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) {
      event.preventDefault();
    }
  });
});
