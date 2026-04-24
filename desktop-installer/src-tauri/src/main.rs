#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use aethercloud_installer::cleanup;
use aethercloud_installer::installer::InstallerState;
use aethercloud_installer::telemetry::{self, Event, EventProperties};
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

    // Session I (PR #50 funnel re-port): fire the top-of-funnel
    // WizardLaunched event before the Tauri event loop spins up. Uses
    // capture_fire_and_forget — no runtime yet exists, so this takes
    // the pre-runtime branch (detached OS thread w/ current-thread
    // runtime). Zero chance of blocking the wizard render; the POST
    // is network-bound and telemetry is disabled entirely in debug
    // builds and when no PostHog key is configured.
    telemetry::capture_fire_and_forget(
        Event::WizardLaunched,
        EventProperties::new(),
    );

    // Session H (PR #60): plugin registration. In Tauri v2 each plugin
    // crate must be explicitly `.plugin(...)` registered at Builder time;
    // the old v1 `allowlist` config is gone. Actual permission scoping
    // lives in `capabilities/*.json`. Order: plugins first (so their
    // state is available when `.manage()` / invoke handlers fire), then
    // app state, then our own invoke handlers.
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Arc::new(InstallerState::default()))
        .invoke_handler(tauri::generate_handler![
            commands::start_install,
            commands::cancel_install,
            commands::launch_app,
            commands::detect_existing,
        ])
        .run(tauri::generate_context!())
        .expect("error while running AetherCloud Setup");

    // Session I (PR #50): bottom-of-funnel WizardClosed event. The Tauri
    // runtime has exited at this point so we take the pre-runtime branch
    // again (detached OS thread). `closed_reason=normal_exit` means the
    // event loop returned cleanly — error/cancel paths already emitted
    // InstallFailed / cancelled events from commands.rs, so "normal_exit"
    // here captures the union of success and user-closed-after-success.
    telemetry::capture_fire_and_forget(
        Event::WizardClosed,
        EventProperties::new().with_closed_reason("normal_exit"),
    );

    // Session F: flush pending state on normal exit. Note: Tauri's `.run()`
    // blocks until the window closes, so this runs after the UI teardown.
    cleanup::shutdown_cleanup();
}
