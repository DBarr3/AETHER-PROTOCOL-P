# Branded Installer Wizard (Tauri) — Design

**Status:** Draft
**Date:** 2026-04-18
**Author:** Claude + @lilbenxo

## 1. Context

The current user-facing artifact `AetherCloud-L-Setup-0.9.7.exe` is an electron-builder NSIS
installer configured with `oneClick: true`. It silently extracts the app to
`%LOCALAPPDATA%\aethercloud-l\` and auto-launches on completion.

The branded 4-page HTML wizard at `aethercloud-installer-pack/` and
`desktop/pages/branded-installer/` is currently **decorative**:

- Renders only AFTER the silent NSIS has already written files and registered an uninstaller
- `installer.js` has `installerAPI.startInstall()` stubs but no host wires them
- Progress bar on page 3 is `setInterval` + `Math.random()` theatre (installer.js:199-212)
- Consent checkbox on page 2 blocks a `setPage()` call but not a real install

**Consent gap:** A user who opens the installer and closes it before reaching the
branded UI has already had files written and an uninstaller registered — without
seeing a single piece of the consent flow we built. AetherCloud has filesystem
access, making silent install unacceptable.

## 2. Goals

1. **Pre-consent zero-write guarantee.** No persistent bytes written to the user's
   machine until they check the consent box on page 2 and click "Download & install".
2. **Keep the branded 4-page HTML UI** as the first thing the user sees.
3. **Tamper-evident payload delivery** via Ed25519-signed manifest + SHA-256 hash
   verification. Fail closed on any verification error.
4. **Single download for the user** — they download one `.exe`, the wizard handles
   the rest.
5. **Reuse existing infra.** vps1 nginx for hosting; existing code-signing pipeline
   for Windows Authenticode; existing NSIS payload (renamed) as the inner installer.

## 3. Non-Goals

- Auto-updater for the installed app (separate future project; wizard can be reused).
- Linux AppImage / macOS DMG branded wizards (unchanged for this project).
- Key rotation, multi-key trust, mirror CDN failover (v1 uses single pinned public key).
- Telemetry on install success/failure.
- Delta / differential updates.

## 4. Architecture

Two signed binaries with distinct roles:

| Artifact | Role | Size | User-Facing |
|---|---|---|---|
| `AetherCloud-Setup.exe` | Tauri wizard — UI, consent gate, payload fetch/verify/run | ~8 MB | Yes — download page links to this |
| `AetherCloud-L-Payload-0.9.7.exe` | Existing NSIS installer (renamed from `-Setup-`) | ~90 MB | No — hosted but not linked; wizard-only consumer |

### Data flow

```
User → [Download page] → AetherCloud-Setup.exe (signed wizard)
                         ↓ launched
                         Wizard renders installer.html locally
                         ↓ user walks pages 1 → 2
                         Consent checkbox + "Download & install"
                         ↓ invoke('start_install')
                         ├── GET https://aethersystems.io/downloads/manifest-latest.json
                         ├── GET https://aethersystems.io/downloads/manifest-latest.sig
                         ├── Verify sig with embedded Ed25519 public key → fail closed
                         ├── GET payload_url (stream, emit progress events)
                         ├── Compute SHA-256 → compare to manifest.payload_sha256 → fail closed
                         ├── Spawn payload with /S (silent NSIS), inherit current-user perms
                         ├── Wait for exit code 0
                         └── Page 4 shown; Launch button → spawn installed AetherCloud-L.exe
```

## 5. Wizard Implementation (Tauri v2, Rust)

### Directory layout

```
desktop-installer/                  # NEW, sibling to desktop/
├── package.json                    # npm scripts for tauri-cli convenience
├── src/                            # Frontend (mirrors aethercloud-installer-pack/)
│   ├── index.html                  # Copy of installer.html, script src updated
│   ├── installer.css
│   ├── installer.js                # Minor edits: use tauri invoke/listen
│   ├── tauri-bridge.js             # NEW: adapts window.installerAPI to Tauri invoke
│   └── agents/                     # Agent SVGs copied from pack
└── src-tauri/
    ├── Cargo.toml
    ├── tauri.conf.json
    ├── build.rs
    ├── keys/
    │   └── manifest-signing.pub.bin   # 32 bytes, Ed25519 public key (committed)
    └── src/
        ├── main.rs                 # Window + WebView2 setup, event loop
        ├── commands.rs             # #[tauri::command] for start_install, cancel_install, launch_app
        ├── installer.rs            # State machine, download loop
        ├── manifest.rs             # JSON parse, Ed25519 verify
        ├── payload.rs              # Stream download, SHA-256, spawn NSIS
        └── errors.rs               # Typed error enum with user-facing messages
