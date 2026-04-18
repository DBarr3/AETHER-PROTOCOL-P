/**
 * AetherCloud-L v0.9.4 — Electron Main Process
 * Aether Systems LLC · Patent Pending
 *
 * All traffic routes through VPS1 HTTPS proxy → VPS2 private mesh
 */

// Cloudflare provides valid SSL — TLS verification enabled

const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const https = require('https');
const http  = require('http');
const fs    = require('fs');
const os    = require('os');

const keyManager = require('./key-manager');

// Cloudflare provides valid SSL — reject all cert errors
app.on('certificate-error', (event, webContents, url, error, certificate, callback) => {
  callback(false);
});

// ── Constants ────────────────────────────────────────
const PAGES_DIR    = path.join(__dirname, 'pages');
const API_BASE     = 'https://api.aethersystems.net/cloud';
const DOWNLOAD_URL = 'https://aethersystems.io/download/latest';

// ── Security: path-jail for every filesystem IPC ─────
// Every filesystem-touching IPC handler routes user-supplied paths through
// safeResolve() which enforces (1) no UNC/SMB, (2) no null bytes,
// (3) symlink rejection at the leaf, (4) resolved path must lie inside an
// allowed root. Allowed roots = AETHER_VAULT_ROOT (env) + ~/AetherVault +
// any directory the user has explicitly picked from a folder-dialog this
// session. Without this, any renderer XSS can rm -rf the home directory.
const DANGEROUS_EXEC_EXTS = new Set([
  '.exe','.bat','.cmd','.com','.ps1','.vbs','.vbe','.js','.jse',
  '.ws','.wsf','.wsh','.msh','.hta','.scr','.msi','.msp','.lnk',
  '.url','.reg','.dll','.chm','.cpl','.pif','.jar','.appx','.appxbundle',
]);
const sessionGrantedRoots = new Set();

function _defaultVaultRoots() {
  const roots = [];
  if (process.env.AETHER_VAULT_ROOT) {
    try { roots.push(path.resolve(process.env.AETHER_VAULT_ROOT)); } catch {}
  }
  try { roots.push(path.resolve(path.join(os.homedir(), 'AetherVault'))); } catch {}
  return roots;
}
function getAllowedRoots() {
  const base = _defaultVaultRoots();
  for (const r of sessionGrantedRoots) base.push(r);
  return base;
}
function grantRoot(dir) {
  try {
    if (!dir || typeof dir !== 'string') return null;
    const resolved = path.resolve(dir);
    sessionGrantedRoots.add(resolved);
    return resolved;
  } catch { return null; }
}
function isUncPath(p) {
  if (typeof p !== 'string') return false;
  if (process.platform !== 'win32') return false;
  return p.startsWith('\\\\') || p.startsWith('//');
}
// Canonicalize a path; for non-existent leaves, realpath the deepest existing
// ancestor and re-attach the suffix. Defeats symlink-hop escapes.
function _canonicalize(candidate) {
  const abs = path.resolve(candidate);
  let cursor = abs;
  const suffix = [];
  for (let i = 0; i < 64; i++) {
    try { fs.lstatSync(cursor); break; }
    catch {
      const parent = path.dirname(cursor);
      if (parent === cursor) break;
      suffix.unshift(path.basename(cursor));
      cursor = parent;
    }
  }
  let realAncestor;
  try { realAncestor = fs.realpathSync.native(cursor); }
  catch { realAncestor = cursor; }
  return suffix.length ? path.join(realAncestor, ...suffix) : realAncestor;
}
// opts: { allowCreate, denyExec, allowedExt, allowSymlink }
function safeResolve(candidate, opts = {}) {
  if (typeof candidate !== 'string' || candidate.length === 0) {
    throw new Error('Invalid path');
  }
  if (candidate.includes('\0')) throw new Error('Null byte in path');
  if (isUncPath(candidate)) throw new Error('UNC / network paths are blocked');
  const canonical = _canonicalize(candidate);
  if (isUncPath(canonical)) throw new Error('UNC / network paths are blocked');

  const roots = getAllowedRoots().map(r => _canonicalize(r));
  const sep = path.sep;
  const insideRoot = roots.some(root => {
    const withSep = root.endsWith(sep) ? root : root + sep;
    return canonical === root || canonical.startsWith(withSep);
  });
  if (!insideRoot) {
    throw new Error(`Path is outside the allowed vault root (${candidate})`);
  }

  const ext = path.extname(canonical).toLowerCase();
  if (opts.denyExec && DANGEROUS_EXEC_EXTS.has(ext)) {
    throw new Error(`Refusing to operate on executable type: ${ext}`);
  }
  if (opts.allowedExt) {
    const allowed = new Set(
      (Array.isArray(opts.allowedExt) ? opts.allowedExt : [...opts.allowedExt])
        .map(e => e.toLowerCase())
    );
    if (!allowed.has(ext)) throw new Error(`File type not allowed: ${ext}`);
  }

  try {
    const lst = fs.lstatSync(canonical);
    if (!opts.allowSymlink && lst.isSymbolicLink()) {
      throw new Error('Symbolic links are not allowed');
    }
  } catch (e) {
    if (e.message && e.message.includes('Symbolic')) throw e;
    if (!opts.allowCreate) throw new Error(`Path does not exist: ${candidate}`);
  }
  return canonical;
}

