/**
 * AetherCloud-L v0.9.2 — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * All traffic routes through VPS1 HTTPS proxy → VPS2 private mesh
 */

// Accept self-signed certificate for VPS1
// VPS1 uses a self-signed cert — traffic is still fully encrypted
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const https = require('https');
const http  = require('http');
const fs    = require('fs');

const keyManager = require('./key-manager');

// Accept self-signed cert ONLY from our VPS1 IP
app.on('certificate-error', (event, webContents, url, error, certificate, callback) => {
  if (url.startsWith('https://143.198.162.111')) {
    event.preventDefault();
    callback(true);
  } else {
    callback(false);
  }
});

// ── Constants ────────────────────────────────────────
const PAGES_DIR    = path.join(__dirname, 'pages');
const API_BASE     = 'https://143.198.162.111/cloud';
const DOWNLOAD_URL = 'https://aethersystems.io/download/latest';

// ── Update tracking (shared between boot check + IPC) ──
let _updateInfo = { currentVersion: null, latestVersion: null, updateAvailable: false, downloadUrl: DOWNLOAD_URL };

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
        const mod = statusUrl.startsWith('https') ? https : http;
        const req = mod.get(statusUrl, { rejectUnauthorized: false }, (res) => {
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

      console.log(`[AetherCloud] Backend connected — Protocol-C: ${data.protocol_c || 'ACTIVE'}, Agent: ${data.agent}`);

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
    detail: `Tried ${maxRetries} times to reach ${API_BASE}/status\n\nCheck:\n• VPS1 is running (143.198.162.111)\n• Backend is active\n• Your internet connection`,
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
      const mod = API_BASE.startsWith('https') ? https : http;
      const req = mod.get(`${API_BASE}/routing-check`, { rejectUnauthorized: false }, (res) => {
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
      // IBM quantum references removed — Protocol-C only
    }
    return data;
  } catch (err) {
    console.error('[AetherCloud] Routing check failed:', err.message);
    return null;
  }
}

// ── Version comparison ───────────────────────────────
// Returns >0 if a > b, <0 if a < b, 0 if equal.
function compareVersions(a, b) {
  const pa = String(a).split('.').map(Number);
  const pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

// ── Update check ─────────────────────────────────────
// Called after waitForBackend() — server version is the source of truth.
async function checkForUpdates(serverVersion) {
  const localVersion = app.getVersion();
  _updateInfo.currentVersion = localVersion;
  _updateInfo.latestVersion  = serverVersion || localVersion;

  if (!serverVersion || compareVersions(serverVersion, localVersion) <= 0) {
    _updateInfo.updateAvailable = false;
    return; // up to date or server didn't report a version
  }

  _updateInfo.updateAvailable = true;
  console.log(`[AetherCloud] Update available: ${localVersion} → ${serverVersion}`);

  const { response } = await dialog.showMessageBox({
    type: 'info',
    title: 'AetherCloud Update Available',
    message: `A new version is available`,
    detail: `You are running v${localVersion}.\nThe latest version is v${serverVersion}.\n\nDownload the update to access new features and security improvements.`,
    buttons: ['Download Update', 'Continue Anyway'],
    defaultId: 0,
    cancelId: 1,
  });

  if (response === 0) {
    shell.openExternal(DOWNLOAD_URL);
    // Give the browser a moment to open, then continue launching
    await new Promise(r => setTimeout(r, 1500));
  }
}

// ── App lifecycle ────────────────────────────────────
app.whenReady().then(async () => {
  keyManager.hydrate();

  // Test backend connectivity before showing login
  const status = await waitForBackend();
  if (!status.ready) return;

  // Check for updates using server version as source of truth
  await checkForUpdates(status.version);

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
ipcMain.handle('app:updateInfo', () => _updateInfo);
ipcMain.handle('app:openDownload', () => shell.openExternal(DOWNLOAD_URL));

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

    // Guard: directories cannot be read as files
    if (stat.isDirectory()) {
      const entries = fs.readdirSync(filePath, { withFileTypes: true });
      const listing = entries.slice(0, 50).map(e => `${e.isDirectory() ? '📁' : '📄'} ${e.name}`).join('\n');
      return { preview: listing, size: 0, binary: false, lines: entries.length, totalLines: entries.length, isDirectory: true };
    }

    // Skip known binary extensions before reading
    const binExts = ['.exe','.dll','.bin','.png','.jpg','.jpeg','.gif','.bmp','.ico','.zip','.tar','.gz','.7z','.rar','.mp3','.mp4','.mov','.avi','.woff','.woff2','.ttf','.otf','.so','.dylib','.psd','.ai'];
    const ext = (filePath.match(/\.[^.]+$/) || [''])[0].toLowerCase();
    if (binExts.includes(ext)) {
      return { preview: `[Binary file: ${ext} — ${stat.size} bytes]`, size: stat.size, binary: true };
    }

    // Cap at 50KB to avoid memory issues
    if (stat.size > 50 * 1024) {
      const fd = fs.openSync(filePath, 'r');
      const buf = Buffer.alloc(50 * 1024);
      fs.readSync(fd, buf, 0, 50 * 1024, 0);
      fs.closeSync(fd);
      const text = buf.toString('utf-8');
      const lines = text.split('\n').slice(0, maxLines);
      return { preview: lines.join('\n') + '\n\n[... truncated at 50KB]', size: stat.size, binary: false, lines: lines.length, truncated: true };
    }

    const buf = fs.readFileSync(filePath);
    // Detect binary via null-byte ratio
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

// ═══════════════════════════════════════════════════
// IPC: Read directory tree with file contents for agent context
// ═══════════════════════════════════════════════════
const SKIP_DIRS = new Set(['.git', 'node_modules', '__pycache__', '.venv', 'env', '.next', 'dist', 'build', '.cache', '.idea', '.vscode']);
const TEXT_EXTS = new Set(['.py','.js','.ts','.tsx','.jsx','.json','.md','.txt','.html','.css','.yml','.yaml','.toml','.cfg','.ini','.sh','.bat','.ps1','.sql','.xml','.csv','.env','.gitignore','.dockerfile','.rs','.go','.java','.c','.cpp','.h','.rb','.php','.swift','.kt','.r','.vue','.svelte']);
const PRIORITY_EXTS = ['.py','.js','.ts','.tsx','.jsx','.json','.md'];
const MAX_FILE_SIZE = 50 * 1024; // 50KB per file
const MAX_FILES_READ = 20;

// Options: maxFiles (number), treeOnly (bool), specificFiles (string[] of relPaths)
ipcMain.handle('read-directory-context', async (_e, dirPath, optionsOrMax = MAX_FILES_READ) => {
  try {
    if (!dirPath || !fs.existsSync(dirPath)) return { error: true, message: 'Path not found' };
    const stat = fs.statSync(dirPath);
    if (!stat.isDirectory()) return { error: true, message: 'Not a directory' };

    // Support both old (number) and new (object) signatures
    let maxFiles = MAX_FILES_READ;
    let treeOnly = false;
    let specificFiles = null;
    if (typeof optionsOrMax === 'number') {
      maxFiles = optionsOrMax;
    } else if (typeof optionsOrMax === 'object' && optionsOrMax !== null) {
      maxFiles = optionsOrMax.maxFiles || MAX_FILES_READ;
      treeOnly = !!optionsOrMax.treeOnly;
      specificFiles = optionsOrMax.specificFiles || null;
    }

    const allFiles = [];
    const walkDir = (dir, rel = '') => {
      let entries;
      try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
      for (const e of entries) {
        if (e.name.startsWith('.') && e.name !== '.env.example') continue;
        const full = path.join(dir, e.name);
        const relPath = rel ? rel + '/' + e.name : e.name;
        if (e.isDirectory()) {
          if (!SKIP_DIRS.has(e.name)) walkDir(full, relPath);
        } else if (e.isFile()) {
          try {
            const s = fs.statSync(full);
            const ext = path.extname(e.name).toLowerCase();
            allFiles.push({ path: full, relPath, size: s.size, ext });
          } catch { /* skip */ }
        }
      }
    };
    walkDir(dirPath);

    // Sort by priority
    allFiles.sort((a, b) => {
      const ap = PRIORITY_EXTS.includes(a.ext) ? 0 : 1;
      const bp = PRIORITY_EXTS.includes(b.ext) ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return a.size - b.size;
    });

    const treeListing = allFiles.map(f => `  ${f.relPath}  (${f.size} bytes)`).join('\n');

    // Tree-only mode: return metadata without reading contents
    if (treeOnly) {
      const textFiles = allFiles.filter(f => TEXT_EXTS.has(f.ext));
      return {
        directory: dirPath,
        totalFiles: allFiles.length,
        textFileCount: textFiles.length,
        filesRead: 0,
        treeListing,
        fileContents: [],
        fileMeta: allFiles.map(f => ({ relPath: f.relPath, size: f.size, ext: f.ext, isText: TEXT_EXTS.has(f.ext) })),
      };
    }

    // Determine which files to read
    let filesToRead = allFiles;
    if (specificFiles && specificFiles.length > 0) {
      const specSet = new Set(specificFiles);
      filesToRead = allFiles.filter(f => specSet.has(f.relPath));
      maxFiles = specificFiles.length;
    }

    // Read files
    const fileContents = [];
    let readCount = 0;
    for (const f of filesToRead) {
      if (readCount >= maxFiles) break;
      if (!TEXT_EXTS.has(f.ext)) continue;
      if (f.size > MAX_FILE_SIZE) {
        fileContents.push({ relPath: f.relPath, content: `[Truncated — file is ${f.size} bytes, max ${MAX_FILE_SIZE}]`, truncated: true });
        readCount++;
        continue;
      }
      if (f.size === 0) continue;
      try {
        const buf = fs.readFileSync(f.path);
        const sample = buf.slice(0, Math.min(512, buf.length));
        let nulls = 0;
        for (let i = 0; i < sample.length; i++) { if (sample[i] === 0) nulls++; }
        if (nulls > sample.length * 0.1) continue;
        fileContents.push({ relPath: f.relPath, content: buf.toString('utf-8') });
        readCount++;
      } catch { /* skip unreadable */ }
    }

    return {
      directory: dirPath,
      totalFiles: allFiles.length,
      filesRead: fileContents.length,
      treeListing,
      fileContents,
    };
  } catch (err) {
    return { error: true, message: err.message };
  }
});

// ═══════════════════════════════════════════════════
// IPC: Auth Persistence (remember me)
// ═══════════════════════════════════════════════════
let authStore = null;
function getAuthStore() {
  if (!authStore) authStore = require('./auth-store');
  return authStore;
}

ipcMain.handle('auth:get', () => {
  const store = getAuthStore();
  return {
    sessionToken: store.get('sessionToken') || null,
    userId: store.get('userId') || null,
    email: store.get('email') || null,
    rememberMe: store.get('rememberMe', true),
    lastLogin: store.get('lastLogin') || null,
    serverUrl: store.get('serverUrl') || null,
    licenseKey: store.get('licenseKey') || null,
    plan: store.get('plan') || null,
  };
});

ipcMain.handle('auth:set', (_e, data) => {
  const store = getAuthStore();
  if (data.sessionToken !== undefined) store.set('sessionToken', data.sessionToken);
  if (data.userId !== undefined) store.set('userId', data.userId);
  if (data.email !== undefined) store.set('email', data.email);
  if (data.rememberMe !== undefined) store.set('rememberMe', data.rememberMe);
  if (data.lastLogin !== undefined) store.set('lastLogin', data.lastLogin);
  if (data.serverUrl !== undefined) store.set('serverUrl', data.serverUrl);
  if (data.licenseKey !== undefined) store.set('licenseKey', data.licenseKey);
  if (data.plan !== undefined) store.set('plan', data.plan);
  return { success: true };
});

ipcMain.handle('auth:clear', () => {
  const store = getAuthStore();
  store.delete('sessionToken');
  store.delete('userId');
  store.delete('email');
  return { success: true };
});

ipcMain.handle('auth:clearAll', () => {
  const store = getAuthStore();
  store.clear();
  return { success: true };
});

// ═══════════════════════════════════════════════════
// IPC: Analysis Cache (persistent directory analysis memory)
// ═══════════════════════════════════════════════════
let analysisCache = null;
function getAnalysisCache() {
  if (!analysisCache) analysisCache = require('./analysis-cache');
  return analysisCache;
}

ipcMain.handle('cache:get', (_e, dirPath) => {
  try {
    const cache = getAnalysisCache();
    const entries = cache.get('entries', {});
    return entries[dirPath] || null;
  } catch { return null; }
});

ipcMain.handle('cache:set', (_e, dirPath, entry) => {
  try {
    const cache = getAnalysisCache();
    const entries = cache.get('entries', {});
    entries[dirPath] = entry;
    cache.set('entries', entries);
    return { success: true };
  } catch (err) { return { error: true, message: err.message }; }
});

ipcMain.handle('cache:list', () => {
  try {
    const cache = getAnalysisCache();
    const entries = cache.get('entries', {});
    return Object.values(entries).map(e => ({
      path: e.path, label: e.label, analyzedAt: e.analyzedAt,
      fileCount: e.fileCount, passes: e.passes, fingerprint: e.fingerprint,
    }));
  } catch { return []; }
});

ipcMain.handle('cache:clear', (_e, dirPath) => {
  try {
    const cache = getAnalysisCache();
    if (dirPath) {
      const entries = cache.get('entries', {});
      delete entries[dirPath];
      cache.set('entries', entries);
    } else {
      cache.set('entries', {});
    }
    return { success: true };
  } catch (err) { return { error: true, message: err.message }; }
});

// ═══════════════════════════════════════════════════
// IPC: Admin License Server Calls
// ═══════════════════════════════════════════════════
const LICENSE_SERVER = process.env.AETHER_LICENSE_SERVER || 'https://143.198.162.111/api/license';
const ADMIN_KEY = process.env.AETHER_ADMIN_KEY || '';

async function adminFetch(endpoint, options = {}) {
  const url = `${LICENSE_SERVER}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    'X-Aether-Admin-Key': ADMIN_KEY,
    ...(options.headers || {}),
  };
  try {
    const resp = await fetch(url, { ...options, headers });
    return await resp.json();
  } catch (err) {
    return { error: true, message: err.message };
  }
}

ipcMain.handle('admin:overview', () => adminFetch('/admin/overview'));
ipcMain.handle('admin:scrambler:list', (_e, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return adminFetch(`/license/scrambler/list?${qs}`);
});
ipcMain.handle('admin:scrambler:issue', (_e, data) =>
  adminFetch('/license/scrambler/issue', { method: 'POST', body: JSON.stringify(data) })
);
ipcMain.handle('admin:scrambler:revoke', (_e, data) =>
  adminFetch('/license/scrambler/revoke', { method: 'POST', body: JSON.stringify(data) })
);
ipcMain.handle('admin:scrambler:extend', (_e, data) =>
  adminFetch('/license/scrambler/extend', { method: 'POST', body: JSON.stringify(data) })
);
ipcMain.handle('admin:cloud:list', (_e, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return adminFetch(`/license/cloud/list?${qs}`);
});
ipcMain.handle('admin:cloud:issue', (_e, data) =>
  adminFetch('/license/cloud/issue', { method: 'POST', body: JSON.stringify(data) })
);
ipcMain.handle('admin:cloud:revoke', (_e, data) =>
  adminFetch('/license/cloud/revoke', { method: 'POST', body: JSON.stringify(data) })
);
ipcMain.handle('admin:apikey:list', (_e, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return adminFetch(`/license/api/list?${qs}`);
});
ipcMain.handle('admin:apikey:issue', (_e, data) =>
  adminFetch('/license/api/issue', { method: 'POST', body: JSON.stringify(data) })
);
ipcMain.handle('admin:apikey:revoke', (_e, data) =>
  adminFetch('/license/api/revoke', { method: 'POST', body: JSON.stringify(data) })
);