```

### Why this layout

- `desktop-installer/` sits beside `desktop/` — separate build output, separate
  signing, no coupling.
- Frontend in `src/` is pure static assets; Tauri serves them via its asset protocol.
- `src-tauri/` is standard Tauri scaffolding; anyone with Rust+tauri-cli can build.
- Keys folder contains ONLY the public key (committed). Private key lives offline
  at a path configured per-release (see §7).

### Window configuration

- Fixed size 1000 × 680, non-resizable
- Frameless (custom HTML header handles the brand bar, drag region set via CSS)
- Single window, no menu, no tray
- Title bar text: "AetherCloud Setup"
- Icon: reuse `desktop/assets/icon.ico`

## 6. IPC Contract

Existing `installer.js` uses `window.installerAPI`. A thin bridge (`tauri-bridge.js`,
loaded before `installer.js`) adapts it to Tauri's `invoke` / `listen` primitives so
the existing frontend code works with ~0 changes.

### Commands (frontend → backend)

```ts
installerAPI.startInstall(): Promise<void>
  // Kicks off manifest fetch + full install flow.
  // Resolves when payload install reports success.
  // Rejects with typed error string on any failure.

installerAPI.cancelInstall(): void
  // Aborts in-flight download / install; deletes temp files; closes window.

installerAPI.launchApp(): void
  // Spawns %LOCALAPPDATA%\aethercloud-l\AetherCloud-L.exe and exits wizard.

installerAPI.detectExisting(): Promise<{ installed: boolean; version?: string }>
  // Checks %LOCALAPPDATA%\aethercloud-l\ for existing install; used on wizard startup
  // to offer Reinstall / Launch / Cancel instead of fresh install.
```

### Events (backend → frontend)

Emitted over Tauri event bus, bridged to `installerAPI.onProgress(cb)`:

```ts
{
  state: 'fetching_manifest' | 'verifying_manifest' | 'downloading_payload'
       | 'verifying_payload'  | 'installing' | 'done' | 'error',
  percent: number,        // 0-100, cumulative progress weighting all phases
  label: string,          // Top-line status text
  detail: string,         // Sub-line ("Page 3 of 4" or error detail)
  speed: string,          // Speed/throughput text
  error?: string          // Set when state === 'error'
}
```

Phase weighting (percent):
- `fetching_manifest` → 0–5%
- `verifying_manifest` → 5–7%
- `downloading_payload` → 7–85% (real bytes-downloaded tracking)
- `verifying_payload` → 85–90%
- `installing` → 90–99% (NSIS exit awaited; percent held at 95 with indeterminate label)
- `done` → 100%

## 7. Manifest Format & Signing

### `manifest-latest.json` (hosted at `https://aethersystems.io/downloads/manifest-latest.json`)

```json
{
  "version": "0.9.7",
  "payload_url": "https://aethersystems.io/downloads/AetherCloud-L-Payload-0.9.7.exe",
  "payload_sha256": "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b",
  "payload_size_bytes": 94371840,
  "min_wizard_version": "1.0.0",
  "released_at": "2026-04-18T23:00:00Z"
}
```

Rules:
- All fields required; wizard rejects manifest if any field missing, wrong type, or null.
- `payload_url` MUST use `https://` scheme — wizard rejects `http://`.
- `min_wizard_version`: if wizard's own version is below this, wizard shows "update
  required" and refuses to proceed. Enables future forced-upgrade of the wizard.
- `payload_size_bytes`: validated during download. If content-length differs by >1%
  or download exceeds declared size, abort.

### `manifest-latest.sig` (hosted beside the JSON)

Raw 64-byte Ed25519 signature over **the exact bytes of `manifest-latest.json`**
(no re-serialization, no whitespace normalization — verify what was served).

### Signing pipeline (operator workflow)

1. Generate keypair once using a companion Rust binary `tools/manifest-keygen/`:
   ```
   cargo run --bin manifest-keygen -- --out keys/
   ```
   Produces:
   - `keys/manifest-signing.priv.bin` (32 bytes, KEEP OFFLINE, do NOT commit)
   - `keys/manifest-signing.pub.bin` (32 bytes, committed to `src-tauri/keys/`)

