use crate::errors::{InstallerError, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

const MANIFEST_FILENAME: &str = "install_manifest.json";
const HEALTH_CHECK_FILENAME: &str = "install_health_check.json";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstallManifest {
    pub version: String,
    pub install_date: String,
    pub install_dir: String,
    pub files: Vec<InstalledFile>,
    pub registry_keys: Vec<String>,
    pub shortcuts: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstalledFile {
    pub path: String,
    pub sha256: Option<String>,
    pub size_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthCheckResult {
    pub timestamp: String,
    pub version: String,
    pub all_files_present: bool,
    pub missing_files: Vec<String>,
    pub total_files: usize,
    pub verified_files: usize,
    pub status: HealthStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum HealthStatus {
    Healthy,
    Degraded,
    Failed,
}

impl InstallManifest {
    pub fn new(version: &str, install_dir: &Path) -> Self {
        let now = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        Self {
            version: version.to_string(),
            install_date: format!("{}", now),
            install_dir: install_dir.to_string_lossy().into_owned(),
            files: Vec::new(),
            registry_keys: Vec::new(),
            shortcuts: Vec::new(),
        }
    }

    pub fn add_file(&mut self, path: &Path, sha256: Option<String>, size_bytes: u64) {
        self.files.push(InstalledFile {
            path: path.to_string_lossy().into_owned(),
            sha256,
            size_bytes,
        });
    }

    pub fn add_registry_key(&mut self, key: &str) {
        self.registry_keys.push(key.to_string());
    }

    pub fn add_shortcut(&mut self, path: &Path) {
        self.shortcuts.push(path.to_string_lossy().into_owned());
    }

    pub fn save(&self) -> Result<PathBuf> {
        let dir = manifest_dir()?;
        std::fs::create_dir_all(&dir)?;
        let path = dir.join(MANIFEST_FILENAME);
        let json = serde_json::to_string_pretty(self).map_err(InstallerError::ManifestParse)?;
        std::fs::write(&path, json)?;
        tracing::info!(path = %path.display(), files = self.files.len(), "install_manifest: saved");
        Ok(path)
    }

    pub fn load() -> Result<Self> {
        let dir = manifest_dir()?;
        let path = dir.join(MANIFEST_FILENAME);
        let bytes = std::fs::read(&path)?;
        serde_json::from_slice(&bytes).map_err(InstallerError::ManifestParse)
    }

    pub fn scan_installed_files(version: &str, install_dir: &Path) -> Self {
        let mut m = Self::new(version, install_dir);
        if install_dir.exists() {
            scan_dir_recursive(install_dir, &mut m.files);
        }
        m.add_registry_key(r"HKCU\Software\AetherCloud");
        m
    }

    pub fn health_check(&self) -> HealthCheckResult {
        let mut missing = Vec::new();
        let mut verified = 0;
        for file in &self.files {
            if Path::new(&file.path).exists() {
                verified += 1;
            } else {
                missing.push(file.path.clone());
            }
        }
        let status = if missing.is_empty() {
            HealthStatus::Healthy
        } else if verified > 0 {
            HealthStatus::Degraded
        } else if self.files.is_empty() {
            HealthStatus::Healthy
        } else {
            HealthStatus::Failed
        };
        let now = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        HealthCheckResult {
            timestamp: format!("{}", now),
            version: self.version.clone(),
            all_files_present: missing.is_empty(),
            missing_files: missing,
            total_files: self.files.len(),
            verified_files: verified,
            status,
        }
    }

    pub fn save_health_check(result: &HealthCheckResult) -> Result<PathBuf> {
        let dir = manifest_dir()?;
        std::fs::create_dir_all(&dir)?;
        let path = dir.join(HEALTH_CHECK_FILENAME);
        let json = serde_json::to_string_pretty(result).map_err(InstallerError::ManifestParse)?;
        std::fs::write(&path, json)?;
        tracing::info!(path = %path.display(), status = ?result.status, "health_check: saved");
        Ok(path)
    }
}

fn manifest_dir() -> Result<PathBuf> {
    let local = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| InstallerError::Internal("LOCALAPPDATA not set".into()))?;
    Ok(local.join("AetherCloud"))
}

fn scan_dir_recursive(dir: &Path, files: &mut Vec<InstalledFile>) {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            scan_dir_recursive(&path, files);
        } else if let Ok(meta) = path.metadata() {
            files.push(InstalledFile {
                path: path.to_string_lossy().into_owned(),
                sha256: None,
                size_bytes: meta.len(),
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn new_manifest_has_correct_version() {
        let m = InstallManifest::new("1.2.3", Path::new("C:\\test"));
        assert_eq!(m.version, "1.2.3");
        assert_eq!(m.install_dir, "C:\\test");
        assert!(m.files.is_empty());
    }

    #[test]
    fn add_file_tracks_entry() {
        let mut m = InstallManifest::new("1.0.0", Path::new("/install"));
        m.add_file(Path::new("/install/app.exe"), Some("abcd1234".into()), 1024);
        assert_eq!(m.files.len(), 1);
        assert_eq!(m.files[0].size_bytes, 1024);
    }

    #[test]
    fn health_check_all_present() {
        let dir = std::env::temp_dir().join("aether_im_test_health");
        let _ = fs::create_dir_all(&dir);
        let f = dir.join("test.txt");
        fs::write(&f, b"hello").unwrap();
        let mut m = InstallManifest::new("1.0.0", &dir);
        m.add_file(&f, None, 5);
        let r = m.health_check();
        assert_eq!(r.status, HealthStatus::Healthy);
        assert!(r.all_files_present);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn health_check_missing() {
        let mut m = InstallManifest::new("1.0.0", Path::new("/gone"));
        m.add_file(Path::new("/gone/missing.exe"), None, 0);
        let r = m.health_check();
        assert_eq!(r.status, HealthStatus::Failed);
    }

    #[test]
    fn manifest_roundtrip_json() {
        let mut m = InstallManifest::new("2.0.0", Path::new("C:\\Aether"));
        m.add_file(Path::new("C:\\app.exe"), Some("abc".into()), 999);
        m.add_registry_key(r"HKCU\Software\Test");
        let json = serde_json::to_string(&m).unwrap();
        let p: InstallManifest = serde_json::from_str(&json).unwrap();
        assert_eq!(p.version, "2.0.0");
        assert_eq!(p.files.len(), 1);
    }
}