// ── Update tracking (shared between boot check + IPC) ──
let _updateInfo = { currentVersion: null, latestVersion: null, updateAvailable: false, downloadUrl: DOWNLOAD_URL };

let mainWindow = null;
let appQuitting = false;
const terminalWindows = new Map(); // key: 'agent-{id}' or 'team-{name}'

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
      sandbox: true,
      devTools: !app.isPackaged,  // DevTools disabled in production builds
    },
  });

  mainWindow = win;

  // Navigation guards — audit M4. Without these:
  //   - window.open / target=_blank creates a NEW BrowserWindow that inherits
  //     our preload (including every window.aether.* IPC bridge).
  //   - will-navigate on an attacker-controlled URL redirects the renderer
  //     to an external page but keeps the preload active.
  // Both fail any XSS + link attack into instant preload hijack.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) shell.openExternal(url);
    else console.warn('[AetherCloud] Blocked window.open to non-allowlist URL:', url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, navUrl) => {
    // Only allow file:// (internal page navigation) and hash fragments.
    if (!navUrl.startsWith('file://')) {
      console.warn('[AetherCloud] Blocked in-place navigation to:', navUrl);
      event.preventDefault();
    }
  });

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
        const req = mod.get(statusUrl, (res) => {
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
    detail: `Tried ${maxRetries} times to reach ${API_BASE}/status\n\nCheck:\n• api.aethersystems.net is reachable\n• Backend is active\n• Your internet connection`,
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
      const req = mod.get(`${API_BASE}/routing-check`, (res) => {
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
// Records version info for the app:updateInfo IPC handler.
// No longer shows a native dialog — the dashboard HTML banner
// handles version mismatch display (directional: only when backend > installed).
// The old native dialog was problematic: it fired before the app loaded,
// pointed to a download URL that might serve stale installers, and
// confused users by telling them to "download" when they already had the latest.
async function checkForUpdates(serverVersion) {
  const localVersion = app.getVersion();
  _updateInfo.currentVersion = localVersion;
  _updateInfo.latestVersion  = serverVersion || localVersion;

  if (!serverVersion || compareVersions(serverVersion, localVersion) <= 0) {
    _updateInfo.updateAvailable = false;
    console.log(`[AetherCloud] Version check: installed v${localVersion}, backend v${serverVersion || 'unknown'} — up to date`);
    return;
  }

  _updateInfo.updateAvailable = true;
  console.log(`[AetherCloud] Version check: installed v${localVersion}, backend v${serverVersion} — update available (dashboard will show banner)`);
  // Dashboard banner handles the UI notification — no native dialog needed.
}

// ── App lifecycle ────────────────────────────────────
// Strict CSP injected as a response header for every response the default
// session handles. Defense-in-depth: the meta tag in each HTML page is the
// primary enforcement (file:// loads never hit this hook), but any https://
// sub-resource load gets the header applied regardless.
const CSP_POLICY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data:",
  "connect-src 'self' https://api.aethersystems.net https://license.aethersystems.net",
  "object-src 'none'",
  "base-uri 'none'",
  "frame-ancestors 'none'",
  "form-action 'none'",
].join('; ');

function installCspHeader() {
  const { session } = require('electron');
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const headers = { ...details.responseHeaders };
    // Strip any existing CSP/X-Frame headers so ours is authoritative
    for (const k of Object.keys(headers)) {
      const lk = k.toLowerCase();
      if (lk === 'content-security-policy' || lk === 'content-security-policy-report-only' || lk === 'x-frame-options') {
        delete headers[k];
      }
    }
    headers['Content-Security-Policy'] = [CSP_POLICY];
    headers['X-Frame-Options'] = ['DENY'];
    callback({ responseHeaders: headers });
  });
}

app.whenReady().then(async () => {
  installCspHeader();
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

// ── IPC: Agent QOPC refresh (stub — full loop integration deferred) ──
ipcMain.handle('agent:qopcRefresh', async (_e, agentId) => ({
  agentId,
  status: 'IDLE',
  lastSync: new Date().toISOString(),
  qopcCycle: Math.floor(Math.random() * 1000),
}));

// ── IPC: Dialogs ─────────────────────────────────────
ipcMain.handle('dialog:openDirectory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
  });
  if (result.canceled) return null;
  grantRoot(result.filePaths[0]);
  return result.filePaths[0];
});

