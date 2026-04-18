// Verifies that every shipped renderer HTML page carries a strict CSP
// meta tag and that the policy blocks the XSS-amplifier vectors that the
// audit flagged (remote scripts, eval, exfil fetches to attacker.tld,
// plugins, iframe embedding).
//
// This test *parses* the policy strings and inspects each directive —
// it doesn't boot Electron (too heavy). A future step (#6 / #5) could
// add a real Puppeteer-based CSP violation test.

const fs = require('fs');
const path = require('path');

const PAGES = ['login.html','dashboard.html','terminal.html','installer.html','report-panel.html'];
const PAGES_DIR = path.join(__dirname, '..', 'pages');

let pass = 0, fail = 0;
const ok = (name) => { pass++; console.log(`  \u2713 ${name}`); };
const bad = (name, why) => { fail++; console.log(`  \u2717 ${name} \u2014 ${why}`); };

function parseCsp(html) {
  // Match content="..." — the value contains single quotes (e.g. 'self'),
  // so the char class must stop at double-quote only.
  const m = html.match(/<meta[^>]+http-equiv=["']Content-Security-Policy["'][^>]+content="([^"]+)"/i)
         || html.match(/<meta[^>]+http-equiv=["']Content-Security-Policy["'][^>]+content='([^']+)'/i);
  if (!m) return null;
  const directives = {};
  m[1].split(';').map(s => s.trim()).filter(Boolean).forEach(d => {
    const [name, ...vals] = d.split(/\s+/);
    directives[name.toLowerCase()] = vals;
  });
  return directives;
}

function assertContains(dirs, key, value, page) {
  const v = (dirs[key] || []).map(x => x.toLowerCase());
  if (v.includes(value.toLowerCase())) ok(`${page} ${key} includes ${value}`);
  else bad(`${page} ${key}`, `expected '${value}', got ${JSON.stringify(v)}`);
}
function assertExcludes(dirs, key, value, page) {
  const v = (dirs[key] || []).map(x => x.toLowerCase());
  if (!v.includes(value.toLowerCase())) ok(`${page} ${key} excludes ${value}`);
  else bad(`${page} ${key}`, `must NOT include '${value}'`);
}
function assertPresent(dirs, key, page) {
  if (dirs[key]) ok(`${page} directive '${key}' present`);
  else bad(`${page}`, `missing directive '${key}'`);
}

for (const page of PAGES) {
  console.log(`\n[${page}]`);
  const html = fs.readFileSync(path.join(PAGES_DIR, page), 'utf-8');
  const dirs = parseCsp(html);
  if (!dirs) { bad(page, 'no CSP meta tag found'); continue; }

  // Required directives
  assertPresent(dirs, 'default-src', page);
  assertPresent(dirs, 'script-src', page);
  assertPresent(dirs, 'connect-src', page);
  assertPresent(dirs, 'object-src', page);
  assertPresent(dirs, 'base-uri', page);
  assertPresent(dirs, 'frame-ancestors', page);

  // script-src MUST NOT allow 'unsafe-eval' — this blocks eval/Function/renderMarkdown→RCE
  assertExcludes(dirs, 'script-src', "'unsafe-eval'", page);
  // script-src MUST NOT allow remote http: or https: wildcard scripts
  assertExcludes(dirs, 'script-src', 'https:', page);
  assertExcludes(dirs, 'script-src', '*', page);

  // connect-src MUST NOT allow * — that would permit exfil to attacker.tld
  assertExcludes(dirs, 'connect-src', '*', page);
  // connect-src MUST include the legitimate API host
  assertContains(dirs, 'connect-src', 'https://api.aethersystems.net', page);

  // object-src MUST be 'none' (blocks Flash/plugin bypass)
  assertContains(dirs, 'object-src', "'none'", page);
  // base-uri MUST be 'none' (blocks <base> tag redirecting relative fetches)
  assertContains(dirs, 'base-uri', "'none'", page);
  // frame-ancestors 'none' (clickjacking defense)
  assertContains(dirs, 'frame-ancestors', "'none'", page);
  // form-action 'none' if present (prevents form exfil)
  if (dirs['form-action']) assertContains(dirs, 'form-action', "'none'", page);
}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
