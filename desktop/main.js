/**
 * AetherCloud-L Desktop — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * Flow: installer.html → login.html → app.html
 * Spawns Python FastAPI server on localhost:8741.
 * Each page transition uses IPC so the main process controls window
 * geometry, frameless chrome, and secure context isolation.
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path  = require('path');
const fs    = require('fs');
const http  = require('http');

// ── State ────────────────────────────────────────────
const PAGES_DIR    = path.join(__dirname, 'pages');
const PROJECT_ROOT = path.join(__dirname, '..');
const INSTALL_FLAG = path.join(app.getPath('userData'), '.installed');
const isDev        = process.argv.includes('--dev');
const API_PORT     = 8741;
const API_BASE     = `http://127.0.0.1:${API_PORT}`;

let mainWindow     = null;
let pythonProcess  = null;
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
// PYTHON PROCESS MANAGEMENT
// ═══════════════════════════════════════════════════
function findPython() {
  // Try common Python executables
  const candidates = process.platform === 'win32'
    ? ['python', 'python3', 'py']
    : ['python3', 'python'];
  return candidates[0]; // spawn will search PATH
}

function startPython() {
  if (pythonProcess) return;

  const pythonPath = findPython();
  const scriptPath = path.join(PROJECT_ROOT, 'main.py');

  console.log(`[Python] Starting: ${pythonPath} ${scriptPath} --serve`);

  pythonProcess = spawn(pythonPath, [scriptPath, '--serve'], {
    cwd: PROJECT_ROOT,
    env: { ...process.env },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  pythonProcess.stdout.on('data', (data) => {
    console.log(`[Python] ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on('data', (data) => {
    const msg = data.toString().trim();
    // uvicorn logs to stderr by default — not necessarily errors
    if (msg) console.log(`[Python] ${msg}`);
  });

  pythonProcess.on('error', (err) => {
    console.error(`[Python] Failed to start: ${err.message}`);
    pythonProcess = null;
  });

  pythonProcess.on('close', (code) => {
    console.log(`[Python] Process exited with code ${code}`);
    pythonProcess = null;
    // Auto-restart on unexpected exit (unless app is quitting)
    if (code !== 0 && !appQuitting) {
      console.log('[Python] Unexpected exit — restarting in 2s...');
      setTimeout(startPython, 2000);
    }
  });
}

function stopPython() {
  if (!pythonProcess) return;
  console.log('[Python] Stopping server...');
  try {
    if (process.platform === 'win32') {
      // On Windows, spawn taskkill to ensure child processes are killed
      spawn('taskkill', ['/pid', pythonProcess.pid.toString(), '/f', '/t']);
    } else {
      pythonProcess.kill('SIGTERM');
    }
  } catch (e) {
    console.error('[Python] Error stopping:', e.message);
  }
  pythonProcess = null;
}

/**
 * Poll the /status endpoint until the Python server is ready.
 * Returns a promise that resolves when server responds,
 * or rejects after maxWait ms.
 */
function waitForPython(maxWait = 15000, interval = 500) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + maxWait;

    function poll() {
      if (Date.now() > deadline) {
        return reject(new Error('Python server did not start in time'));
      }

      const req = http.get(`${API_BASE}/status`, (res) => {
        let body = '';
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => {
          try {
            const data = JSON.parse(body);
            console.log(`[Python] Server ready — Protocol-L: ${data.protocol_l}, Agent: ${data.agent}`);
            resolve(data);
          } catch (e) {
            setTimeout(poll, interval);
          }
        });
      });

      req.on('error', () => {
        setTimeout(poll, interval);
      });

      req.setTimeout(2000, () => {
        req.destroy();
        setTimeout(poll, interval);
      });
    }

    poll();
  });
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

// Get API base URL
ipcMain.handle('api:getBase', () => API_BASE);

// Check if Python server is ready
ipcMain.handle('api:isReady', async () => {
  try {
    await waitForPython(2000, 500);
    return true;
  } catch {
    return false;
  }
});

// ═══════════════════════════════════════════════════
// APP LIFECYCLE
// ═══════════════════════════════════════════════════
app.whenReady().then(async () => {
  // Start Python backend server
  startPython();

  // Skip installer if already installed
  const startPage = isInstalled() ? 'login' : 'installer';
  createWindow(startPage);

  // Wait for Python server to be ready (non-blocking — window shows immediately)
  try {
    await waitForPython(15000, 500);
    console.log('[Electron] Python backend ready');
  } catch (e) {
    console.warn('[Electron] Python backend not ready:', e.message);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow(isInstalled() ? 'login' : 'installer');
    }
  });
});

app.on('before-quit', () => {
  appQuitting = true;
  stopPython();
});

app.on('window-all-closed', () => {
  stopPython();
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
