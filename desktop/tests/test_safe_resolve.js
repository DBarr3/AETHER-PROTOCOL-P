// Verification harness for the path-jail added to main.js.
// Extracts the safeResolve() / _canonicalize() logic and runs attack payloads.
// Run: node tests/test_safe_resolve.js

const path = require('path');
const fs = require('fs');
const os = require('os');

// ── Isolated copy of main.js security helpers (keep in sync) ───
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

// ── Test harness ────────────────────────────────────
let pass = 0, fail = 0;
const ok = (name) => { pass++; console.log(`  ✓ ${name}`); };
const bad = (name, why) => { fail++; console.log(`  ✗ ${name} — ${why}`); };
function expectBlock(name, candidate, opts) {
  try { safeResolve(candidate, opts); bad(name, `expected to throw, resolved to ${safeResolve(candidate, opts)}`); }
  catch (e) { ok(`${name} — blocked: ${e.message}`); }
}
function expectAllow(name, candidate, opts) {
  try { const r = safeResolve(candidate, opts); ok(`${name} — allowed: ${r}`); }
  catch (e) { bad(name, `expected allow, got: ${e.message}`); }
}

// ── Setup: create a fake vault for the test ────────
const tmpVault = path.join(os.tmpdir(), 'aether-jail-test-' + Date.now());
fs.mkdirSync(tmpVault, { recursive: true });
fs.writeFileSync(path.join(tmpVault, 'legit.txt'), 'hi');
grantRoot(tmpVault);

console.log('\n[1] Attack payloads — every one of these MUST be blocked:\n');

// C1 attack: traversal to Startup folder (persistence RCE)
expectBlock('traversal to Startup .lnk',
  path.join(tmpVault, '..', '..', '..', 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'pwn.lnk'),
  { allowCreate: true });

// C1 attack: absolute path far outside vault
expectBlock('absolute path outside vault',
  'C:/Windows/System32/config/SAM');

// UNC path (SMB credential harvest)
if (process.platform === 'win32') {
  expectBlock('UNC path \\\\attacker\\share', '\\\\attacker.tld\\share\\run.exe');
  expectBlock('UNC path with forward slashes', '//attacker.tld/share/run.exe');
}

// Null byte smuggle
expectBlock('null-byte in path',
  path.join(tmpVault, 'ok.txt\0/../../etc/passwd'));

// Empty / non-string
expectBlock('empty string', '');
expectBlock('null value', null);
expectBlock('object value', {});

// H2 attack: executable extension
fs.writeFileSync(path.join(tmpVault, 'payload.hta'), '<script>alert(1)</script>');
expectBlock('dangerous .hta rejection',
  path.join(tmpVault, 'payload.hta'),
  { denyExec: true });
fs.writeFileSync(path.join(tmpVault, 'payload.bat'), 'echo pwn');
expectBlock('dangerous .bat rejection',
  path.join(tmpVault, 'payload.bat'),
  { denyExec: true });

// Root-prefix confusion — adjacent dir should NOT match
const adjacent = tmpVault + '-evil';
fs.mkdirSync(adjacent, { recursive: true });
fs.writeFileSync(path.join(adjacent, 'x.txt'), 'nope');
expectBlock('adjacent dir prefix confusion',
  path.join(adjacent, 'x.txt'));

// H5 attack: symlink escape (only if we can create one)
try {
  const target = 'C:\\Windows\\System32';
  const linkInVault = path.join(tmpVault, 'escape_link');
  fs.symlinkSync(target, linkInVault, 'dir');
  expectBlock('symlink to system dir rejected at leaf',
    linkInVault);
} catch (e) {
  console.log(`  · symlink test skipped (no privilege): ${e.message}`);
}

console.log('\n[2] Legitimate access — every one MUST succeed:\n');

expectAllow('legit file in vault',
  path.join(tmpVault, 'legit.txt'));
expectAllow('vault root itself',
  tmpVault);
expectAllow('new file in vault (allowCreate)',
  path.join(tmpVault, 'new.txt'),
  { allowCreate: true });
expectAllow('new subdir (allowCreate)',
  path.join(tmpVault, 'sub', 'deep'),
  { allowCreate: true });

// Cleanup
try { fs.rmSync(tmpVault, { recursive: true, force: true }); } catch {}
try { fs.rmSync(adjacent, { recursive: true, force: true }); } catch {}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
