use crate::errors::{InstallerError, Result};
use crate::manifest::{self, Manifest};
use crate::payload::{self, DownloadProgress};
use serde::Serialize;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::Mutex;

const MANIFEST_URL: &str = "https://api.aethersystems.net/downloads/manifest-latest.json";
const MANIFEST_SIG_URL: &str = "https://api.aethersystems.net/downloads/manifest-latest.sig";
const MAX_PAYLOAD_BYTES: u64 = 500 * 1024 * 1024; // 500 MB ceiling — sanity check
const WIZARD_VERSION: &str = env!("CARGO_PKG_VERSION");

/// Compile-time pinned public key for manifest signature verification.
/// Production key generated 2026-04-19. Pub fingerprint:
///   b9f4d6d5460ad525b362c5886747fde43f567e63aa8b9060b88d6d4e82a97301
/// The matching private key is stored offline outside the repo. Rotating
/// requires regenerating the key + rebuilding the wizard (which invalidates
/// all older wizards' trust — intentional).
const PINNED_PUBKEY: &[u8; 32] = include_bytes!("../keys/manifest-signing.pub.bin");

#[derive(Serialize, Clone, Debug)]
pub struct ProgressEvent {
    pub state: &'static str,
    pub percent: u32,
    pub label: String,
    pub detail: String,
    pub speed: String,
    pub error: Option<String>,
}

#[derive(Default)]
pub struct InstallerState {
    pub cancelled: Arc<Mutex<bool>>,
    pub in_flight_temp: Arc<Mutex<Option<PathBuf>>>,
}

impl InstallerState {
    pub async fn cancel(&self) {
        *self.cancelled.lock().await = true;
        if let Some(path) = self.in_flight_temp.lock().await.take() {
            let _ = tokio::fs::remove_file(&path).await;
        }
    }
    async fn is_cancelled(&self) -> bool {
        *self.cancelled.lock().await
    }
}

pub async fn run_install<F>(state: Arc<InstallerState>, mut emit: F) -> Result<PathBuf>
where
    F: FnMut(ProgressEvent) + Send,
{
    emit(ProgressEvent {
        state: "fetching_manifest",
        percent: 2,
        label: "Connecting to AetherCloud".into(),
        detail: "Page 3 of 4".into(),
        speed: "Fetching manifest".into(),
        error: None,
    });

    let client = reqwest::Client::builder().build()?;
    let manifest_bytes = client.get(MANIFEST_URL).send().await?
        .error_for_status().map_err(|e| match e.status() {
            Some(s) => InstallerError::ManifestHttpStatus(s.as_u16()),
            None => InstallerError::Network(e),
        })?
        .bytes().await?;
    let sig_bytes = client.get(MANIFEST_SIG_URL).send().await?
        .error_for_status().map_err(|e| match e.status() {
            Some(s) => InstallerError::ManifestHttpStatus(s.as_u16()),
            None => InstallerError::Network(e),
        })?
        .bytes().await?;

    if state.is_cancelled().await { return Err(InstallerError::Cancelled); }

    emit(ProgressEvent {
        state: "verifying_manifest",
        percent: 6,
        label: "Verifying install package".into(),
        detail: "Page 3 of 4".into(),
        speed: "Checking signature".into(),
        error: None,
    });

    manifest::verify_signature(&manifest_bytes, &sig_bytes, PINNED_PUBKEY)?;
    let manifest = Manifest::parse(&manifest_bytes)?;

    check_min_wizard_version(&manifest.min_wizard_version)?;

    emit(ProgressEvent {
        state: "downloading_payload",
        percent: 8,
        label: "Downloading AetherCloud".into(),
        detail: "Page 3 of 4".into(),
        speed: "Starting download".into(),
        error: None,
    });

    let temp_path = payload::temp_payload_path();
    *state.in_flight_temp.lock().await = Some(temp_path.clone());

    let max_bytes = manifest.payload_size_bytes.min(MAX_PAYLOAD_BYTES);
    let hash = {
        let emit_ref = &mut emit;
        payload::download_with_progress(&manifest.payload_url, &temp_path, max_bytes, |p: DownloadProgress| {
            let pct = if p.total_bytes > 0 {
                8 + (77 * p.bytes_written / p.total_bytes.max(1)) as u32
            } else { 8 };
            emit_ref(ProgressEvent {
                state: "downloading_payload",
                percent: pct.min(85),
                label: "Downloading AetherCloud".into(),
                detail: format!("{} / {} MB",
                    p.bytes_written / (1024 * 1024),
                    p.total_bytes / (1024 * 1024)),
                speed: "Receiving packages".into(),
                error: None,
            });
        }).await?
    };

    if state.is_cancelled().await {
        let _ = tokio::fs::remove_file(&temp_path).await;
        return Err(InstallerError::Cancelled);
    }

    emit(ProgressEvent {
        state: "verifying_payload",
        percent: 87,
        label: "Verifying download".into(),
        detail: "Page 3 of 4".into(),
        speed: "Checking integrity".into(),
        error: None,
    });

    if hash != manifest.payload_sha256 {
        let _ = tokio::fs::remove_file(&temp_path).await;
        return Err(InstallerError::PayloadHashMismatch {
            expected: manifest.payload_sha256.clone(),
            got: hash,
        });
    }

    emit(ProgressEvent {
        state: "installing",
        percent: 92,
        label: "Installing AetherCloud".into(),
        detail: "Page 3 of 4".into(),
        speed: "Running installer".into(),
        error: None,
    });

    // Hand the payload to NSIS — past this point a cancel() must NOT delete
    // the file out from under the running process. Clearing in_flight_temp
    // keeps cancel()'s cleanup branch from racing run_payload_silent.
    *state.in_flight_temp.lock().await = None;

    let code = payload::run_payload_silent(&temp_path).await?;
    let _ = tokio::fs::remove_file(&temp_path).await;

    if code != 0 {
        return Err(InstallerError::PayloadExit { code });
    }

    emit(ProgressEvent {
        state: "done",
        percent: 100,
        label: "AetherCloud is ready".into(),
        detail: "Page 4 of 4".into(),
        speed: "Verification complete".into(),
        error: None,
    });

    Ok(installed_app_path())
}