2. Add `keys/manifest-signing.priv.bin` to `.gitignore` at repo root.

3. Per-release signing using `tools/manifest-sign/`:
   ```
   cargo run --bin manifest-sign -- \
     --key /secure/location/manifest-signing.priv.bin \
     --in release-artifacts/manifest-latest.json \
     --out release-artifacts/manifest-latest.sig
   ```

4. Upload `manifest-latest.json` + `manifest-latest.sig` + payload `.exe` to vps1
   via `scp` or rsync.

### Public key embedding

`src-tauri/build.rs` copies `keys/manifest-signing.pub.bin` into the binary at
compile time via `include_bytes!`. Verification uses the `ed25519-dalek` v2 crate
with default features (std is available in a Tauri app).

## 8. Hosting — vps1 nginx

The existing desktop build already references `https://aethersystems.io/download/latest`
(see `desktop/main.js:27`). The wizard uses the same top-level domain with a
`/downloads/` path (plural, to avoid colliding with the existing `/download/` route).

**Operator action required:** confirm whether vps1 nginx terminates TLS for
`aethersystems.io` directly, or if that domain is fronted by a different host. If
fronted elsewhere, either (a) add `/downloads/` location there and point it at vps1
via upstream proxy, or (b) use a `downloads.aethersystems.io` subdomain pointed at
vps1. Both are simple; the spec assumes (a) with path-based routing.

Path convention on vps1: `/var/www/aethercloud-downloads/`

Files:
- `manifest-latest.json`
- `manifest-latest.sig`
- `AetherCloud-Setup.exe` (current wizard — what the download page links to)
- `AetherCloud-Setup.exe.sig` (optional future: dual-sig for supply-chain defense)
- `AetherCloud-L-Payload-0.9.7.exe`
- `AetherCloud-L-Payload-0.9.7.exe.blockmap` (unused by wizard but harmless)
- Historical versions retained: `AetherCloud-L-Payload-0.9.6.exe`, etc.

Nginx location block (additive, does not change existing `/api/` routing):

```nginx
location /downloads/ {
  alias /var/www/aethercloud-downloads/;
  autoindex off;
  add_header Cache-Control "public, max-age=60" always;
  # manifest-latest.json and .sig should have low cache to roll releases fast
  location ~ ^/downloads/manifest-.* {
    add_header Cache-Control "public, max-age=60" always;
  }
  # Payloads are immutable per version - longer cache
  location ~ ^/downloads/AetherCloud-L-Payload-.*\.exe$ {
    add_header Cache-Control "public, max-age=31536000, immutable" always;
  }
}
```

No CORS configuration needed — wizard is a native Rust process using `reqwest`,
not a browser. No authentication — payload URL is public and verification is
enforced by Ed25519 signature on the manifest.

## 9. State Machine

```
 ┌─────────┐  onboard   ┌───────────┐  click+consent   ┌──────────────────┐
 │  idle   │ ─────────> │  welcome  │ ───────────────> │ fetching_manifest│
 └─────────┘            └───────────┘                  └──────────────────┘
                              ↑                                 │ ok
                              │ back                            ↓
                              └───────────────┐        ┌──────────────────┐
                                              │        │verifying_manifest│
                                              │        └──────────────────┘
                                              │                 │ ok
                                              │                 ↓
                                              │        ┌──────────────────┐
                                              │        │downloading_payload│
                                              │        └──────────────────┘
                                              │                 │ ok
                                              │                 ↓
                                              │        ┌──────────────────┐
                                              │        │verifying_payload │
                                              │        └──────────────────┘
                                              │                 │ ok
                                              │                 ↓
                                              │         ┌────────────┐
                                              │         │ installing │
                                              │         └────────────┘
                                              │                 │ exit 0
                                              │                 ↓
                                              │         ┌────────────┐
                                              │         │    done    │
                                              │         └────────────┘
                                              │                 │ Launch btn
                                              │                 ↓
                                              │        [spawn app, exit]
                                              │
                                              │ any_error_anywhere
                                              ↓
                                        ┌────────────┐
                                        │   error    │ → Cancel closes; no cleanup needed mid-dl
                                        └────────────┘
```

Consent gate:
- Page 2 "Download & install" button disabled until consent checkbox checked
  (existing `installer.js:234` behavior preserved).
