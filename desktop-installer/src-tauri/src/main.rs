#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use aethercloud_installer::installer::InstallerState;
use std::sync::Arc;

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter("aethercloud_installer=info,warn")
        .init();

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
