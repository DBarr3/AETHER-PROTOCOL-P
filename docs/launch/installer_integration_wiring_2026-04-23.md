# Installer Integration Wiring — Session F — 2026-04-23

Session F integrates Session B's three unmerged modules into the live Tauri
wizard (`desktop-installer/`). This closes the gap left when Session B
delivered the module files but not the call-sites.

Branch: `claude/installer-integration-wiring`
Base: `891765e` (main)
Cherry-pick source: `origin/claude/installer-cleanup-hygiene`
Cherry-pick: **clean** (no conflicts, no file-level fallback needed).

## Session B modules — purpose summary

- **`cleanup.rs`** — Filesystem lifecycle hooks. Three public entry points:
  - `startup_cleanup()` scans `%TEMP%` for `.part` files older than 24h and
    removes them (drains aborted prior-session downloads).
  - `shutdown_cleanup()` flushes pending state on normal exit.
  - `uninstall_teardown()` / `purge()` run a full teardown: LOCALAPPDATA +
    APPDATA + install dir + registry key (`HKCU\Software\AetherCloud`) +
    Credential Manager entries + scheduled tasks + Start-Menu/Desktop
    shortcuts, returning an `UninstallReport`.
- **`download.rs`** — Download hygiene with SHA-256 verification. The core
  helper `download_verified(url, final_path, expected_sha256, max_bytes,
  on_progress)` streams to `<final_path>.part`, hashes in-line, compares
  against the caller-supplied expected digest, and atomically `rename`s only
  on match. Three-attempt retry with exponential backoff (2s → 4s → 8s),
  60s connect timeout, 10-minute total timeout, 30s stall detection,
  500 MB hard cap, HTTPS-only. On any failure the `.part` file is deleted
  before the error returns. Also exposes `cleanup_stale_parts(dir)` used by
  `cleanup::startup_cleanup`.
- **`install_manifest.rs`** — Post-install audit + health check.
  `InstallManifest::scan_installed_files(version, install_dir)` walks the
  install tree and records every file + registry key. `health_check()`
  returns `HealthStatus::{Healthy, Degraded, Failed}` based on whether
  every recorded file still exists. Persists to
  `%LOCALAPPDATA%\AetherCloud\install_manifest.json` and
  `install_health_check.json`.

## Wiring diff summary

### `main.rs`

```
+ use aethercloud_installer::cleanup;
```

After `init_logging()` / `tracing::info!("AetherCloud Setup starting")`
(~L69) and before `tauri::Builder::default()` (~L71-79):

```rust
// Session F wiring: startup_cleanup — must run before the wizard renders.
// Wrapped in catch_unwind so cleanup failure NEVER blocks the wizard launch.
if let Err(panic) = std::panic::catch_unwind(cleanup::startup_cleanup) {
    tracing::error!(?panic, "startup_cleanup panicked — continuing to launch wizard");
}

// CLI --purge shortcut (QA aid; matches Session B's lifecycle contract).
if cleanup::check_purge_flag() {
    let report = cleanup::purge();
    tracing::info!(?report, "purge: exiting after CLI teardown");
    return;
}

// TODO(#50 telemetry re-port): a future session will add a telemetry
// command to the handler list below. Slot left empty by Session F.
```

After `.run(tauri::generate_context!())` (post-window-close):

```rust
cleanup::shutdown_cleanup();
```

The PR #50 telemetry slot at the `.invoke_handler!` macro was left exactly
as-is — commented TODO only, no handler added.

### `installer.rs`

Imports added:

```
+ use crate::download;
+ use crate::install_manifest::{HealthStatus, InstallManifest};
- use crate::payload::{self, DownloadProgress};
+ use crate::payload;
```

Payload download refactored (function body of `run_install`, ~L189-250):

- **Before**: `payload::download_with_progress(...)` returned the hash, then
  `installer.rs` manually compared it against `manifest.payload_sha256` and
  cleaned up on mismatch.
- **After**: a single call to `download::download_verified(&manifest.payload_url,
  &temp_path, &manifest.payload_sha256, max_bytes, on_progress)` — the
  helper downloads to `.part`, SHA-256s, compares, atomic-renames on success,
  and cleans the `.part` on any error. The manual `if hash != ... { remove_file
  + return Err(PayloadHashMismatch) }` block is gone; that guarantee is now
  enforced inside `download_verified`.

Post-NSIS manifest + health check (~L280-350, new block):

```rust
// After NSIS exit-0:
let scanned = InstallManifest::scan_installed_files(&manifest.version, &install_dir);
scanned.save().ok();
let health = scanned.health_check();
InstallManifest::save_health_check(&health).ok();

match health.status {
    HealthStatus::Healthy => {
        // Scratch cleanup — remove any .part files now that install is good.
        download::cleanup_stale_parts(&std::env::temp_dir());
        emit(ProgressEvent { state: "done", percent: 100, ... });
        Ok(app_path)
    }
    HealthStatus::Degraded | HealthStatus::Failed => {
        emit(ProgressEvent { state: "install_verify_failed", ... });
        Err(InstallerError::Internal("install-verify-failed: ..."))
    }
}
```

