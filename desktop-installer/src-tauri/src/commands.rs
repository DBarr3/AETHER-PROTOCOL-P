use aethercloud_installer::errors::InstallerError;
use aethercloud_installer::installer::{self, InstallerState, ProgressEvent};
use aethercloud_installer::telemetry::{self, Event, EventProperties};
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
        if let Err(emit_err) = app.emit("installer://progress", ev) {
            tracing::warn!(error = ?emit_err, "cmd: emit() failed on NoConsent path");
        }
        return Err(err.user_message());
    }

    let state_inner = state.inner().clone();
    *state_inner.cancelled.lock().await = false;

    // Session I (PR #50): InstallerStarted fires AFTER consent re-verify
    // passes but BEFORE the heavy work begins. Matches the moment the
    // user commits to the install. Rust-side so a compromised WebView
    // can't suppress it. Fire-and-forget — a telemetry stall must not
    // delay the install.
    telemetry::capture_fire_and_forget(
        Event::InstallerStarted,
        EventProperties::new(),
    );

    let app_for_emit = app.clone();
    let result = installer::run_install(state_inner.clone(), move |ev: ProgressEvent| {
        tracing::debug!(state = ev.state, percent = ev.percent, "cmd: emitting progress");
        if let Err(emit_err) = app_for_emit.emit("installer://progress", ev) {
            tracing::warn!(error = ?emit_err, "cmd: emit() failed — capability missing?");
        }
    })
    .await;

    match result {
        Ok(path) => {
            tracing::info!(installed_path = %path.display(), "cmd: start_install completed successfully");
            // Session I (PR #50): terminal success event. `redact_path`
            // reduces the concrete user-home path to a static layout
            // label so we learn which NSIS install layout the wizard
            // ended on without leaking user names.
            telemetry::capture_fire_and_forget(
                Event::InstallCompleted,
                EventProperties::new()
                    .with_percent(100)
                    .with_error_code(telemetry::redact_path(&path)),
            );
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
            // Session I (PR #50): terminal failure event. `variant_name`
            // is `InstallerError::state_label()` — a `&'static str`
            // from a fixed enum (NOT the Display string, which may
            // contain URLs/paths). Cancellations get their own
            // closed_reason so the dashboard can separate voluntary
            // abandon from hard failure.
            telemetry::capture_fire_and_forget(
                Event::InstallFailed,
                EventProperties::new()
                    .with_error_code(variant_name)
                    .with_closed_reason(if is_cancel { "cancelled" } else { "error" }),
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
            if let Err(emit_err) = app.emit("installer://progress", ev) {
                tracing::warn!(error = ?emit_err, "cmd: emit() failed on error path");
            }
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
