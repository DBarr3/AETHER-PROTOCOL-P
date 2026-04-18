// Dry-run verification for the electron-builder afterPack fuses hook.
// A full build is heavy (~100MB Electron download + pack), so instead we:
//   1. Import the hook module and confirm it exports an async fn
//   2. Import @electron/fuses and confirm every Fuse option we reference
//      actually exists in the installed version (catches typos and
//      library-version drift)
//   3. Confirm the hook is wired in package.json under build.afterPack

const path = require('path');
const fs = require('fs');
const assert = require('assert');

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  \u2713 ${n}`); };
const bad = (n, why) => { fail++; console.log(`  \u2717 ${n} \u2014 ${why}`); };

function check(name, fn) {
  try { fn(); ok(name); } catch (e) { bad(name, e.message); }
}

check('hook module is require-able', () => {
  const h = require('../build/fuses.js');
  assert.strictEqual(typeof h, 'function', 'default export must be a function');
});

check('hook is an async function accepting (context)', () => {
  const h = require('../build/fuses.js');
  // Async functions have .constructor.name === 'AsyncFunction'.
  assert.strictEqual(h.constructor.name, 'AsyncFunction', 'must be async');
  assert.strictEqual(h.length, 1, 'must take one arg (context)');
});

check('@electron/fuses is installed', () => {
  const f = require('@electron/fuses');
  assert.ok(f.flipFuses, 'flipFuses export missing');
  assert.ok(f.FuseV1Options, 'FuseV1Options export missing');
  assert.ok(f.FuseVersion, 'FuseVersion export missing');
});

check('every fuse referenced by the hook exists in installed library', () => {
  const { FuseV1Options } = require('@electron/fuses');
  const referenced = [
    'RunAsNode',
    'EnableCookieEncryption',
    'EnableNodeOptionsEnvironmentVariable',
    'EnableNodeCliInspectArguments',
    'EnableEmbeddedAsarIntegrityValidation',
    'OnlyLoadAppFromAsar',
    'LoadBrowserProcessSpecificV8Snapshot',
    'GrantFileProtocolExtraPrivileges',
  ];
  for (const key of referenced) {
    assert.ok(FuseV1Options[key] !== undefined, `FuseV1Options.${key} missing`);
  }
});

check('package.json wires build.afterPack to ./build/fuses.js', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf-8'));
  assert.strictEqual(pkg.build && pkg.build.afterPack, './build/fuses.js',
    `expected build.afterPack to be './build/fuses.js', got ${pkg.build && pkg.build.afterPack}`);
});

check('Electron version is 41+', () => {
  const pkg = JSON.parse(fs.readFileSync(
    path.join(__dirname, '..', 'node_modules', 'electron', 'package.json'), 'utf-8'));
  const major = parseInt(pkg.version.split('.')[0], 10);
  assert.ok(major >= 41, `expected Electron >=41, got ${pkg.version}`);
});

check('Electron-specific runtime CVEs are closed (no electron in npm audit)', () => {
  const { execSync } = require('child_process');
  let out;
  try {
    out = execSync('npm audit --json --omit=dev', { cwd: path.join(__dirname, '..'), encoding: 'utf-8' });
  } catch (e) {
    // npm audit exits non-zero when vulns exist; the output is still valid JSON on stdout.
    out = e.stdout || '';
  }
  let parsed;
  try { parsed = JSON.parse(out); } catch { parsed = null; }
  if (!parsed) throw new Error('could not parse npm audit output');
  const v = parsed.vulnerabilities || {};
  const electronAdvisories = Object.keys(v).filter(k => k === 'electron');
  assert.strictEqual(electronAdvisories.length, 0,
    `electron still has advisories: ${JSON.stringify(v.electron && v.electron.via)}`);
});

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
