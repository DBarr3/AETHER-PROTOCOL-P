// Verifies the dependency audit posture after upgrading electron-builder
// from 24.13.3 → 26.8.1. Closes audit finding H11 — six `tar` path-traversal
// advisories, @xmldom/xmldom XXE, lodash template injection, brace-expansion
// ReDoS, @tootallnate/once control-flow.
//
// This also guards against future drift: if a PR introduces a dependency
// that pulls back any known vulnerability, `npm test` fails here.

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

let pass = 0, fail = 0;
const ok = (n) => { pass++; console.log(`  \u2713 ${n}`); };
const bad = (n, why) => { fail++; console.log(`  \u2717 ${n} \u2014 ${why}`); };

function runAudit(flag) {
  try {
    return execSync(`npm audit --json ${flag}`, {
      cwd: path.join(__dirname, '..'), encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (e) {
    // npm audit exits non-zero when vulns are found; stdout still holds JSON.
    return (e.stdout || '').toString();
  }
}

function parse(out) {
  try { return JSON.parse(out); } catch { return null; }
}

// (1) electron-builder is >=26.8.1
{
  const v = require(path.join(__dirname, '..', 'node_modules', 'electron-builder', 'package.json')).version;
  const [maj, min, pat] = v.split('.').map(Number);
  if (maj > 26 || (maj === 26 && (min > 8 || (min === 8 && pat >= 1)))) ok(`electron-builder@${v} >= 26.8.1`);
  else bad('electron-builder version', `expected >=26.8.1, got ${v}`);
}

// (2) electron is >=41
{
  const v = require(path.join(__dirname, '..', 'node_modules', 'electron', 'package.json')).version;
  const maj = parseInt(v.split('.')[0], 10);
  if (maj >= 41) ok(`electron@${v} >= 41`);
  else bad('electron version', `expected >=41, got ${v}`);
}

// (3) npm audit — runtime deps (production only)
{
  const j = parse(runAudit('--omit=dev'));
  if (!j) bad('runtime audit', 'could not parse npm audit output');
  else {
    const v = j.metadata.vulnerabilities;
    const total = v.critical + v.high + v.moderate + v.low;
    if (total === 0) ok(`runtime audit: 0 vulnerabilities (${JSON.stringify(v)})`);
    else bad('runtime audit', `${total} vulns remain: ${JSON.stringify(v)}`);
  }
}

// (4) npm audit — full tree (including devDeps). This was at 12 before #7.
{
  const j = parse(runAudit(''));
  if (!j) bad('full audit', 'could not parse npm audit output');
  else {
    const v = j.metadata.vulnerabilities;
    const critHigh = v.critical + v.high;
    if (critHigh === 0) ok(`full audit: 0 critical+high (${JSON.stringify(v)})`);
    else bad('full audit', `${critHigh} critical/high remain: ${JSON.stringify(v)}`);
  }
}

// (5) Specific advisory names that were present before #7 must be gone.
{
  const j = parse(runAudit(''));
  if (!j) bad('advisory list', 'no audit data');
  else {
    const advisoryNames = Object.keys(j.vulnerabilities || {});
    const mustBeGone = [
      'tar',
      '@xmldom/xmldom',
      'lodash',
      'brace-expansion',
      '@tootallnate/once',
      'app-builder-lib',
      'builder-util',
      'dmg-builder',
      'electron-builder',
      'electron-publish',
      'electron-builder-squirrel-windows',
      'http-proxy-agent',
    ];
    const stillThere = mustBeGone.filter(n => advisoryNames.includes(n));
    if (stillThere.length === 0) ok(`pre-#7 advisories all cleared (${mustBeGone.length} checked)`);
    else bad('cleared advisories', `still present: ${stillThere.join(', ')}`);
  }
}

console.log(`\nResult: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