ipcMain.handle('browse-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select folder to connect',
  });
  if (result.canceled) return null;
  grantRoot(result.filePaths[0]);
  return result.filePaths[0];
});

// ── IPC: Shell ───────────────────────────────────────
// Whitelist external URLs — only allow known Aether Systems domains
const ALLOWED_EXTERNAL_HOSTS = new Set([
  'aethersystems.net',
  'aethersystems.io',
]);
function isSafeExternalUrl(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return false;
    const host = parsed.hostname.toLowerCase();
    return [...ALLOWED_EXTERNAL_HOSTS].some(h => host === h || host.endsWith('.' + h));
  } catch { return false; }
}
ipcMain.on('shell:openExternal', (_e, url) => {
  if (isSafeExternalUrl(url)) {
    shell.openExternal(url);
  } else {
    console.warn('[AetherCloud] Blocked external URL (not in allowlist):', url);
  }
});
ipcMain.handle('open-file', async (_e, filePath) => {
  try {
    const safe = safeResolve(filePath, { denyExec: true });
    const result = await shell.openPath(safe);
    // openPath returns an error-string on failure, empty string on success.
    if (result) return { success: false, error: result };
    return { success: true };
  } catch (err) { return { success: false, error: err.message }; }
});
ipcMain.handle('show-in-explorer', async (_e, filePath) => {
  try {
    const safe = safeResolve(filePath, { denyExec: true });
    shell.showItemInFolder(safe);
    return { success: true };
  } catch (err) { return { success: false, error: err.message }; }
});

// ── IPC: Key management ──────────────────────────────
ipcMain.handle('keys:set', (_e, name, value) => keyManager.setKey(name, value));
ipcMain.handle('keys:has', (_e, name) => keyManager.hasKey(name));
ipcMain.handle('keys:delete', (_e, name) => keyManager.deleteKey(name));
ipcMain.handle('keys:validate', () => keyManager.validate());

// ── IPC: Local File Plan Execution ───────────────────
// Executes an action-plan produced by the agent.
// Actions: { type: 'mkdir'|'move'|'rename', path, from, to, new_name }
// Returns array of { action, success, error? } per action.
ipcMain.handle('fs:execPlan', async (_e, actions) => {
  if (!Array.isArray(actions)) return [];
  const results = [];
  for (const action of actions) {
    try {
      if (action.type === 'mkdir') {
        const dst = safeResolve(action.path, { allowCreate: true });
        fs.mkdirSync(dst, { recursive: true });
        results.push({ action, success: true });

      } else if (action.type === 'move') {
        const src = safeResolve(action.from);
        const dst = safeResolve(action.to, { allowCreate: true, denyExec: true });
        const destDir = path.dirname(dst);
        // destDir must also be inside the jail
        safeResolve(destDir, { allowCreate: true });
        fs.mkdirSync(destDir, { recursive: true });
        fs.renameSync(src, dst);
        results.push({ action, success: true });

      } else if (action.type === 'rename') {
        if (!action.new_name || typeof action.new_name !== 'string') {
          results.push({ action, success: false, error: 'Invalid new_name' });
          continue;
        }
        if (action.new_name.includes('/') || action.new_name.includes('\\') ||
            action.new_name.includes('..') || action.new_name.includes('\0')) {
          results.push({ action, success: false, error: 'new_name must be a bare filename' });
          continue;
        }
        const src = safeResolve(action.path);
        const dir = path.dirname(src);
        const dest = safeResolve(path.join(dir, action.new_name), { allowCreate: true, denyExec: true });
        fs.renameSync(src, dest);
        results.push({ action, success: true });

      } else {
        results.push({ action, success: false, error: 'Unknown action type: ' + action.type });
      }
    } catch (e) {
      results.push({ action, success: false, error: e.message });
    }
  }
  return results;
});