- `start_install` command in Rust also re-checks: rejects if caller didn't signal
  consent. Defense in depth — frontend could be compromised by a malicious HTML
  injection; backend still enforces.

## 10. Error Handling

All errors map to a typed `InstallerError` Rust enum. User-facing copy:

| Error | State Entered | User Message | Technical Logged |
|---|---|---|---|
| Network offline | `error` | "Cannot reach AetherCloud. Check your internet connection and try again." | reqwest connect error |
| Manifest HTTP non-200 | `error` | "Install service is temporarily unavailable. Please try again in a few minutes." | HTTP status code |
| Manifest parse fail | `error` | "Install data is invalid. Please reinstall from aethersystems.io/download." | serde_json error |
| Signature mismatch | `error` | "Install verification failed. Do not proceed — download was tampered with. Please reinstall from aethersystems.io/download." | sig verify error |
| SHA-256 mismatch | `error` | "Install verification failed. Do not proceed — download was corrupted or tampered. Please retry." | hash values (truncated) |
| Payload exit non-zero | `error` | "Installation was not completed. Error code: <n>. Please contact support@aethersystems.io." | NSIS exit code + log tail |
| min_wizard_version fail | `error` | "Please download the latest AetherCloud installer from aethersystems.io/download." | current vs required version |

On entering `error`: stop all in-flight work, delete any temp files, show error UI.
User options: **Retry** (restart flow from idle) or **Close**. No silent recovery.

## 11. Build Pipeline

### Wizard build

`desktop-installer/package.json`:
```json
{
  "name": "aethercloud-installer",
  "scripts": {
    "tauri:dev": "tauri dev",
    "tauri:build": "tauri build"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2.0.0"
  }
}
```

`desktop-installer/src-tauri/tauri.conf.json` key settings:
- `productName: "AetherCloud Setup"`
- `version: "1.0.0"` (independent from app version)
- `identifier: "com.aethersystems.aethercloud.setup"`
- `bundle.active: false` — skip MSI/NSIS packaging; we want the raw compiled `.exe`
- The intermediate binary at `src-tauri/target/release/aethercloud-installer.exe`
  IS the wizard. No wrapper installer needed — this is a portable executable.
- Post-build: rename to `AetherCloud-Setup.exe`, then run `signtool sign` with the
  existing Authenticode cert (same pipeline as `desktop/build/check-signing.js`).

### Payload build (minimal change to existing)

`desktop/package.json` line 70:
```diff
- "artifactName": "AetherCloud-L-Setup-${version}.exe",
+ "artifactName": "AetherCloud-L-Payload-${version}.exe",
```

No other changes. NSIS `oneClick: true` stays — the wizard depends on it so `/S`
works reliably.

### Release automation (future, noted not specced)

A bash script `tools/release.sh` to:
1. Build payload: `cd desktop && npm run dist`
2. Compute SHA-256 of payload
3. Build manifest JSON with version, URL, SHA-256
4. Sign manifest: `cargo run --bin manifest-sign`
5. Rsync payload + manifest + sig to vps1
6. Purge nginx cache (if any) for manifest file

Not implemented in v1. Operator runs these steps manually for first release.

## 12. Testing Strategy

### Unit tests (Rust, `cargo test`)

- `manifest::parse` — valid, missing fields, wrong types, extra fields (must reject
  unknown fields — strict), `http://` URL, invalid ISO date
- `manifest::verify_signature` — valid, wrong key, truncated sig, tampered bytes
- `payload::sha256_stream` — known input → known digest
- `installer::state_machine` — all valid transitions, reject invalid

### Integration test (in-process, no external server)

Bring up a `hyper` HTTP server in-test serving a known-valid manifest + tiny
payload (`cmd.exe` stand-in — won't actually run, but we can verify the spawn is
attempted by replacing the spawn call with a trait-injected mock).

Matrix:
- Happy path: fetch → verify → download → verify → spawn → exit 0 → done
- Bad signature → error state entered, no download attempted
- Bad hash → error state entered after download, temp file cleaned up
- Payload exit non-zero → error state entered with exit code

### Manual QA (pre-release checklist)

Tester opens unsigned wizard dev build (`tauri dev`) and:
1. [ ] All 4 pages render correctly with existing visual design
2. [ ] Welcome → Next advances to Setup
3. [ ] Setup: "Download & install" disabled until consent checkbox checked
4. [ ] Setup: Back returns to Welcome; navigating forward to Setup again preserves
       consent checkbox state within same wizard run (resolved decision: preserve)
