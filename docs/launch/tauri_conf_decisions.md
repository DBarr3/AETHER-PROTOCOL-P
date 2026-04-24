# tauri.conf.json hardening decisions - 2026-04-23

**Owner of record:** Session D (branch `claude/tauri-conf-handoff`).
**Ownership rule:** All future `desktop-installer/src-tauri/tauri.conf.json`
changes go through this file's owner of record. Sessions A (tests) and B
(installer hygiene / lifecycle modules) agreed to hand off this file.
Future PRs that need to touch it should coordinate here, not patch it
inline alongside unrelated installer work.

## Scope

- File touched: `desktop-installer/src-tauri/tauri.conf.json`
- Tauri version: **v2** (`$schema` = `https://schema.tauri.app/config/2`)
- Parent spec was written against Tauri v1 keys; adaptations documented
  per-section below.

## Before / after diff

### Before (pre-hardening, on main @ 891765e)

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "AetherCloud Setup",
  "version": "1.0.0",
  "identifier": "com.aethersystems.aethercloud.setup",
  "build": {
    "frontendDist": "../src",
    "beforeDevCommand": "",
    "beforeBuildCommand": ""
  },
  "app": {
    "withGlobalTauri": true,
    "windows": [ { "title": "AetherCloud Setup", "width": 1000, "height": 680,
      "resizable": false, "decorations": false, "center": true, "visible": true } ],
    "security": {
      "csp": "default-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src https://fonts.gstatic.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self' ipc: http://ipc.localhost;"
    }
  },
  "bundle": {
    "active": false,
    "targets": ["app"],
    "icon": ["../../desktop/assets/icon.ico"]
  }
}
```

### After (this PR)

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "AetherCloud Setup",
  "version": "1.0.0",
  "identifier": "net.aethersystems.aethercloud",
  "build": {
    "frontendDist": "../src",
    "beforeDevCommand": "",
    "beforeBuildCommand": ""
  },
  "app": {
    "withGlobalTauri": false,
    "windows": [ { "title": "AetherCloud Setup", "width": 1000, "height": 680,
      "resizable": false, "decorations": false, "center": true, "visible": true } ],
    "security": {
      "csp": "default-src 'self'; connect-src 'self' ipc: http://ipc.localhost https://*.aethersystems.net https://*.posthog.com; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
    }
  },
  "bundle": {
    "active": true,
    "targets": ["nsis", "msi"],
    "identifier": "net.aethersystems.aethercloud",
    "icon": ["../../desktop/assets/icon.ico"],
    "windows": {
      "webviewInstallMode": { "type": "downloadBootstrapper", "silent": true },
      "certificateThumbprint": null,
      "digestAlgorithm": "sha256",
      "timestampUrl": "http://timestamp.digicert.com",
      "wix": { "language": ["en-US"] }
    }
  },
  "plugins": {
    "updater": {
      "active": true,
      "endpoints": [
        "https://license.aethersystems.net/updater/{{target}}/{{current_version}}"
      ],
      "dialog": true,
      "pubkey": ""
    }
  }
}
```

## Rationale per setting

| Key | Old -> new | Rationale |
| --- | --- | --- |
| `bundle.active` | `false` -> `true` | Session A's E2E tests (PR #55) depend on `cargo tauri build` producing an actual installer artifact. With `active=false`, Tauri skips the bundler and the NSIS/MSI outputs never exist. Flipping this unblocks the happy-path test in `desktop-installer/tests/e2e/happy_path.spec.ts`. |
| `bundle.targets` | `["app"]` -> `["nsis", "msi"]` | `"app"` is macOS-only. On Windows we need NSIS (primary, small download, clean uninstall) and MSI (enterprise MDM/GPO deployment). Dropping `"app"` silences a warning on Windows builds. |
| `identifier` | `com.aethersystems.aethercloud.setup` -> `net.aethersystems.aethercloud` | Consolidates to the org's `.net` TLD (matches `aethersystems.net` customer-facing domain) and drops the `.setup` suffix so the identifier represents the app, not the installer phase. Also duplicated under `bundle.identifier` for v2 explicitness. |
| `bundle.windows.webviewInstallMode` | (absent) -> `downloadBootstrapper, silent=true` | Without this, Tauri defaults to `downloadBootstrapper` but renders a visible WebView2 bootstrapper prompt inside the installer window. Silent mode integrates into the wizard UI instead. |
| `bundle.windows.wix.language` | (absent) -> `["en-US"]` | Pins the MSI language so WiX doesn't balk on machines with unusual locales. English-only until we have translated UI. |
| `bundle.windows.certificateThumbprint` | (absent) -> `null` | Explicit null placeholder. **The thumbprint is injected by CI at sign time via env var** - it must never be committed. Hardcoding a real thumbprint in the repo is effectively leaking a code-signing cert identifier into public git history. |
| `bundle.windows.digestAlgorithm` | (absent) -> `"sha256"` | SHA-1 signatures are rejected by Windows SmartScreen since 2016. Be explicit. |
| `bundle.windows.timestampUrl` | (absent) -> `http://timestamp.digicert.com` | RFC 3161 timestamp URL. Timestamped signatures remain valid after the signing cert expires. |
| `app.security.csp` | see diff | Removed `'unsafe-inline'` from `default-src` (it was there to accommodate inline `<script>` tags, but we can move to hashed inline scripts or external bundles). Removed Google Fonts from `font-src` / `style-src` - we ship fonts locally. Added `https://*.aethersystems.net` and `https://*.posthog.com` to `connect-src` so the installer can call license API and emit telemetry. Kept `ipc:` + `http://ipc.localhost` in `connect-src` - **required by Tauri v2 IPC** (dropping them breaks `invoke()`). |
| `app.withGlobalTauri` | `true` -> `false` | `withGlobalTauri` injects the full `window.__TAURI__` surface into the frontend. With it `false`, the frontend must `import { invoke } from '@tauri-apps/api'` instead. Reduces the attack surface if the frontend JS bundle is ever compromised (e.g. via a supply-chain-tainted npm dep). |
| `plugins.updater` | (absent) -> configured | Tauri v2 moved the updater from a core feature to a plugin. Configured to poll `license.aethersystems.net/updater/<target>/<current_version>` and surface a dialog on new releases. Empty `pubkey` until the user generates a signing key (see below). |