// Preview a plan — check which sources exist without executing
ipcMain.handle('fs:previewPlan', async (_e, actions) => {
  if (!Array.isArray(actions)) return [];
  return actions.map(action => {
    let exists = false;
    let denied = false;
    if (action.type === 'move' || action.type === 'rename') {
      const src = action.from || action.path;
      try {
        if (src) { safeResolve(src); exists = true; }
      } catch { denied = true; exists = false; }
    } else if (action.type === 'mkdir') {
      try {
        if (action.path) { safeResolve(action.path, { allowCreate: true }); exists = true; }
      } catch { denied = true; exists = false; }
    }
    return { action, exists, denied };
  });
});

// ── IPC: Agent Profile System ───────────────────────
ipcMain.handle('agent:loadIcons', async () => {
  // Icons are packaged inside desktop/assets/agents/ so they're available
  // in both development (electron .) and installed builds (inside asar).
  const iconsPath = path.join(__dirname, 'assets', 'agents');
  try {
    const files = fs.readdirSync(iconsPath).filter(f => f.endsWith('.svg'));
    return files.map(file => ({
      name: path.basename(file, '.svg'),
      svgContent: fs.readFileSync(path.join(iconsPath, file), 'utf-8'),
    }));
  } catch (e) {
    console.error('[agent:loadIcons]', e.message);
    return [];
  }
});

ipcMain.handle('agent:loadAnimations', async () => {
  // Animation JSON data is packaged inside desktop/assets/agents/animations/
  // so it's available in both development and installed builds.
  const animPath = path.join(__dirname, 'assets', 'agents', 'animations');
  try {
    if (!fs.existsSync(animPath)) return {};
    const files = fs.readdirSync(animPath).filter(f => f.endsWith('.json'));
    const anims = {};
    files.forEach(file => {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(animPath, file), 'utf-8'));
        if (data.id) anims[data.id] = data;
      } catch(e) { /* skip bad files */ }
    });
    return anims;
  } catch (e) {
    console.error('[agent:loadAnimations]', e.message);
    return {};
  }
});

ipcMain.handle('agent:loadProfiles', async () => {
  const profilesPath = path.join(__dirname, '..', 'agent', 'profiles');
  try {
    if (!fs.existsSync(profilesPath)) fs.mkdirSync(profilesPath, { recursive: true });
    const files = fs.readdirSync(profilesPath).filter(f => f.endsWith('.json'));
    return files.map(file => {
      try { return JSON.parse(fs.readFileSync(path.join(profilesPath, file), 'utf-8')); }
      catch { return null; }
    }).filter(Boolean);
  } catch (e) {
    console.error('[agent:loadProfiles]', e.message);
    return [];
  }
});

ipcMain.handle('agent:saveProfile', async (_e, profile) => {
  const profilesPath = path.join(__dirname, '..', 'agent', 'profiles');
  if (!fs.existsSync(profilesPath)) fs.mkdirSync(profilesPath, { recursive: true });
  const filePath = path.join(profilesPath, `${profile.id}.json`);
  fs.writeFileSync(filePath, JSON.stringify(profile, null, 2));
  return { success: true, path: filePath };
});

