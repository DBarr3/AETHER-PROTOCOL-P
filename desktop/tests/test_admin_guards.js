// Verifies remediation #10:
//   - localStorage session fallback removed from dashboard.html
//   - authStatus() exposed via preload, returns no secrets
//   - Destructive admin IPCs are routed through a confirmation wrapper
//   - Non-destructive admin IPCs bypass the prompt
//
// This is a static/structural test — a real end-to-end Electron test of
// dialog.showMessageBox requires booting the app, which is out of scope.
// The structural checks catch the regressions we care about: the wrapper
// must reference EVERY destructive op, and no destructive op may land an
// `ipcMain.handle` without it.

const fs = require('fs');
const path = require('path');

const MAIN = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf-8');
const PRELOAD = fs.readFileSync(path.join(__dirname, '..', 'preload.js'), 'utf-8');
const DASHBOARD = fs.readFileSync(path.join(__dirname, '..', 'pages', 'dashboard.html'), 'utf-8');

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  \u2713 ${n}`); };
const bad = (n, why) => { fail++; console.log(`  \u2717 ${n} \u2014 ${why}`); };

console.log('\n[10a] localStorage session fallback removed:\n');

// Must not do: localStorage.getItem('aether_session')
if (!/localStorage\.getItem\(['"]aether_session['"]\)/.test(DASHBOARD)) {
  ok('dashboard.html does not read aether_session from localStorage');
} else {
  bad('dashboard.html', 'still reads session token from localStorage');
}

console.log('\n[10b] Scoped auth:status IPC present and exposed:\n');

if (/ipcMain\.handle\(['"]auth:status['"]/.test(MAIN)) ok('main.js registers auth:status handler');
else bad('auth:status handler', 'missing from main.js');
if (/authStatus:\s*\(\)\s*=>\s*ipcRenderer\.invoke\(['"]auth:status['"]/.test(PRELOAD)) ok('preload exposes authStatus()');
else bad('authStatus bridge', 'missing from preload.js');

// authStatus must NOT return sessionToken / licenseKey
// Extract the auth:status handler body and assert it doesn't mention them.
const statusHandler = MAIN.match(/ipcMain\.handle\(['"]auth:status['"][\s\S]*?^\}\);/m);
if (statusHandler) {
  const body = statusHandler[0];
  if (!/sessionToken/.test(body) || body.includes('loggedIn')) {
    // loggedIn: boolean is allowed; sessionToken as a raw value is not
    const returnsBool = /loggedIn:\s*!!/.test(body);
    const returnsRaw = /sessionToken:\s*store\.get\(['"]sessionToken['"]\)/.test(body);
    if (returnsBool && !returnsRaw) ok('auth:status returns loggedIn boolean, no raw token');
    else bad('auth:status leaks', 'returns sessionToken raw value');
  } else {
    ok('auth:status handler body omits secrets');
  }
  if (!/licenseKey/.test(body)) ok('auth:status does not expose licenseKey');
  else bad('auth:status leaks', 'returns licenseKey');
} else {
  bad('auth:status', 'could not locate handler body');
}

console.log('\n[10c] Destructive admin IPCs are guarded:\n');

const DESTRUCTIVE = [
  'admin:scrambler:issue',
  'admin:scrambler:revoke',
  'admin:scrambler:extend',
  'admin:cloud:issue',
  'admin:cloud:revoke',
  'admin:apikey:issue',
  'admin:apikey:revoke',
];
const NON_DESTRUCTIVE = [
  'admin:overview',
  'admin:scrambler:list',
  'admin:cloud:list',
  'admin:apikey:list',
];

// (1) Every destructive op must be wrapped in guardedAdminHandler.
for (const op of DESTRUCTIVE) {
  // Extract the handler registration block for this op
  const re = new RegExp(
    `ipcMain\\.handle\\(\\s*['"]${op.replace(/:/g, ':')}['"][\\s\\S]{0,400}?\\)\\s*;`
  );
  const match = MAIN.match(re);
  if (!match) { bad(`handler for ${op}`, 'not found'); continue; }
  if (/guardedAdminHandler/.test(match[0])) ok(`${op} routed through guardedAdminHandler`);
  else bad(`${op}`, `NOT guarded: ${match[0].slice(0, 120)}`);
}

// (2) Confirm the DESTRUCTIVE_ADMIN_OPS set in main.js lists exactly these.
const setMatch = MAIN.match(/const DESTRUCTIVE_ADMIN_OPS = new Set\(\[([\s\S]*?)\]\);/);
if (!setMatch) bad('DESTRUCTIVE_ADMIN_OPS set', 'not found in main.js');
else {
  const inSet = [...setMatch[1].matchAll(/['"]([^'"]+)['"]/g)].map(m => m[1]);
  const missing = DESTRUCTIVE.filter(d => !inSet.includes(d));
  const extra = inSet.filter(d => !DESTRUCTIVE.includes(d));
  if (missing.length === 0 && extra.length === 0) ok(`DESTRUCTIVE_ADMIN_OPS set contains exactly the ${DESTRUCTIVE.length} expected ops`);
  else bad('DESTRUCTIVE_ADMIN_OPS', `missing=${missing}, extra=${extra}`);
}

// (3) Non-destructive ops must NOT be wrapped (they should be read-only and
//     shouldn't spam prompts).
for (const op of NON_DESTRUCTIVE) {
  const re = new RegExp(
    `ipcMain\\.handle\\(\\s*['"]${op.replace(/:/g, ':')}['"][\\s\\S]{0,200}?\\)\\s*;`
  );
  const match = MAIN.match(re);
  if (!match) { bad(`handler for ${op}`, 'not found'); continue; }
  if (!/guardedAdminHandler/.test(match[0])) ok(`${op} is NOT guarded (correct — read-only)`);
  else bad(`${op}`, 'wrapped in guard unnecessarily — will spam user');
}

// (4) The confirm helper must use a NATIVE dialog (not a JS confirm() in
//     the renderer). That means it calls dialog.showMessageBox from the
//     main process — XSS cannot drive it.
if (/dialog\.showMessageBox\([\s\S]*?buttons:\s*\[\s*['"]Cancel['"]/.test(MAIN)) {
  ok('confirmDestructiveAdmin uses native dialog.showMessageBox with Cancel default');
} else {
  bad('confirm dialog', 'not using native showMessageBox');
}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
