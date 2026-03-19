/**
 * AetherCloud-L Desktop — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * Flow: installer.html → login.html → app.html
 * Each page transition uses IPC so the main process controls window
 * geometry, frameless chrome, and secure context isolation.
 */

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path  = require('path');
const fs    = require('fs');

// ── State ────────────────────────────────────────────
const PAGES_DIR    = path.join(__dirname, 'pages');
const INSTALL_FLAG = path.join(app.getPath('userData'), '.installed');
const isDev        = process.argv.includes('--dev');
let mainWindow     = null;

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

// ── Create / navigate window ─────────────────────────
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
      sandbox:            true,
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

// ── IPC handlers ─────────────────────────────────────

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

// ── App lifecycle ────────────────────────────────────
app.whenReady().then(() => {
  // Skip installer if already installed
  const startPage = isInstalled() ? 'login' : 'installer';
  createWindow(startPage);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow(isInstalled() ? 'login' : 'installer');
    }
  });
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
