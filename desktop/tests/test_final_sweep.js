// Final-sweep verification for the post-#10 Electron-side fixes:
//   M4  — setWindowOpenHandler + will-navigate guards on both BrowserWindows
//   H3  — DOMPurify vendored and wired into dashboard.html
//   Follow-up #10 — apiCall() token-free bridge exposed in preload

const fs = require('fs');
const path = require('path');

const MAIN = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf-8');
const PRELOAD = fs.readFileSync(path.join(__dirname, '..', 'preload.js'), 'utf-8');
const DASHBOARD = fs.readFileSync(path.join(__dirname, '..', 'pages', 'dashboard.html'), 'utf-8');

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  \u2713 ${n}`); };
const bad = (n, why) => { fail++; console.log(`  \u2717 ${n} \u2014 ${why}`); };

console.log('\n[M4] Navigation guards on BrowserWindows:\n');

// setWindowOpenHandler must appear >= 2 times (one per BrowserWindow).
const openHandlers = (MAIN.match(/setWindowOpenHandler\(/g) || []).length;
if (openHandlers >= 2) ok(`setWindowOpenHandler present on both windows (${openHandlers} occurrences)`);
else bad('setWindowOpenHandler', `expected >=2, got ${openHandlers}`);

// will-navigate listener must appear >= 2 times.
const willNav = (MAIN.match(/on\(['"]will-navigate['"]/g) || []).length;
if (willNav >= 2) ok(`will-navigate guard present on both windows (${willNav} occurrences)`);
else bad('will-navigate guard', `expected >=2, got ${willNav}`);

// The setWindowOpenHandler callback must deny the open.
if (/setWindowOpenHandler[\s\S]{0,300}?action:\s*['"]deny['"]/.test(MAIN)) {
  ok('setWindowOpenHandler returns { action: "deny" }');
} else {
  bad('setWindowOpenHandler', 'does not deny the open');
}

// isSafeExternalUrl must gate the shell.openExternal call from the handler.
if (/setWindowOpenHandler[\s\S]{0,200}?isSafeExternalUrl/.test(MAIN)) {
  ok('external-URL allowlist (isSafeExternalUrl) is enforced before shell.openExternal');
} else {
  bad('external-URL allowlist', 'not enforced in setWindowOpenHandler');
}

// will-navigate callback must call event.preventDefault when URL is remote.
if (/on\(['"]will-navigate['"][\s\S]{0,300}?preventDefault\(\)/.test(MAIN)) {
  ok('will-navigate handler calls event.preventDefault() on remote URLs');
} else {
  bad('will-navigate', 'does not preventDefault');
}

console.log('\n[H3] DOMPurify wired into dashboard.html:\n');

// Vendor file must exist on disk.
const vendorPath = path.join(__dirname, '..', 'pages', 'vendor', 'dompurify.min.js');
if (fs.existsSync(vendorPath)) ok('pages/vendor/dompurify.min.js present on disk');
else bad('DOMPurify vendor file', 'missing');

// The vendor file must be loaded via <script src=...> in dashboard.html.
if (/<script[^>]+src=["']vendor\/dompurify\.min\.js["']/.test(DASHBOARD)) {
  ok('dashboard.html loads vendor/dompurify.min.js via <script>');
} else {
  bad('dashboard.html DOMPurify load', 'no script tag found');
}

// window.safeHTML helper must be defined.
if (/window\.safeHTML\s*=\s*function/.test(DASHBOARD)) {
  ok('window.safeHTML helper defined in dashboard.html');
} else {
  bad('safeHTML helper', 'not defined');
}

// safeHTML must use DOMPurify.sanitize with a FORBID_TAGS list.
if (/safeHTML[\s\S]{0,800}?DOMPurify\.sanitize[\s\S]{0,800}?FORBID_TAGS[\s\S]{0,200}?['"]script['"]/.test(DASHBOARD)) {
  ok('safeHTML forbids <script> via DOMPurify FORBID_TAGS');
} else {
  bad('safeHTML FORBID_TAGS', 'does not forbid script');
}

// The renderMarkdown sinks that the audit called out must now route
// through safeHTML.
const sanitizedSinks = (DASHBOARD.match(/window\.safeHTML\(renderMarkdown\(/g) || []).length;
if (sanitizedSinks >= 2) ok(`renderMarkdown sinks routed through safeHTML (${sanitizedSinks} call sites)`);
else bad('renderMarkdown sinks', `expected >=2 sanitized sites, got ${sanitizedSinks}`);

console.log('\n[Follow-up #10] Token-free API bridge exposed:\n');

if (/apiCall:\s*\(endpoint,\s*options\s*=\s*\{\}\)\s*=>\s*apiFetch/.test(PRELOAD)) {
  ok('preload exposes aetherAPI.apiCall(endpoint, options) → apiFetch');
} else {
  bad('apiCall bridge', 'not exposed');
}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
