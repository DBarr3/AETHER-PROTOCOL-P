use std::path::{Path, PathBuf};

use crate::download;

/// Paths the installer touches on Windows.
pub struct InstallerPaths {
    pub local_app_data: PathBuf,
    pub roaming_app_data: PathBuf,
    pub temp_dir: PathBuf,
    pub start_menu: PathBuf,
    pub desktop: PathBuf,
}

impl InstallerPaths {
    pub fn detect() -> Option<Self> {
        let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from)?;
        let roaming = std::env::var_os("APPDATA").map(PathBuf::from)?;
        let temp = std::env::temp_dir();
        let start_menu = roaming.join("Microsoft\\Windows\\Start Menu\\Programs");
        let desktop_env = std::env::var_os("USERPROFILE").map(PathBuf::from)?;
        let desktop = desktop_env.join("Desktop");

        Some(Self {
            local_app_data: local,
            roaming_app_data: roaming,
            temp_dir: temp,
            start_menu,
            desktop,
        })
    }

    pub fn aether_local(&self) -> PathBuf {
        self.local_app_data.join("AetherCloud")
    }

    pub fn aether_roaming(&self) -> PathBuf {
        self.roaming_app_data.join("AetherCloud")
    }

    pub fn aether_setup_logs(&self) -> PathBuf {
        self.local_app_data.join("AetherCloud-Setup")
    }

    pub fn install_dir(&self) -> PathBuf {
        self.local_app_data.join("Programs").join("AetherCloud-L")
    }
}

/// Run on every app startup: clean stale `.part` files from temp.
pub fn startup_cleanup() {
    let temp = std::env::temp_dir();
    let removed = download::cleanup_stale_parts(&temp);
    if !removed.is_empty() {
        tracing::info!(count = removed.len(), "startup: cleaned stale .part files");
    }
}

/// Flush pending writes and close handles cleanly.
pub fn shutdown_cleanup() {
    tracing::info!("shutdown: flushing pending state");
}

/// Full uninstall teardown. Removes all known AetherCloud artifacts.
pub fn uninstall_teardown() -> UninstallReport {
    let mut report = UninstallReport::default();
    let Some(paths) = InstallerPaths::detect() else {
        tracing::error!("uninstall: cannot detect system paths");
        report.errors.push("Cannot detect system paths".into());
        return report;
    };

    remove_dir_logged(&paths.aether_local(), &mut report);
    remove_dir_logged(&paths.aether_roaming(), &mut report);
    remove_dir_logged(&paths.aether_setup_logs(), &mut report);
    remove_dir_logged(&paths.install_dir(), &mut report);

    let alt_install = paths.local_app_data.join("Programs").join("aethercloud-l");
    if alt_install.exists() {
        remove_dir_logged(&alt_install, &mut report);
    }

    remove_registry_keys(&mut report);
    remove_credential_entries(&mut report);
    remove_scheduled_tasks(&mut report);
    remove_shortcuts(&paths, &mut report);

    tracing::info!(
        dirs_removed = report.dirs_removed,
        files_removed = report.files_removed,
        reg_keys_removed = report.reg_keys_removed,
        errors = report.errors.len(),
        "uninstall: teardown complete"
    );
    report
}

/// CLI-driven full purge (useful for QA). Same as uninstall_teardown.
pub fn purge() -> UninstallReport {
    tracing::info!("purge: running full cleanup");
    uninstall_teardown()
}

/// Check CLI args for `--purge` flag.
pub fn check_purge_flag() -> bool {
    std::env::args().any(|a| a == "--purge")
}

#[derive(Default, Debug)]
pub struct UninstallReport {
    pub dirs_removed: u32,
    pub files_removed: u32,
    pub reg_keys_removed: u32,
    pub credential_entries_removed: u32,
    pub shortcuts_removed: u32,
    pub tasks_removed: u32,
    pub errors: Vec<String>,
}

fn remove_dir_logged(path: &Path, report: &mut UninstallReport) {
    if !path.exists() {
        return;
    }
    match std::fs::remove_dir_all(path) {
        Ok(_) => {
            tracing::info!(path = %path.display(), "uninstall: removed directory");
            report.dirs_removed += 1;
        }
        Err(e) => {
            tracing::error!(path = %path.display(), error = ?e, "uninstall: failed to remove directory");
            report.errors.push(format!("Failed to remove {}: {}", path.display(), e));
        }
    }
}

