#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

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
}
