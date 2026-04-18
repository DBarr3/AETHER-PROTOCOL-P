// Verifies the signing gate (build/check-signing.js) and the hardened
// electron-builder signing config in package.json. These fixes close
// audit finding C4 (unsigned Windows installer + perMachine:false).

const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SCRIPT = path.join(__dirname, '..', 'build', 'check-signing.js');
const PKG = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf-8'));
const NODE = process.execPath;

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  \u2713 ${n}`); };
const bad = (n, why) => { fail++; console.log(`  \u2717 ${n} \u2014 ${why}`); };

// Run check-signing.js with a specific env; returns { code, stderr }.
function run(env) {
  // Build a clean env: remove any already-set CSC vars that would leak from
  // the shell, then layer the test's env on top.
  const clean = { ...process.env };
  for (const k of Object.keys(clean)) {
    if (k.startsWith('CSC_') || k.startsWith('WIN_CSC_') || k === 'AETHER_ALLOW_UNSIGNED') {
      delete clean[k];
    }
  }
  const finalEnv = { ...clean, ...env };
  try {
    execFileSync(NODE, [SCRIPT], { env: finalEnv, stdio: 'pipe' });
    return { code: 0, stderr: '' };
  } catch (e) {
    return { code: e.status, stderr: (e.stderr || Buffer.alloc(0)).toString() };
  }
}

console.log('\n[1] Signing gate — exit code matrix:\n');

// (1) No env → must fail with exit 2.
{
  const { code } = run({});
  if (code === 2) ok('no signing config → exit 2');
  else bad('no signing config', `expected 2, got ${code}`);
}

// (2) Escape hatch → must succeed with exit 0.
{
  const { code } = run({ AETHER_ALLOW_UNSIGNED: '1' });
  if (code === 0) ok('AETHER_ALLOW_UNSIGNED=1 → exit 0');
  else bad('escape hatch', `expected 0, got ${code}`);
}

// (3) CSC_LINK missing file → must fail with exit 2.
{
  const { code, stderr } = run({ CSC_LINK: 'C:/nope/missing.pfx', CSC_KEY_PASSWORD: 'x' });
  if (code === 2 && /missing file/.test(stderr)) ok('CSC_LINK points at missing file → exit 2');
  else bad('CSC_LINK missing file', `expected 2 with 'missing file', got ${code}: ${stderr.slice(0, 120)}`);
}

// (4) CSC_LINK with no password → must fail.
{
  const fakeCert = path.join(require('os').tmpdir(), 'fake-' + Date.now() + '.pfx');
  fs.writeFileSync(fakeCert, Buffer.from([0]));
  try {
    const { code, stderr } = run({ CSC_LINK: fakeCert });
    if (code === 2 && /CSC_KEY_PASSWORD is missing/.test(stderr)) ok('CSC_LINK without password → exit 2');
    else bad('CSC_LINK no password', `expected 2 with 'missing', got ${code}: ${stderr.slice(0, 120)}`);
  } finally {
    try { fs.unlinkSync(fakeCert); } catch {}
  }
}

// (5) CSC_LINK + password + existing file → must succeed.
{
  const fakeCert = path.join(require('os').tmpdir(), 'fake-' + Date.now() + '.pfx');
  fs.writeFileSync(fakeCert, Buffer.from([0]));
  try {
    const { code } = run({ CSC_LINK: fakeCert, CSC_KEY_PASSWORD: 's3cret' });
    if (code === 0) ok('CSC_LINK + CSC_KEY_PASSWORD on an existing file → exit 0');
    else bad('signed config', `expected 0, got ${code}`);
  } finally {
    try { fs.unlinkSync(fakeCert); } catch {}
  }
}

// (6) CSC_IDENTITY_AUTO_DISCOVERY=true → must succeed.
{
  const { code } = run({ CSC_IDENTITY_AUTO_DISCOVERY: 'true' });
  if (code === 0) ok('CSC_IDENTITY_AUTO_DISCOVERY=true → exit 0');
  else bad('keychain auto-discovery', `expected 0, got ${code}`);
}

// (7) URL CSC_LINK + password → must succeed (can't verify https reachable).
{
  const { code } = run({ CSC_LINK: 'https://example.com/cert.pfx', CSC_KEY_PASSWORD: 's' });
  if (code === 0) ok('https CSC_LINK + password → exit 0');
  else bad('https CSC_LINK', `expected 0, got ${code}`);
}

console.log('\n[2] package.json signing configuration:\n');

const win = PKG.build.win;
if (!win.signAndEditExecutable === false || win.signAndEditExecutable === undefined) ok('win.signAndEditExecutable not explicitly disabled');
else bad('win.signAndEditExecutable', 'must not be set to false');
if (win.sign === null) bad('win.sign', 'must not be set to null (forces skip)');
else ok('win.sign is not forced to null');
if (Array.isArray(win.signingHashAlgorithms) && win.signingHashAlgorithms.includes('sha256')) ok('signingHashAlgorithms includes sha256');
else bad('signingHashAlgorithms', `missing sha256, got ${JSON.stringify(win.signingHashAlgorithms)}`);
if (typeof win.rfc3161TimeStampServer === 'string' && /^https?:\/\//.test(win.rfc3161TimeStampServer)) ok('rfc3161TimeStampServer configured');
else bad('rfc3161TimeStampServer', 'missing or invalid URL');
if (win.verifyUpdateCodeSignature === true) ok('verifyUpdateCodeSignature: true');
else bad('verifyUpdateCodeSignature', `expected true, got ${win.verifyUpdateCodeSignature}`);

if (PKG.build.nsis.perMachine === true) ok('nsis.perMachine: true (admin-only writes)');
else bad('nsis.perMachine', `expected true, got ${PKG.build.nsis.perMachine}`);

// Scripts must route through the gate.
const scripts = PKG.scripts || {};
for (const s of ['build:win', 'dist', 'dist:signed']) {
  if ((scripts[s] || '').includes('check-signing.js')) ok(`script "${s}" invokes check-signing gate`);
  else bad(`script "${s}"`, `does not invoke check-signing.js: ${scripts[s]}`);
}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