#[cfg(windows)]
fn remove_registry_keys(report: &mut UninstallReport) {
    use std::process::Command;

    let keys = [r"HKCU\Software\AetherCloud"];

    for key in &keys {
        let result = Command::new("reg")
            .args(["delete", key, "/f"])
            .output();

        match result {
            Ok(output) if output.status.success() => {
                tracing::info!(key, "uninstall: removed registry key");
                report.reg_keys_removed += 1;
            }
            Ok(output) => {
                let stderr = String::from_utf8_lossy(&output.stderr);
                if !stderr.contains("unable to find") {
                    tracing::warn!(key, stderr = %stderr, "uninstall: reg delete warning");
                }
            }
            Err(e) => {
                tracing::error!(key, error = ?e, "uninstall: reg command failed");
                report.errors.push(format!("Registry delete {}: {}", key, e));
            }
        }
    }
}

#[cfg(not(windows))]
fn remove_registry_keys(_report: &mut UninstallReport) {}

#[cfg(windows)]
fn remove_credential_entries(report: &mut UninstallReport) {
    use std::process::Command;

    let list_result = Command::new("cmdkey").arg("/list").output();

    if let Ok(output) = list_result {
        let stdout = String::from_utf8_lossy(&output.stdout);
        for line in stdout.lines() {
            let trimmed = line.trim();
            if let Some(target) = trimmed.strip_prefix("Target: ") {
                if target.to_lowercase().contains("aethercloud") {
                    let del = Command::new("cmdkey")
                        .args(["/delete", target.trim()])
                        .output();
                    match del {
                        Ok(o) if o.status.success() => {
                            tracing::info!(target = target.trim(), "uninstall: removed credential");
                            report.credential_entries_removed += 1;
                        }
                        _ => {
                            tracing::warn!(target = target.trim(), "uninstall: credential delete failed");
                        }
                    }
                }
            }
        }
    }
}

#[cfg(not(windows))]
fn remove_credential_entries(_report: &mut UninstallReport) {}

#[cfg(windows)]
fn remove_scheduled_tasks(report: &mut UninstallReport) {
    use std::process::Command;

    let list_result = Command::new("schtasks")
        .args(["/query", "/fo", "CSV", "/nh"])
        .output();

    if let Ok(output) = list_result {
        let stdout = String::from_utf8_lossy(&output.stdout);
        for line in stdout.lines() {
            if line.to_lowercase().contains("aethercloud") {
                if let Some(task_name) = line.split(',').next() {
                    let name = task_name.trim_matches('"');
                    let del = Command::new("schtasks")
                        .args(["/delete", "/tn", name, "/f"])
                        .output();
                    match del {
                        Ok(o) if o.status.success() => {
                            tracing::info!(task = name, "uninstall: removed scheduled task");
                            report.tasks_removed += 1;
                        }
                        _ => {
                            tracing::warn!(task = name, "uninstall: task delete failed");
                        }
                    }
                }
            }
        }
    }
}

#[cfg(not(windows))]
fn remove_scheduled_tasks(_report: &mut UninstallReport) {}

fn remove_shortcuts(paths: &InstallerPaths, report: &mut UninstallReport) {
    let shortcuts = [
        paths.start_menu.join("AetherCloud.lnk"),
        paths.start_menu.join("AetherCloud-L.lnk"),
        paths.desktop.join("AetherCloud.lnk"),
        paths.desktop.join("AetherCloud-L.lnk"),
    ];

    for shortcut in &shortcuts {
        if shortcut.exists() {
            match std::fs::remove_file(shortcut) {
                Ok(_) => {
                    tracing::info!(path = %shortcut.display(), "uninstall: removed shortcut");
                    report.shortcuts_removed += 1;
                }
                Err(e) => {
                    tracing::error!(path = %shortcut.display(), error = ?e, "uninstall: shortcut remove failed");
                    report.errors.push(format!("Shortcut {}: {}", shortcut.display(), e));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn installer_paths_detect_returns_some_on_windows() {
        #[cfg(windows)]
        {
            let paths = InstallerPaths::detect();
            assert!(paths.is_some());
            let p = paths.unwrap();
            assert!(p.local_app_data.exists());
            assert!(p.roaming_app_data.exists());
        }
    }

    #[test]
    fn aether_paths_are_consistent() {
        #[cfg(windows)]
        {
            if let Some(p) = InstallerPaths::detect() {
                assert!(p.aether_local().to_string_lossy().contains("AetherCloud"));
                assert!(p.aether_roaming().to_string_lossy().contains("AetherCloud"));
                assert!(p.aether_setup_logs().to_string_lossy().contains("AetherCloud-Setup"));
            }
        }
    }

    #[test]
    fn check_purge_flag_negative() {
        assert!(!check_purge_flag());
    }

    #[test]
    fn uninstall_report_default_is_clean() {
        let r = UninstallReport::default();
        assert_eq!(r.dirs_removed, 0);
        assert_eq!(r.files_removed, 0);
        assert_eq!(r.reg_keys_removed, 0);
        assert!(r.errors.is_empty());
    }
}