5. [ ] Setup: Download & install triggers real manifest fetch (check with Fiddler/Wireshark)
6. [ ] Download: progress bar reflects real bytes downloaded
7. [ ] Cancel mid-download: temp file deleted, wizard exits clean
8. [ ] Bad signature scenario (tester edits manifest on server): error shown, no download
9. [ ] Bad hash scenario (tester truncates payload on server): error shown, no spawn
10. [ ] Final page: Launch AetherCloud starts installed app
11. [ ] Already-installed detection: wizard offers Reinstall / Launch / Cancel on startup
12. [ ] Closing wizard via titlebar X: same as Cancel

### Clean-VM signed test (operator, post-spec)

Out of scope for in-session verification. Operator runs this post-implementation:
1. Sign both binaries with Authenticode cert
2. Upload payload + manifest + sig to vps1 `/var/www/aethercloud-downloads/`
3. Fresh Windows 11 VM, download `AetherCloud-Setup.exe` from public URL
4. Full flow: consent → download → install → launch
5. Verify SmartScreen does not warn (signed binary, established reputation)
6. Verify uninstall works via Add/Remove Programs

## 13. Security Considerations

- **HTTPS-only.** Wizard rejects any non-HTTPS URL in manifest. Nginx must have
  valid TLS cert for `aethercloud.app` (or chosen domain).
- **Signature before hash.** Wizard verifies Ed25519 signature on manifest BEFORE
  trusting the SHA-256 inside it. Order matters — otherwise attacker who swaps
  both manifest and payload bypasses hash check.
- **Temp file ACL.** Payload downloaded to `%TEMP%\aether-installer-<uuid>.exe`.
  Rust uses `tempfile` crate which sets ACL to current user only on Windows.
- **No elevation.** Wizard runs as current user. NSIS `oneClick: true` with
  `perMachine: false` installs to `%LOCALAPPDATA%` — no UAC prompt, no admin.
- **Signed wizard binary.** Both wizard and payload must be Authenticode signed.
  Unsigned binaries trigger SmartScreen which kills download conversion.
- **Fail-closed everywhere.** Any error → `error` state. Never silently skip
  verification, never retry a failed signature check, never prompt user to
  "continue anyway".
- **Public key pinning.** Manifest public key is embedded at wizard compile time.
  Rotating the key requires a new wizard release. This is intentional — keyless
  updates would undermine the trust model.
- **Consent enforcement.** Backend re-verifies consent bit was set before any
  network request; don't trust frontend alone.

## 14. Migration / Rollout

### One-time setup (before any user sees the new wizard)

1. Generate Ed25519 keypair. Commit public, store private offline.
2. Host payload + manifest + sig on vps1.
3. Build + sign wizard.
4. Smoke-test on clean VM.
5. Update `aethersystems.io/download` to link to `AetherCloud-Setup.exe` instead
   of the old `AetherCloud-L-Setup-*.exe`.

### Existing v0.9.6 / v0.9.7 users

No action required. They already have the app installed. They'll upgrade when
the app's internal update mechanism ships (out of scope here) or by re-downloading
and running the new wizard.

### Rollback plan

If wizard proves broken post-release: revert `aethercloud.app/download` link to
the old NSIS-only artifact. Users get the consent-less experience temporarily.
Fix wizard, re-release, swap link back.

## 15. Open Questions

None blocking. Resolved during brainstorming:
- ✅ Native shell: Tauri (Rust) — §5
- ✅ Hosting: vps1 nginx — §8
- ✅ Manifest signing: Ed25519 — §7
- ✅ Consent gate: checkbox + backend re-verification — §9

Deferred to v2 (noted, not specced):
- Key rotation mechanism
- Mirror CDN failover
- TLS cert pinning
- Telemetry hooks
- Release automation script

## 16. Out-of-Scope (explicit)

Stated so later PRs don't scope-creep this one:
- Auto-updater for installed app
- Cross-platform wizard equivalents (Linux AppImage, macOS DMG)
- Changes to the branded HTML design (reuse as-is)
- License key flow changes (that's the existing Sequence 1 work, separate)
- NSIS payload script changes beyond artifactName rename

---

**Spec complete.** Next steps require user approval:
1. User reviews this document for correctness / omissions
2. On approval, invoke `writing-plans` skill to produce step-by-step implementation plan
3. Execute plan under TDD discipline