fn check_min_wizard_version(required: &str) -> Result<()> {
    if version_cmp(WIZARD_VERSION, required).is_lt() {
        return Err(InstallerError::MinWizardVersion {
            required: required.to_string(),
            current: WIZARD_VERSION.to_string(),
        });
    }
    Ok(())
}

/// Minimal semver-ish comparison. Zero-pads unequal lengths so "1.0" == "1.0.0".
/// Non-numeric pre-release tags (e.g. "-beta") are silently dropped — the wizard
/// and manifest are expected to use plain numeric versions only.
fn version_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    let mut pa: Vec<u32> = a.split('.').filter_map(|s| s.parse().ok()).collect();
    let mut pb: Vec<u32> = b.split('.').filter_map(|s| s.parse().ok()).collect();
    let len = pa.len().max(pb.len());
    pa.resize(len, 0);
    pb.resize(len, 0);
    pa.cmp(&pb)
}

pub fn installed_app_path() -> PathBuf {
    // %LOCALAPPDATA%\aethercloud-l\AetherCloud-L.exe (matches existing NSIS oneClick default).
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        PathBuf::from(local).join("aethercloud-l").join("AetherCloud-L.exe")
    } else {
        PathBuf::from("AetherCloud-L.exe")
    }
}

pub fn detect_existing_install() -> (bool, Option<String>) {
    let p = installed_app_path();
    (p.exists(), None)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_cmp_basic() {
        assert_eq!(version_cmp("1.0.0", "1.0.0"), std::cmp::Ordering::Equal);
        assert_eq!(version_cmp("1.0.0", "1.0.1"), std::cmp::Ordering::Less);
        assert_eq!(version_cmp("2.0.0", "1.9.9"), std::cmp::Ordering::Greater);
    }

    #[test]
    fn version_cmp_handles_unequal_length() {
        // Regression: "1.0" must compare equal to "1.0.0" — zero-padding,
        // not lexicographic Vec ordering. Otherwise a manifest with
        // min_wizard_version "1.0" incorrectly blocks a wizard at "1.0.0".
        assert_eq!(version_cmp("1.0", "1.0.0"), std::cmp::Ordering::Equal);
        assert_eq!(version_cmp("1.0.0", "1.0"), std::cmp::Ordering::Equal);
        assert_eq!(version_cmp("1.0", "1.0.1"), std::cmp::Ordering::Less);
        assert_eq!(version_cmp("1.1", "1.0.9"), std::cmp::Ordering::Greater);
    }

    #[test]
    fn min_wizard_version_blocks_older() {
        let err = check_min_wizard_version("999.0.0").unwrap_err();
        assert!(matches!(err, InstallerError::MinWizardVersion { .. }));
    }

    #[test]
    fn min_wizard_version_accepts_equal_or_newer() {
        check_min_wizard_version("1.0.0").unwrap();
        check_min_wizard_version("0.0.1").unwrap();
    }
}