ipcMain.handle('agent:deleteProfile', async (_e, profileId) => {
  const filePath = path.join(__dirname, '..', 'agent', 'profiles', `${profileId}.json`);
  try {
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
});

// ── IPC: Tool Registry ──────────────────────────────
const DEFAULT_TOOL_REGISTRY = {
  mcpServers: [
    { id:'gmail', name:'Gmail', description:'Read, send, and search emails', category:'Communication', status:'active', transport:'SSE' },
    { id:'google-calendar', name:'Google Calendar', description:'Manage events and scheduling', category:'Productivity', status:'active', transport:'SSE' },
    { id:'slack', name:'Slack', description:'Send and read Slack messages', category:'Communication', status:'available', transport:'HTTP' },
    { id:'github', name:'GitHub', description:'Access repos, issues, and PRs', category:'Dev Tools', status:'available', transport:'HTTP' },
    { id:'notion', name:'Notion', description:'Read and write Notion pages', category:'Productivity', status:'available', transport:'HTTP' },
    { id:'linear', name:'Linear', description:'Create and manage issues', category:'Dev Tools', status:'available', transport:'HTTP' },
    { id:'brave-search', name:'Brave Search', description:'Live web search', category:'Research', status:'available', transport:'HTTP' },
    { id:'filesystem', name:'Filesystem', description:'Read and write local files', category:'System', status:'available', transport:'STDIO' },
    { id:'postgres', name:'PostgreSQL', description:'Query PostgreSQL databases', category:'Data', status:'available', transport:'STDIO' },
    { id:'puppeteer', name:'Puppeteer', description:'Headless browser automation', category:'Automation', status:'available', transport:'STDIO' },
    { id:'fetch-http', name:'Fetch / HTTP', description:'Make HTTP requests', category:'Dev Tools', status:'available', transport:'HTTP' },
    { id:'memory', name:'Memory', description:'Persistent agent memory store', category:'AI Tools', status:'available', transport:'STDIO' },
    { id:'obsidian', name:'Obsidian', description:'Read Obsidian vault notes', category:'Productivity', status:'available', transport:'STDIO' },
    { id:'youtube', name:'YouTube', description:'Search and fetch transcripts', category:'Research', status:'available', transport:'HTTP' },
    { id:'aws-s3', name:'AWS S3', description:'Read and write S3 buckets', category:'Cloud', status:'available', transport:'HTTP' },
  ],
  skills: [
    { id:'web-search', name:'Web Search', description:'Search the internet for current info', category:'Research', status:'available', promptInjection:'You have access to web search. When answering questions that require current information, search the web first.' },
    { id:'code-execution', name:'Code Execution', description:'Run Python and JavaScript snippets', category:'Dev Tools', status:'available', promptInjection:'You can execute Python and JavaScript code to compute answers, process data, or demonstrate solutions.' },
    { id:'pdf-reader', name:'PDF Reader', description:'Extract and parse PDF content', category:'Documents', status:'available', promptInjection:'You can read and extract text from PDF files.' },
    { id:'image-vision', name:'Image Vision', description:'Analyze and describe images', category:'AI Tools', status:'available', promptInjection:'You can analyze images and provide detailed descriptions of their content.' },
    { id:'data-analyst', name:'Data Analyst', description:'Process CSV, Excel, and structured data', category:'Data', status:'available', promptInjection:'You can process and analyze structured data from CSV, Excel, and similar formats.' },
    { id:'summarizer', name:'Summarizer', description:'Compress long documents to key points', category:'Documents', status:'available', promptInjection:'You can summarize long documents into concise key points.' },
    { id:'translator', name:'Translator', description:'Translate between languages', category:'Language', status:'available', promptInjection:'You can translate text between multiple languages accurately.' },
    { id:'deep-researcher', name:'Deep Researcher', description:'Multi-step web research synthesis', category:'Research', status:'available', promptInjection:'You can perform multi-step research, synthesizing information from multiple sources into comprehensive findings.' },
    { id:'email-drafter', name:'Email Drafter', description:'Compose professional emails', category:'Communication', status:'available', promptInjection:'You can draft professional emails with appropriate tone and formatting.' },
    { id:'scheduler', name:'Scheduler', description:'Parse and manage time-based tasks', category:'Productivity', status:'available', promptInjection:'You can parse dates, schedule tasks, and manage time-based workflows.' },
    { id:'report-writer', name:'Report Writer', description:'Generate structured markdown reports', category:'Documents', status:'available', promptInjection:'You can generate well-structured markdown reports with sections, tables, and findings.' },
    { id:'task-planner', name:'Task Planner', description:'Break goals into actionable task lists', category:'Productivity', status:'available', promptInjection:'You can decompose complex goals into structured, actionable task lists with priorities and dependencies.' },
  ]
};

ipcMain.handle('agent:loadToolRegistry', async () => {
  const registryPath = path.join(__dirname, '..', 'agent', 'tools', 'registry.json');
  try {
    if (!fs.existsSync(registryPath)) {
      fs.mkdirSync(path.dirname(registryPath), { recursive: true });
      fs.writeFileSync(registryPath, JSON.stringify(DEFAULT_TOOL_REGISTRY, null, 2));
    }
    return JSON.parse(fs.readFileSync(registryPath, 'utf-8'));
  } catch (e) {
    console.error('[agent:loadToolRegistry]', e.message);
    return DEFAULT_TOOL_REGISTRY;
  }
});

ipcMain.handle('agent:saveToolRegistry', async (_e, registry) => {
  const registryPath = path.join(__dirname, '..', 'agent', 'tools', 'registry.json');
  try {
    fs.mkdirSync(path.dirname(registryPath), { recursive: true });
    fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
});

// ── IPC: Terminal Windows ───────────────────────────
ipcMain.handle('terminal:open', async (_e, config) => {
  const key = config.type === 'agent'
    ? 'agent-' + config.agentId
    : 'team-' + config.teamName;

  if (terminalWindows.has(key)) {
    const existing = terminalWindows.get(key);
    if (!existing.isDestroyed()) {
      existing.focus();
      return { focused: true };
    }
    terminalWindows.delete(key);
  }

  const win = new BrowserWindow({
    width: 680,
    height: 480,
    minWidth: 480,
    minHeight: 320,
    resizable: true,
    frame: false,
    transparent: false,
    backgroundColor: '#0a0a0f',
    title: config.type === 'agent' ? config.agentName : ('Team \u00b7 ' + config.teamName),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
    },
    show: false,
  });

  // Navigation guards — same rationale as the main window (audit M4).
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, navUrl) => {
    if (!navUrl.startsWith('file://')) event.preventDefault();
  });

  win.loadFile(path.join(PAGES_DIR, 'terminal.html'));

  win.once('ready-to-show', () => {
    win.show();
    win.webContents.send('terminal:init', config);
  });

  win.on('closed', () => {
    terminalWindows.delete(key);
  });

  terminalWindows.set(key, win);
  return { opened: true };
});

