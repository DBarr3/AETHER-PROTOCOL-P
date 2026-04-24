#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use aethercloud_installer::cleanup;
use aethercloud_installer::installer::InstallerState;
use std::sync::Arc;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

/// Directory for user-visible install logs. Created if missing.
/// Returned path is written to by `tracing` so a hung install is debuggable.
fn log_dir() -> std::path::PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("."));
    base.join("AetherCloud-Setup")
}

fn init_logging() -> Option<std::path::PathBuf> {
    let dir = log_dir();
    std::fs::create_dir_all(&dir).ok()?;
    let log_path = dir.join("install.log");

    // Open append-mode so repeated install attempts don't wipe prior history.
    let file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .ok()?;

    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("aethercloud_installer=info,warn"));

    let file_layer = fmt::layer()
        .with_writer(file)
        .with_ansi(false)
        .with_target(true)
        .with_line_number(true);

    let stderr_layer = fmt::layer()
        .with_writer(std::io::stderr)
        .with_target(true);

    tracing_subscriber::registry()
        .with(filter)
        .with(file_layer)
        .with(stderr_layer)
        .init();

    Some(log_path)
}

fn main() {
    let log_path = init_logging();

    if let Some(ref p) = log_path {
        tracing::info!(path = %p.display(), "install log file ready");
    } else {
        // Logging init failed (e.g., LOCALAPPDATA unreachable). Fall back to
        // stderr-only so tracing! calls elsewhere don't no-op.
        let _ = tracing_subscriber::fmt()
            .with_env_filter(
                EnvFilter::try_from_default_env()
                    .unwrap_or_else(|_| EnvFilter::new("aethercloud_installer=info,warn")),
            )
            .try_init();
        tracing::warn!("could not open install log file; logging to stderr only");
    }

    tracing::info!(version = env!("CARGO_PKG_VERSION"), "AetherCloud Setup starting");

    // Session F wiring (PR #59): drain stale `.part` files from %TEMP% before
    // the wizard renders. Session B's `startup_cleanup()` is synchronous and
    // swallows its own errors (logs via tracing), but we guard with
    // catch_unwind anyway — cleanup failure MUST NOT prevent the wizard from
    // launching. If cleanup panics, log and continue so the user can still
    // retry or bypass.
    if let Err(panic) = std::panic::catch_unwind(cleanup::startup_cleanup) {
        tracing::error!(
            ?panic,
            "startup_cleanup panicked — continuing to launch wizard"
        );
    }

    // CLI --purge shortcut (QA aid; matches Session B's lifecycle contract).
    // If invoked, run a full teardown and exit without rendering the wizard.
    if cleanup::check_purge_flag() {
        let report = cleanup::purge();
        tracing::info!(?report, "purge: exiting after CLI teardown");
        return;
    }

    // TODO(#50 telemetry re-port): a future session will add a telemetry
    // command to the handler list below. That slot is intentionally left
    // empty by Session F — do not populate here.
    tauri::Builder::default()
        .manage(Arc::new(InstallerState::default()))
        .invoke_handler(tauri::generate_handler![
            commands::start_install,
            commands::cancel_install,
            commands::launch_app,
            commands::detect_existing,
        ])
        .run(tauri::generate_context!())
        .expect("error while running AetherCloud Setup");

    // Session F: flush pending state on normal exit. Note: Tauri's `.run()`
    // blocks until the window closes, so this runs after the UI teardown.
    cleanup::shutdown_cleanup();
}
