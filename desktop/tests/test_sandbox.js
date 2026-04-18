// Verifies sandbox:true is set on every BrowserWindow, and that preload.js
// stays sandbox-compatible (only requires 'electron', no Node-module imports).
//
// Sandbox:true enforces the Chromium sandbox on the renderer process. Closes
// audit finding C3: without sandbox, any post-EOL Chromium RCE would run
// with the user's full OS privileges.

const fs = require('fs');
const path = require('path');

const MAIN = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf-8');
const PRELOAD = fs.readFileSync(path.join(__dirname, '..', 'preload.js'), 'utf-8');

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  \u2713 ${n}`); };
const bad = (n, why) => { fail++; console.log(`  \u2717 ${n} \u2014 ${why}`); };

// (1) Every sandbox: declaration in main.js must be true.
const sandboxMatches = MAIN.match(/sandbox:\s*(true|false)/g) || [];
if (sandboxMatches.length === 0) {
  bad('sandbox declared', 'no sandbox: key found in main.js at all');
} else {
  for (const m of sandboxMatches) {
    if (/sandbox:\s*true/.test(m)) ok(`main.js contains ${m}`);
    else bad(`main.js contains ${m}`, 'must be true');
  }
  if (sandboxMatches.length >= 2) ok(`at least 2 sandbox:true blocks (main + terminal windows)`);
  else bad('sandbox:true count', `expected >=2, got ${sandboxMatches.length}`);
}

// (2) contextIsolation:true and nodeIntegration:false must accompany sandbox.
if (/contextIsolation:\s*true/.test(MAIN)) ok('contextIsolation: true present');
else bad('contextIsolation', 'must be true alongside sandbox');
if (/nodeIntegration:\s*false/.test(MAIN)) ok('nodeIntegration: false present');
else bad('nodeIntegration', 'must be false alongside sandbox');

// (3) preload.js must be sandbox-safe — only allowed require is 'electron'.
// Anything else (fs, path, os, child_process, crypto, etc.) will fail at
// runtime under sandbox:true.
const requires = [...PRELOAD.matchAll(/require\(['"]([^'"]+)['"]\)/g)].map(m => m[1]);
if (requires.length === 0) {
  ok('preload has no require() calls');
} else {
  const illegal = requires.filter(r => r !== 'electron');
  if (illegal.length === 0) ok(`preload only requires 'electron' (${requires.length} call${requires.length === 1 ? '' : 's'})`);
  else bad('preload requires', `illegal Node modules under sandbox: ${JSON.stringify(illegal)}`);
}

// (4) preload.js must not use Node-only process.* APIs.
// Allowed: process.contextIsolated, process.type, etc. (renderer process object).
// NOT allowed: process.env, process.versions (restricted in sandbox).
const dangerousProcessUsage = [...PRELOAD.matchAll(/\bprocess\.(env|mainModule|binding|dlopen|exit|kill)/g)];
if (dangerousProcessUsage.length === 0) ok('preload does not use Node-only process.* APIs');
else bad('preload process.*', `found: ${dangerousProcessUsage.map(m => m[0]).join(', ')}`);

// (5) preload.js must not use __dirname / __filename at runtime.
// They exist in sandboxed preload but point to the preload file location —
// a subtle footgun if used to compute resource paths expected to live in
// the app root. Flag as warning, not failure.
const dirnameUsage = (PRELOAD.match(/\b__dirname\b|\b__filename\b/g) || []).length;
if (dirnameUsage === 0) ok('preload does not rely on __dirname/__filename');
else console.log(`  \u00b7 info: preload references __dirname/__filename ${dirnameUsage}x (works under sandbox but points to preload's location)`);

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