The UI can now listen for `state: "install_verify_failed"` to pop the retry
/ support dialog. `Healthy` flows straight to the existing `done` state.

### `lib.rs`

Session B's cherry-pick already registered the three modules:

```
pub mod download;
pub mod cleanup;
pub mod install_manifest;
```

No additional change required.

## `PINNED_PUBKEY` byte-for-byte proof

File: `desktop-installer/src-tauri/keys/manifest-signing.pub.bin`

**Before Session F edits:**
```
SHA-256 of file:  0d8e2c1fa0aa506a9730940e7975933381733acd521fe673358613811bee0194
Contents (hex):   b9f4d6d5460ad525b362c588 6747fde43f567e63aa8b9060 b88d6d4e82a97301
```

**After Session F edits (post `cargo check`):**
```
SHA-256 of file:  0d8e2c1fa0aa506a9730940e7975933381733acd521fe673358613811bee0194
Contents (hex):   b9f4d6d5460ad525b362c588 6747fde43f567e63aa8b9060 b88d6d4e82a97301
```

**Identical.** The fingerprint in `installer.rs` L26
(`b9f4d6d5460ad525b362c5886747fde43f567e63aa8b9060b88d6d4e82a97301`) is
unchanged, as is the `include_bytes!("../keys/manifest-signing.pub.bin")`
reference on L31. No rotation occurred. All previously-released wizards
remain trust-compatible.

## Build verification

Command: `cargo check` (dev profile, no link, no bundle) in
`desktop-installer/src-tauri/`.

Result: **clean** — `Finished dev profile [unoptimized + debuginfo] target(s)
in 5m 13s`. Zero warnings, zero errors attributable to the wizard crate.

`cargo build --release` was **skipped** — disk free was 4.1 GB after
`cargo check` completed (target dir grew ~0.9 GB during type-check). The
dispatch constraint caps any operation at 2 GB additional, and a release
build would likely exceed that. The user can run a local release build once
disk pressure eases.

Full log written locally to
`docs/launch/installer_integration_build_2026-04-23.log` — not committed
(path matches `docs/launch/*.log` in `.gitignore`). The final summary line
(`Finished dev profile [unoptimized + debuginfo] target(s) in 5m 13s`) is
reproducible with `cargo check` from `desktop-installer/src-tauri/`.

## Cargo.toml additions

**None.** All dependencies required by the cherry-picked Session B modules
(`reqwest`, `sha2`, `tokio`, `futures-util`, `thiserror`, `tracing`, `serde`,
`serde_json`) were already declared for existing modules. Session D deferred
the Tauri v2 plugin crates; none are needed for this wiring either.

## Cross-session TODOs remaining

- **PR #50 telemetry re-port** — main.rs `.invoke_handler![...]` slot is
  preserved. A future session will add a telemetry command there. Comment
  left in place to prevent accidental population.
- **Tauri v2 plugin capabilities** — Session D (PR #57) flagged that
  `tauri-plugin-fs`, `tauri-plugin-updater`, etc. are not yet declared in
  `Cargo.toml`. Session F did NOT need them — the three integration points
  use only std + tokio + reqwest + sha2, all already present. Adding the
  plugin crates remains a future session's call.
- **`payload::download_with_progress`** — now unused by `installer.rs`
  (superseded by `download::download_verified`). It's still referenced by
  its own `#[cfg(test)]` tests and by `sha256_stream`. A follow-up could
  delete it, but doing so in this PR would conflict with Session A's
  (PR #55) test-file authority over `desktop-installer/tests/**`.
- **`payload::temp_payload_path`** and **`payload::run_payload_silent`** are
  still in active use by `installer.rs` — do not remove.
- **`InstallerState::in_flight_temp`** cleanup path is now slightly
  redundant with `download_verified`'s own `.part` cleanup. The redundancy
  is defensive — safe to leave as-is.

## Files touched by Session F

| File | Delta | Notes |
|------|-------|-------|
| `desktop-installer/src-tauri/src/main.rs` | +29 lines | startup + purge + shutdown hooks |
| `desktop-installer/src-tauri/src/installer.rs` | +93 / -26 | download_verified + post-NSIS scan |
| `desktop-installer/src-tauri/src/lib.rs` | 0 | modules pre-registered via cherry-pick |
| `desktop-installer/src-tauri/Cargo.toml` | 0 | no new dependencies |
| `docs/launch/installer_integration_wiring_2026-04-23.md` | new | this file |
| `docs/launch/installer_integration_build_2026-04-23.log` | new | cargo check output |

Cherry-picked (Session B, unchanged from `origin/claude/installer-cleanup-hygiene`):
`cleanup.rs`, `download.rs`, `install_manifest.rs`, `docs/installer/lifecycle.md`,
`docs/launch/installer_filesystem_audit_2026-04-23.md`.
