#!/usr/bin/env node
// Pre-build gate — refuses to produce a build unless code signing is
// configured (or an explicit opt-out env var is set).
//
// An unsigned Windows installer triggers SmartScreen "Unknown Publisher"
// warnings and, crucially, offers no integrity proof — a malware-replaced
// exe in %LOCALAPPDATA%\Programs\AetherCloud-L is undetectable by the OS.
// Prior to this gate, `npm run dist` would silently drop an unsigned
// artifact. Now the build fails loud and early.
//
// Recognized signing config (any one is sufficient):
//   CSC_LINK              — path or https URL to .pfx / .p12 cert
//   WIN_CSC_LINK          — Windows-specific override
//   CSC_IDENTITY_AUTO_DISCOVERY=true (macOS keychain auto-discovery)
//
// Escape hatch — for local dev only:
//   AETHER_ALLOW_UNSIGNED=1
// This is how `npm run dist:unsigned` is allowed to succeed. CI must never
// set this.

const fs = require('fs');
const path = require('path');

const BOLD = '\x1b[1m', RED = '\x1b[31m', GREEN = '\x1b[32m',
      YELLOW = '\x1b[33m', DIM = '\x1b[2m', RESET = '\x1b[0m';

function hasSigningConfig() {
  const cscLink = process.env.CSC_LINK || process.env.WIN_CSC_LINK;
  if (cscLink) {
    // Require password when cert is a .pfx/.p12 on disk or URL.
    const pwd = process.env.CSC_KEY_PASSWORD || process.env.WIN_CSC_KEY_PASSWORD;
    if (!pwd) {
      return { ok: false, reason: 'CSC_LINK is set but CSC_KEY_PASSWORD is missing' };
    }
    // If it's a file path, verify the file actually exists.
    if (!/^https?:\/\//i.test(cscLink) && !fs.existsSync(cscLink)) {
      return { ok: false, reason: `CSC_LINK points to a missing file: ${cscLink}` };
    }
    return { ok: true, via: 'CSC_LINK' };
  }
  if (process.env.CSC_IDENTITY_AUTO_DISCOVERY === 'true') {
    return { ok: true, via: 'CSC_IDENTITY_AUTO_DISCOVERY' };
  }
  return { ok: false, reason: 'no CSC_LINK or keychain auto-discovery configured' };
}

function main() {
  console.log(`${DIM}[check-signing] Verifying code-signing configuration...${RESET}`);

  if (process.env.AETHER_ALLOW_UNSIGNED === '1') {
    console.log(`${YELLOW}${BOLD}[check-signing]  WARNING: AETHER_ALLOW_UNSIGNED=1 — building an UNSIGNED installer.${RESET}`);
    console.log(`${YELLOW}  This build will trigger SmartScreen on every user's machine and`);
    console.log(`  provides no integrity proof. Use for local dev only. NEVER ship this.${RESET}`);
    return;
  }

  const sig = hasSigningConfig();
  if (sig.ok) {
    console.log(`${GREEN}[check-signing] OK — signing via ${sig.via}${RESET}`);
    return;
  }

  console.error('');
  console.error(`${RED}${BOLD}[check-signing] FAIL — code signing is not configured.${RESET}`);
  console.error('');
  console.error(`  Reason: ${sig.reason}`);
  console.error('');
  console.error(`  ${BOLD}To ship a signed Windows installer you must set:${RESET}`);
  console.error(`    CSC_LINK            = path or https URL to your .pfx / .p12 cert`);
  console.error(`    CSC_KEY_PASSWORD    = password for the cert`);
  console.error('');
  console.error(`  Or for local dev only (triggers SmartScreen, NOT shippable):`);
  console.error(`    npm run dist:unsigned`);
  console.error('');
  console.error(`  Reference: https://www.electron.build/code-signing.html`);
  process.exit(2);
}

main();