ipcMain.on('terminal:minimize', (event) => {
  BrowserWindow.fromWebContents(event.sender)?.minimize();
});
ipcMain.on('terminal:maximize', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win?.isMaximized()) win.unmaximize(); else win?.maximize();
});
ipcMain.on('terminal:close', (event) => {
  BrowserWindow.fromWebContents(event.sender)?.close();
});

// ── IPC: Vault ───────────────────────────────────────
// hasAccess: true if a session token is stored (user is authenticated)
ipcMain.handle('vault:hasAccess', () => {
  const store = getAuthStore();
  return !!(store.get('sessionToken'));
});
// getPath: vault root from env var, falling back to ~/AetherVault
ipcMain.handle('vault:getPath', () => {
  return process.env.AETHER_VAULT_ROOT || path.join(os.homedir(), 'AetherVault');
});
ipcMain.handle('vault:requestAccess', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select Vault Root',
  });
  if (result.canceled) return null;
  grantRoot(result.filePaths[0]);
  return result.filePaths[0];
});

ipcMain.handle('request-fs-permission', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Grant filesystem access',
  });
  if (result.canceled) return null;
  grantRoot(result.filePaths[0]);
  return result.filePaths[0];
});

// ── IPC: Local directory scanner ─────────────────────
// Scans a directory on the local filesystem (no VPS needed).
// Returns { folders: [...], files: [...], path, name }
ipcMain.handle('scan-directory', async (_e, dirPath, maxDepth = 1) => {
  try {
    let rootDir;
    try { rootDir = safeResolve(dirPath); }
    catch (err) { return { error: true, message: err.message }; }

    const stat = fs.lstatSync(rootDir);
    if (!stat.isDirectory()) {
      return { error: true, message: 'Not a directory: ' + dirPath };
    }

    const entries = fs.readdirSync(rootDir, { withFileTypes: true });
    const folders = [];
    const files = [];

    for (const entry of entries) {
      // Skip hidden files/dirs and node_modules
      if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
      // Skip symlinks — an imported vault with a symlink to /etc or
      // C:\Windows would otherwise leak through the jail.
      if (entry.isSymbolicLink()) continue;

      const fullPath = path.join(rootDir, entry.name);
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
                if (sub.isSymbolicLink()) continue;
                const subPath = path.join(fullPath, sub.name);
                try {
                  if (sub.isDirectory()) {
                    const sc = fs.readdirSync(subPath).filter(c => !c.startsWith('.')).length;
                    folders.push({ name: entry.name + '/' + sub.name, path: subPath, children: sc, isDirectory: true });
                  } else {
                    const ss = fs.lstatSync(subPath);
                    files.push({ name: sub.name, path: subPath, size: ss.size, modified: ss.mtimeMs, parent: entry.name });
                  }
                } catch { /* skip */ }
              }
            } catch { /* skip */ }
          }
        } else if (entry.isFile()) {
          const st = fs.lstatSync(fullPath);
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
      path: rootDir,
      name: path.basename(rootDir),
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
    let safe;
    try { safe = safeResolve(filePath); }
    catch (err) { return { error: true, message: err.message }; }
    filePath = safe;
    const stat = fs.lstatSync(filePath);

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
    let safe;
    try { safe = safeResolve(dirPath); }
    catch (err) { return { error: true, message: err.message }; }
    dirPath = safe;
    const stat = fs.lstatSync(dirPath);
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
        // Skip symlinks — prevents jail escape via symlink-to-/etc or C:\Windows.
        if (e.isSymbolicLink()) continue;
        const full = path.join(dir, e.name);
        const relPath = rel ? rel + '/' + e.name : e.name;
        if (e.isDirectory()) {
          if (!SKIP_DIRS.has(e.name)) walkDir(full, relPath);
        } else if (e.isFile()) {
          try {
            const s = fs.lstatSync(full);
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

// Scoped status — returns ONLY non-secret fields. Renderer code that only
// needs to know "is the user logged in" or display the user's email should
// use this instead of auth:get so an XSS can't lift the token/license key.
ipcMain.handle('auth:status', () => {
  const store = getAuthStore();
  return {
    loggedIn: !!store.get('sessionToken'),
    userId: store.get('userId') || null,
    email: store.get('email') || null,
    rememberMe: store.get('rememberMe', true),
    lastLogin: store.get('lastLogin') || null,
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
const LICENSE_SERVER = process.env.AETHER_LICENSE_SERVER || 'https://license.aethersystems.net/api/license';
const ADMIN_KEY = process.env.AETHER_ADMIN_KEY || '';

// Guard: admin calls require a non-empty ADMIN_KEY configured on this machine.
// ADMIN_KEY is only available in process.env (main process) — never sent to renderer.
function assertAdminKeySet() {
  if (!ADMIN_KEY) {
    throw new Error('Admin operations require AETHER_ADMIN_KEY to be set in the environment.');
  }
}

// Guard: admin IPC calls additionally require a stored session token in the auth-store.
// This prevents unauthenticated renderer code (e.g. from XSS) from triggering admin ops
// even on machines where AETHER_ADMIN_KEY is set.
function assertAdminSession() {
  assertAdminKeySet();
  try {
    const store = getAuthStore();
    const token = store.get('sessionToken');
    if (!token) throw new Error('No active session — login required for admin operations.');
  } catch (err) {
    if (err.message.includes('login required') || err.message.includes('AETHER_ADMIN_KEY')) throw err;
    throw new Error('Admin session check failed.');
  }
}

async function adminFetch(endpoint, options = {}) {
  assertAdminSession();  // requires both ADMIN_KEY env var AND a stored session token
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

// ═════════════════════════════════════════════════════════════
// Per-call re-auth on destructive admin IPCs
// ═════════════════════════════════════════════════════════════
// Prior to this hook, any renderer XSS (on an admin's logged-in machine)
// could iterate the scrambler list and revoke every license without the
// admin's knowledge. A stored session token + AETHER_ADMIN_KEY was the
// only gate, and neither is a user-gesture signal.
//
// Every destructive admin op now pops a NATIVE OS dialog. XSS cannot
// fake, drive, or suppress `dialog.showMessageBox` — only the user's
// mouse/keyboard can advance it. Non-destructive ops (overview, list)
// still go through without a prompt.
const DESTRUCTIVE_ADMIN_OPS = new Set([
  'admin:scrambler:issue',
  'admin:scrambler:revoke',
  'admin:scrambler:extend',
  'admin:cloud:issue',
  'admin:cloud:revoke',
  'admin:apikey:issue',
  'admin:apikey:revoke',
]);

async function confirmDestructiveAdmin(opName, dataPreview) {
  const win = BrowserWindow.getFocusedWindow() || mainWindow;
  const detail = dataPreview ? `Target:\n${dataPreview}` : 'No target data attached.';
  const { response } = await dialog.showMessageBox(win, {
    type: 'warning',
    title: 'Confirm Admin Operation',
    message: `This will perform: ${opName}`,
    detail: `${detail}\n\nThis is a DESTRUCTIVE license-server operation. Proceed only if you initiated it.`,
    buttons: ['Cancel', 'Proceed'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  });
  return response === 1;
}

function summarizeAdminPayload(data) {
  if (!data) return '';
  try {
    const keys = Object.keys(data).slice(0, 5);
    return keys.map(k => `  ${k}: ${String(data[k]).slice(0, 80)}`).join('\n');
  } catch { return '(unreadable payload)'; }
}

// Wrapper: gate every admin IPC through the confirmation prompt when it's
// in the destructive set. Non-destructive handlers call adminFetch directly.
function guardedAdminHandler(opName, fn) {
  return async (_e, ...args) => {
    if (DESTRUCTIVE_ADMIN_OPS.has(opName)) {
      const payload = args && args[0];
      const ok = await confirmDestructiveAdmin(opName, summarizeAdminPayload(payload));
      if (!ok) return { error: true, message: 'Operation cancelled by user', cancelled: true };
    }
    return fn(...args);
  };
}

ipcMain.handle('admin:overview', () => adminFetch('/admin/overview'));
ipcMain.handle('admin:scrambler:list', (_e, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return adminFetch(`/license/scrambler/list?${qs}`);
});
ipcMain.handle('admin:scrambler:issue',
  guardedAdminHandler('admin:scrambler:issue', (data) =>
    adminFetch('/license/scrambler/issue', { method: 'POST', body: JSON.stringify(data) })
  )
);
ipcMain.handle('admin:scrambler:revoke',
  guardedAdminHandler('admin:scrambler:revoke', (data) =>
    adminFetch('/license/scrambler/revoke', { method: 'POST', body: JSON.stringify(data) })
  )
);
ipcMain.handle('admin:scrambler:extend',
  guardedAdminHandler('admin:scrambler:extend', (data) =>
    adminFetch('/license/scrambler/extend', { method: 'POST', body: JSON.stringify(data) })
  )
);
ipcMain.handle('admin:cloud:list', (_e, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return adminFetch(`/license/cloud/list?${qs}`);
});
ipcMain.handle('admin:cloud:issue',
  guardedAdminHandler('admin:cloud:issue', (data) =>
    adminFetch('/license/cloud/issue', { method: 'POST', body: JSON.stringify(data) })
  )
);
ipcMain.handle('admin:cloud:revoke',
  guardedAdminHandler('admin:cloud:revoke', (data) =>
    adminFetch('/license/cloud/revoke', { method: 'POST', body: JSON.stringify(data) })
  )
);
ipcMain.handle('admin:apikey:list', (_e, params) => {
  const qs = new URLSearchParams(params || {}).toString();
  return adminFetch(`/license/api/list?${qs}`);
});
ipcMain.handle('admin:apikey:issue',
  guardedAdminHandler('admin:apikey:issue', (data) =>
    adminFetch('/license/api/issue', { method: 'POST', body: JSON.stringify(data) })
  )
);
ipcMain.handle('admin:apikey:revoke',
  guardedAdminHandler('admin:apikey:revoke', (data) =>
    adminFetch('/license/api/revoke', { method: 'POST', body: JSON.stringify(data) })
  )
);