## Tauri v2 adaptations from the parent spec

The parent spec was written against Tauri v1 keys. Mappings:

- **`tauri.allowlist.*`** - does not exist in v2. Replaced by the
  **capability system** in `src-tauri/capabilities/*.json`. Hardening
  capabilities in this PR would require also adding the corresponding
  plugin crates (`tauri-plugin-fs`, `tauri-plugin-dialog`, etc.) to
  `src-tauri/Cargo.toml` and wiring them in `src-tauri/src/lib.rs` - both
  of which are **out of scope** for this session (Sessions F + B own
  `src-tauri/src/`). Current `capabilities/default.json` grants only
  `core:default`. Follow-up session should pair capability hardening with
  plugin-crate additions.
- **`tauri.updater.*`** - moved to `plugins.updater.*` in v2. Requires
  `tauri-plugin-updater` in `Cargo.toml`, which is **not currently
  present**. Config is written but inert until the crate is added and
  registered in `lib.rs` (also out of scope here).
- **`tauri.security.csp`** -> **`app.security.csp`** (v2 renamed).
- **`build.withGlobalTauri`** -> **`app.withGlobalTauri`** (v2 moved).
- **`bundle.windows.signCommand`** - parent spec flagged this as a
  user-input CI secret. Not written to the config; by convention Tauri
  picks up `signCommand` from an env var at bundle time.

## User-input items still required

These placeholders must be filled in by a human, not by a session. They
are called out so they don't land in a PR silently.

1. **`plugins.updater.pubkey`** - generate with:
   ```
   cargo install tauri-cli --locked
   cargo tauri signer generate -w ~/.tauri/aethercloud-updater.key
   ```
   Copy the public key into `plugins.updater.pubkey`. Store the private
   key in a secrets manager (1Password / GH Actions secret) - **never
   commit it**.
2. **`bundle.windows.certificateThumbprint`** - currently `null`. Set via
   CI env at sign time. Requires a decision on code-signing provider
   (DigiCert EV, SSL.com, self-hosted HSM). Thumbprint comes from
   `certutil -store My` on the signing host after the cert is installed.
3. **`bundle.windows.signCommand`** - not written to the config. If the
   team chooses to sign inside CI with a HSM-bound cert, add a
   `signCommand` that invokes the HSM tool. Otherwise Tauri uses
   `signtool.exe` with the thumbprint above.

## Verification

- JSON schema: valid against Tauri v2 schema (syntactically well-formed).
- Build: **not attempted** - see `docs/launch/tauri_build_2026-04-23.md`
  for the disk-space block (~700 MB free on C:; Rust/Tauri build needs
  multi-GB). Parent task explicitly told us to stop rather than proceed
  blindly under low disk.

## Handoff

- **Session A (PR #55):** `bundle.active` is now `true`. The E2E happy-path
  and uninstall tests should now produce real NSIS/MSI artifacts to
  exercise.
- **Session B:** installer hygiene modules (`cleanup.rs`,
  `install_manifest.rs`) should be consulted if/when updater plugin is
  wired up, so update flow cleans stale files via the same cleanup
  lifecycle.
- **Session F:** when you wire `tauri-plugin-updater` into `src/lib.rs`,
  pair it with a `pubkey` drop in this config.
