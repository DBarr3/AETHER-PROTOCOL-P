/**
 * AetherCloud-L v0.8.9 — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * Fresh minimal launcher: login.html → dashboard.html
 * Backend: VPS2 at 198.211.115.41:8080
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const http = require('http');
const fs   = require('fs');

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

// ── Wait for VPS backend (hardened) ──────────────────
async function waitForBackend(maxRetries = 15, delayMs = 2000) {
  const statusUrl = `${API_BASE}/status`;
  console.log(`[AetherCloud] Connecting to backend: ${statusUrl}`);

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const data = await new Promise((resolve, reject) => {
        const req = http.get(statusUrl, (res) => {
          let body = '';
          res.on('data', (d) => (body += d));
          res.on('end', () => {
            try {
              resolve(JSON.parse(body));
            } catch {
              resolve({ ready: true });
            }
          });
        });
        req.on('error', (err) => reject(err));
        req.setTimeout(5000, () => {
          req.destroy();
          reject(new Error('timeout'));
        });
      });

      console.log(`[AetherCloud] Backend connected — Protocol-L: ${data.protocol_l}, Agent: ${data.agent}`);

      if (data.needs_setup) {
        console.warn('[AetherCloud] First-time setup required');
      }

      return { ready: true, ...data };
    } catch (err) {
      const reason = err.message || 'unknown';
      console.log(`[AetherCloud] Attempt ${attempt}/${maxRetries} failed: ${reason}`);
    }

    if (attempt < maxRetries) {
      await new Promise(r => setTimeout(r, delayMs));
    }
  }

  // Show user-friendly error dialog
  const { response } = await dialog.showMessageBox({
    type: 'error',
    title: 'AetherCloud Connection Failed',
    message: 'Cannot reach AetherCloud backend.',
    detail: `Tried ${maxRetries} times to reach ${API_BASE}/status\n\nCheck:\n• VPS1 is running (143.198.162.111)\n• VPS2 backend is active (198.211.115.41:8080)\n• Your internet connection`,
    buttons: ['Retry', 'Quit'],
  });

  if (response === 0) {
    app.relaunch();
    app.exit(0);
  } else {
    app.quit();
  }

  return { ready: false, error: `VPS unreachable after ${maxRetries} attempts` };
}

// ── Verify routing ──────────────────────────────────
async function verifyRouting() {
  try {
    const data = await new Promise((resolve, reject) => {
      const req = http.get(`${API_BASE}/routing-check`, (res) => {
        let body = '';
        res.on('data', (d) => (body += d));
        res.on('end', () => {
          try { resolve(JSON.parse(body)); }
          catch { resolve(null); }
        });
      });
      req.on('error', () => resolve(null));
      req.setTimeout(5000, () => { req.destroy(); resolve(null); });
    });

    if (data) {
      console.log('[AetherCloud] Routing verified:', JSON.stringify(data));
      if (!data.anthropic_key_set) {
        console.error('[AetherCloud] WARNING: ANTHROPIC_API_KEY not set on VPS2');
      }
      if (!data.ibm_token_set) {
        console.warn('[AetherCloud] IBM token not set — quantum fallback active');
      }
    }
    return data;
  } catch (err) {
    console.error('[AetherCloud] Routing check failed:', err.message);
    return null;
  }
}

// ── App lifecycle ────────────────────────────────────
app.whenReady().then(async () => {
  keyManager.hydrate();

  // Test backend connectivity before showing login
  const status = await waitForBackend();
  if (!status.ready) return;

  // Verify routing path
  await verifyRouting();

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
ipcMain.handle('api:isReady', async () => waitForBackend(5, 1500));
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

// ── IPC: Local directory scanner ─────────────────────
// Scans a directory on the local filesystem (no VPS needed).
// Returns { folders: [...], files: [...], path, name }
ipcMain.handle('scan-directory', async (_e, dirPath, maxDepth = 1) => {
  try {
    if (!dirPath || !fs.existsSync(dirPath)) {
      return { error: true, message: 'Path does not exist: ' + dirPath };
    }
    const stat = fs.statSync(dirPath);
    if (!stat.isDirectory()) {
      return { error: true, message: 'Not a directory: ' + dirPath };
    }

    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    const folders = [];
    const files = [];

    for (const entry of entries) {
      // Skip hidden files/dirs and node_modules
      if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;

      const fullPath = path.join(dirPath, entry.name);
      try {
        if (entry.isDirectory()) {
          let childCount = 0;
          try {
            const children = fs.readdirSync(fullPath);
            childCount = children.filter(c => !c.startsWith('.')).length;
          } catch { /* permission denied */ }
          folders.push({
            name: entry.name,
            path: fullPath,
            children: childCount,
            isDirectory: true,
          });

          // Recurse one level if maxDepth > 1
          if (maxDepth > 1) {
            try {
              const subEntries = fs.readdirSync(fullPath, { withFileTypes: true });
              for (const sub of subEntries) {
                if (sub.name.startsWith('.') || sub.name === 'node_modules') continue;
                const subPath = path.join(fullPath, sub.name);
                try {
                  if (sub.isDirectory()) {
                    const sc = fs.readdirSync(subPath).filter(c => !c.startsWith('.')).length;
                    folders.push({ name: entry.name + '/' + sub.name, path: subPath, children: sc, isDirectory: true });
                  } else {
                    const ss = fs.statSync(subPath);
                    files.push({ name: sub.name, path: subPath, size: ss.size, modified: ss.mtimeMs, parent: entry.name });
                  }
                } catch { /* skip */ }
              }
            } catch { /* skip */ }
          }
        } else if (entry.isFile()) {
          const st = fs.statSync(fullPath);
          files.push({
            name: entry.name,
            path: fullPath,
            size: st.size,
            modified: st.mtimeMs,
            parent: null,
          });
        }
      } catch { /* permission denied — skip */ }
    }

    return {
      path: dirPath,
      name: path.basename(dirPath),
      folders,
      files,
    };
  } catch (err) {
    return { error: true, message: err.message };
  }
});

// Read first N lines of a text file for preview
ipcMain.handle('read-file-preview', async (_e, filePath, maxLines = 80) => {
  try {
    if (!filePath || !fs.existsSync(filePath)) return { error: true, message: 'File not found' };
    const stat = fs.statSync(filePath);
    if (stat.size > 2 * 1024 * 1024) return { preview: '[File too large for preview]', size: stat.size, binary: true };

    const buf = fs.readFileSync(filePath);
    // Detect binary
    const sample = buf.slice(0, Math.min(512, buf.length));
    let nullCount = 0;
    for (let i = 0; i < sample.length; i++) { if (sample[i] === 0) nullCount++; }
    if (nullCount > sample.length * 0.1) {
      return { preview: `[Binary file: ${stat.size} bytes]`, size: stat.size, binary: true };
    }

    const text = buf.toString('utf-8');
    const lines = text.split('\n').slice(0, maxLines);
    return { preview: lines.join('\n'), size: stat.size, binary: false, lines: lines.length, totalLines: text.split('\n').length };
  } catch (err) {
    return { error: true, message: err.message };
  }
});
