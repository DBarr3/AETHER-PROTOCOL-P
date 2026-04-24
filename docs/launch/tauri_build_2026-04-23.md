Tauri build verification log - 2026-04-23
==========================================

Environment:
  - Host: Windows 10 Home 10.0.19045
  - Rust toolchain: cargo 1.95.0 (f2d3ce0bd 2026-03-21)
  - Tauri crate version: 2 (per Cargo.toml)
  - Schema: https://schema.tauri.app/config/2 (Tauri v2)
  - Working dir: desktop-installer/src-tauri/

Disk space check (df -h /c):
  Filesystem      Size  Used Avail Use% Mounted on
  C:              1.9T  1.9T  840M 100% /c

STATUS: BUILD NOT ATTEMPTED - DISK SPACE BELOW SAFE THRESHOLD

Reason:
  Session B's filesystem audit (2026-04-23) flagged 351 MB free on C:.
  At time of this session (a few hours later) available is 840 MB.
  A cargo/Tauri build requires multi-GB for target/ (incremental compile
  cache, deps, bundled WebView2 downloads, NSIS/WIX artifacts). Running
  `cargo tauri build --target x86_64-pc-windows-msvc --release` or even
  `cargo check` with cold caches risks:
    (a) Filling C: and leaving the system wedged.
    (b) Partial build artifacts that require manual cleanup.
  Per parent task spec: "If disk space issue ... STOP and report - do NOT
  proceed blindly."

JSON validation (config-only):
  $ python -m json.tool desktop-installer/src-tauri/tauri.conf.json
  => JSON valid (syntactically well-formed, schema v2 keys)

Changes applied (config only, no source changes):
  - bundle.active: false -> true
  - bundle.targets: ["app"] -> ["nsis", "msi"]
  - identifier: "com.aethersystems.aethercloud.setup" -> "net.aethersystems.aethercloud"
    (Note: also set bundle.identifier for explicitness in Tauri v2)
  - bundle.windows.* (new): webviewInstallMode, certificateThumbprint=null,
    digestAlgorithm="sha256", timestampUrl=digicert, wix.language=["en-US"]
  - app.security.csp: tightened (removed 'unsafe-inline' from default-src,
    added *.aethersystems.net and *.posthog.com to connect-src, kept
    ipc: / http://ipc.localhost required by Tauri IPC in v2)
  - app.withGlobalTauri: true -> false
  - plugins.updater (new): active=true, endpoint to license.aethersystems.net,
    dialog=true, pubkey="" (TODO: generate via `tauri signer generate`)

Tauri v2 adaptation notes:
  Parent spec referenced Tauri v1 structure (tauri.allowlist.*, tauri.updater.*,
  tauri.security.csp). This project is on Tauri v2 (schema v2). Adaptations:
  - `tauri.security.csp` -> `app.security.csp`
  - `tauri.updater.*` -> `plugins.updater.*` (requires tauri-plugin-updater
    crate in Cargo.toml, which is NOT currently present - flagged in
    tauri_conf_decisions.md as user-input item).
  - `tauri.allowlist.*` -> Tauri v2 capability system in
    src-tauri/capabilities/*.json (not modified here because parent task
    forbids touching src-tauri/src/**; capabilities must be paired with
    plugin crate additions). default.json currently grants only
    "core:default". Hardening of capabilities belongs in a follow-up
    session that can also add plugin crates.
  - `build.withGlobalTauri` -> `app.withGlobalTauri` (v2 moved this key).

Recommended follow-up build command (when disk >= 10 GB free):
  $ cd desktop-installer
  $ cargo tauri build --target x86_64-pc-windows-msvc --release --verbose \
      2>&1 | tee docs/launch/tauri_build_<date>.log

  If signing cert/pubkey missing, fall through to:
  $ cargo tauri build --no-bundle --verbose

End of log.
