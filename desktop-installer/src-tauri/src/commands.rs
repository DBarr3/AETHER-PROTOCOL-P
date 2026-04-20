use aethercloud_installer::errors::InstallerError;
use aethercloud_installer::installer::{self, InstallerState, ProgressEvent};
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager, State};

#[tauri::command]
pub async fn start_install(
    app: AppHandle,
    state: State<'_, Arc<InstallerState>>,
    consent: bool,
) -> Result<(), String> {
    tracing::info!(consent, "cmd: start_install invoked");

    // Spec §9 / §13: backend must re-verify consent before any network
    // request. Don't trust the frontend alone — a crafted IPC call (or a
    // compromised WebView) could otherwise bypass the checkbox.
    if !consent {
        tracing::warn!("cmd: start_install rejected — consent=false");
        let err = InstallerError::NoConsent;
        let ev = ProgressEvent {
            state: "error",
            percent: 0,
            label: "Installation blocked".into(),
            detail: err.state_label().into(),
            speed: "".into(),
            error: Some(err.user_message()),
        };
        let _ = app.emit("installer://progress", ev);
        return Err(err.user_message());
    }

    let state_inner = state.inner().clone();
    *state_inner.cancelled.lock().await = false;
    let app_for_emit = app.clone();
    let result = installer::run_install(state_inner.clone(), move |ev: ProgressEvent| {
        tracing::debug!(state = ev.state, percent = ev.percent, "cmd: emitting progress");
        let _ = app_for_emit.emit("installer://progress", ev);
    })
    .await;

    match result {
        Ok(path) => {
            tracing::info!(installed_path = %path.display(), "cmd: start_install completed successfully");
            Ok(())
        }
        Err(err) => {
            let variant_name = err.state_label();
            let is_cancel = matches!(err, InstallerError::Cancelled);
            tracing::error!(
                variant = variant_name,
                user_message = %err.user_message(),
                "cmd: start_install returning Err"
            );
            // A user-initiated cancel is not a failure — emit a distinct
            // "cancelled" progress event so the frontend can route it to
            // its own UI affordance (close wizard quietly) rather than
            // showing an error banner. Other error kinds still emit the
            // generic error state with the specific variant label.
            let ev = ProgressEvent {
                state: if is_cancel { "cancelled" } else { "error" },
                percent: 0,
                label: if is_cancel {
                    "Installation cancelled".into()
                } else {
                    "Installation failed".into()
                },
                detail: variant_name.into(),
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
    tracing::info!("cmd: cancel_install invoked");
    state.inner().cancel().await;
    Ok(())
}

#[tauri::command]
pub async fn launch_app(app: AppHandle) -> Result<(), String> {
    let path = installer::installed_app_path();
    tracing::info!(path = %path.display(), "cmd: launch_app invoked");
    if !path.exists() {
        tracing::error!(path = %path.display(), "cmd: installed app binary missing");
        return Err(format!("Installed app not found at {}", path.display()));
    }
    std::process::Command::new(&path)
        .spawn()
        .map_err(|e| {
            tracing::error!(error = ?e, path = %path.display(), "cmd: launch spawn failed");
            format!("Failed to launch: {}", e)
        })?;
    tracing::info!("cmd: installed app spawned, closing wizard window");
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
