use aethercloud_installer::errors::InstallerError;
use aethercloud_installer::installer::{self, InstallerState, ProgressEvent};
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager, State};

#[tauri::command]
pub async fn start_install(app: AppHandle, state: State<'_, Arc<InstallerState>>) -> Result<(), String> {
    let state_inner = state.inner().clone();
    *state_inner.cancelled.lock().await = false;
    let app_for_emit = app.clone();
    let result = installer::run_install(state_inner.clone(), move |ev: ProgressEvent| {
        let _ = app_for_emit.emit("installer://progress", ev);
    }).await;

    match result {
        Ok(_) => Ok(()),
        Err(err) => {
            // A user-initiated cancel is not a failure — emit a distinct
            // "cancelled" progress event so the frontend can route it to
            // its own UI affordance (close wizard quietly) rather than
            // showing an error banner. Other error kinds still emit the
            // generic error state.
            let ev = ProgressEvent {
                state: if matches!(err, InstallerError::Cancelled) { "cancelled" } else { "error" },
                percent: 0,
                label: if matches!(err, InstallerError::Cancelled) {
                    "Installation cancelled".into()
                } else {
                    "Installation failed".into()
                },
                detail: err.state_label().into(),
                speed: "".into(),
                error: Some(err.user_message()),
            };
            let _ = app.emit("installer://progress", ev);
            Err(err.user_message())
        }
    }
}

#[tauri::command]
pub async fn cancel_install(state: State<'_, Arc<InstallerState>>) -> Result<(), String> {
    state.inner().cancel().await;
    Ok(())
}

#[tauri::command]
pub async fn launch_app(app: AppHandle) -> Result<(), String> {
    let path = installer::installed_app_path();
    if !path.exists() {
        return Err(format!("Installed app not found at {}", path.display()));
    }
    std::process::Command::new(&path)
        .spawn()
        .map_err(|e| format!("Failed to launch: {}", e))?;
    // Close wizard window after spawn.
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.close();
    }
    Ok(())
}

#[derive(serde::Serialize)]
pub struct DetectExistingResult {
    pub installed: bool,
    pub version: Option<String>,
}

#[tauri::command]
pub async fn detect_existing() -> DetectExistingResult {
    let (installed, version) = installer::detect_existing_install();
    DetectExistingResult { installed, version }
}
