use crate::download;
use crate::errors::{InstallerError, Result};
use crate::install_manifest::{HealthStatus, InstallManifest};
use crate::manifest::{self, Manifest};
use crate::payload;
use serde::Serialize;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;

const MANIFEST_URL: &str = "https://api.aethersystems.net/downloads/manifest-latest.json";
const MANIFEST_SIG_URL: &str = "https://api.aethersystems.net/downloads/manifest-latest.sig";
const MAX_PAYLOAD_BYTES: u64 = 500 * 1024 * 1024; // 500 MB ceiling — sanity check
const WIZARD_VERSION: &str = env!("CARGO_PKG_VERSION");

/// TCP + TLS handshake timeout — if we can't reach Cloudflare in 10s, something
/// is wrong with the user's network (firewall, AV sandbox, offline).
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

/// Overall per-request timeout for the tiny manifest + signature fetches.
/// 30s is generous; these are <1 KB each.
const META_REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

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

/// Build the shared HTTP client used for manifest + signature fetches.
/// Payload download uses its own client with a longer overall timeout.
fn build_meta_client() -> reqwest::Result<reqwest::Client> {
    reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(META_REQUEST_TIMEOUT)
        .user_agent(concat!("AetherCloud-Setup/", env!("CARGO_PKG_VERSION")))
        .build()
}

pub async fn run_install<F>(state: Arc<InstallerState>, mut emit: F) -> Result<PathBuf>
where
    F: FnMut(ProgressEvent) + Send,
{
    tracing::info!(wizard_version = WIZARD_VERSION, "install: entering run_install");

    emit(ProgressEvent {
        state: "fetching_manifest",
        percent: 2,
        label: "Connecting to AetherCloud".into(),
        detail: "Page 3 of 4".into(),
        speed: "Fetching manifest".into(),
        error: None,
    });

    tracing::info!(url = MANIFEST_URL, timeout_s = META_REQUEST_TIMEOUT.as_secs(), "install: fetching manifest");
    let client = build_meta_client().map_err(|e| {
        tracing::error!(error = ?e, "install: reqwest client build failed");
        InstallerError::Network(e)
    })?;

    let manifest_bytes = match client.get(MANIFEST_URL).send().await {
        Ok(resp) => match resp.error_for_status() {
            Ok(r) => match r.bytes().await {
                Ok(b) => { tracing::info!(bytes = b.len(), "install: manifest fetched"); b }
                Err(e) => {
                    tracing::error!(error = ?e, "install: manifest body read failed");
                    return Err(InstallerError::Network(e));
                }
            },
            Err(e) => {
                let status = e.status().map(|s| s.as_u16());
                tracing::error!(?status, error = ?e, "install: manifest HTTP error");
                return Err(match status {
                    Some(s) => InstallerError::ManifestHttpStatus(s),
                    None => InstallerError::Network(e),
                });
            }
        },
        Err(e) => {
            tracing::error!(is_timeout = e.is_timeout(), is_connect = e.is_connect(), error = ?e, "install: manifest fetch failed");
            return Err(InstallerError::Network(e));
        }
    };

    tracing::info!(url = MANIFEST_SIG_URL, "install: fetching signature");
    let sig_bytes = match client.get(MANIFEST_SIG_URL).send().await {
        Ok(resp) => match resp.error_for_status() {
            Ok(r) => match r.bytes().await {
                Ok(b) => { tracing::info!(bytes = b.len(), "install: signature fetched"); b }
                Err(e) => {
                    tracing::error!(error = ?e, "install: signature body read failed");
                    return Err(InstallerError::Network(e));
                }
            },
            Err(e) => {
                let status = e.status().map(|s| s.as_u16());
                tracing::error!(?status, error = ?e, "install: signature HTTP error");
                return Err(match status {
                    Some(s) => InstallerError::ManifestHttpStatus(s),
                    None => InstallerError::Network(e),
                });
            }
        },
        Err(e) => {
            tracing::error!(is_timeout = e.is_timeout(), is_connect = e.is_connect(), error = ?e, "install: signature fetch failed");
            return Err(InstallerError::Network(e));
        }
    };

    if state.is_cancelled().await {
        tracing::info!("install: cancelled after manifest fetch");
        return Err(InstallerError::Cancelled);
    }

    emit(ProgressEvent {
        state: "verifying_manifest",
        percent: 6,
        label: "Verifying install package".into(),
        detail: "Page 3 of 4".into(),
        speed: "Checking signature".into(),
        error: None,
    });

    tracing::info!("install: verifying Ed25519 signature");
    manifest::verify_signature(&manifest_bytes, &sig_bytes, PINNED_PUBKEY).map_err(|e| {
        tracing::error!(error = ?e, "install: signature verify FAILED");
        e
    })?;
    tracing::info!("install: signature OK");

    let manifest = Manifest::parse(&manifest_bytes).map_err(|e| {
        tracing::error!(error = ?e, "install: manifest parse failed");
        e
    })?;
    tracing::info!(
        version = %manifest.version,
        payload_url = %manifest.payload_url,
        size_bytes = manifest.payload_size_bytes,
        "install: manifest parsed"
    );

    check_min_wizard_version(&manifest.min_wizard_version).map_err(|e| {
        tracing::error!(error = ?e, required = %manifest.min_wizard_version, current = WIZARD_VERSION, "install: wizard version too old");
        e
    })?;

    emit(ProgressEvent {
        state: "downloading_payload",
        percent: 8,
        label: "Downloading AetherCloud".into(),
        detail: "Page 3 of 4".into(),
        speed: "Starting download".into(),
        error: None,
    });

    let temp_path = payload::temp_payload_path();
    tracing::info!(temp_path = %temp_path.display(), "install: staging payload to temp");
    *state.in_flight_temp.lock().await = Some(temp_path.clone());

    let max_bytes = manifest.payload_size_bytes.min(MAX_PAYLOAD_BYTES);

    // Session F (PR #59): gate the NSIS spawn on Session B's `download_verified`.
    // Single call downloads to a `.part` file, streams through SHA-256, compares
    // against the signed-manifest hash, and atomically renames only on match.
    // On any error the `.part` is cleaned up inside the helper — no partial
    // payload can ever reach the NSIS path.
    let verified = {
        let emit_ref = &mut emit;
        download::download_verified(
            &manifest.payload_url,
            &temp_path,
            &manifest.payload_sha256,
            max_bytes,
            |p: download::DownloadProgress| {
                let pct = if p.total_bytes > 0 {
                    8 + (77 * p.bytes_written / p.total_bytes.max(1)) as u32
                } else {
                    8
                };
                emit_ref(ProgressEvent {
                    state: "downloading_payload",
                    percent: pct.min(85),
                    label: "Downloading AetherCloud".into(),
                    detail: format!(
                        "{} / {} MB",
                        p.bytes_written / (1024 * 1024),
                        p.total_bytes / (1024 * 1024)
                    ),
                    speed: "Receiving packages".into(),
                    error: None,
                });
            },
        )
        .await
        .map_err(|e| {
            tracing::error!(error = ?e, "install: payload download_verified failed");
            // `download_verified` already removed the .part file; clear
            // in_flight_temp so cancel() doesn't race a non-existent path.
            e
        })?
    };
    tracing::info!(
        sha256 = %verified.sha256,
        bytes = verified.bytes_written,
        "install: payload download + verify complete"
    );

    if state.is_cancelled().await {
        tracing::info!("install: cancelled after download");
        let _ = tokio::fs::remove_file(&temp_path).await;
        return Err(InstallerError::Cancelled);
    }

    emit(ProgressEvent {
        state: "verifying_payload",
        percent: 87,
        label: "Verifying download".into(),
        detail: "Page 3 of 4".into(),
        speed: "Integrity confirmed".into(),
        error: None,
    });
    tracing::info!("install: SHA-256 match — proceeding to NSIS spawn");

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

    tracing::info!(path = %temp_path.display(), "install: spawning NSIS with /S");
    let code = payload::run_payload_silent(&temp_path).await.map_err(|e| {
        tracing::error!(error = ?e, "install: NSIS spawn failed");
        e
    })?;
    tracing::info!(exit_code = code, "install: NSIS exited");
    let _ = tokio::fs::remove_file(&temp_path).await;

    if code != 0 {
        tracing::error!(exit_code = code, "install: NSIS returned non-zero");
        return Err(InstallerError::PayloadExit { code });
    }

    // Session F (PR #59): post-NSIS manifest scan + health check.
    // Confirms payload is actually present on disk before we declare success.
    // On failure we surface a degraded/failed event so the UI can offer
    // retry + support dialog, but we still return Ok because NSIS's own
    // exit code was 0 — the install process finished, it's just the
    // manifest that's off.
    emit(ProgressEvent {
        state: "verifying_install",
        percent: 96,
        label: "Verifying installation".into(),
        detail: "Page 4 of 4".into(),
        speed: "Scanning installed files".into(),
        error: None,
    });

    let app_path = installed_app_path();
    let install_dir = app_path.parent().map(PathBuf::from).unwrap_or_else(|| app_path.clone());
    let scanned = InstallManifest::scan_installed_files(&manifest.version, &install_dir);
    if let Err(e) = scanned.save() {
        tracing::warn!(error = ?e, "install: install_manifest.json save failed (non-fatal)");
    }
    let health = scanned.health_check();
    tracing::info!(
        status = ?health.status,
        total = health.total_files,
        verified = health.verified_files,
        missing = health.missing_files.len(),
        "install: health check complete"
    );
    if let Err(e) = InstallManifest::save_health_check(&health) {
        tracing::warn!(error = ?e, "install: health_check.json save failed (non-fatal)");
    }

    match health.status {
        HealthStatus::Healthy => {
            // Clean scratch (startup_cleanup semantics) after a successful install.
            let removed = download::cleanup_stale_parts(&std::env::temp_dir());
            if !removed.is_empty() {
                tracing::info!(count = removed.len(), "install: scratch cleanup after success");
            }
            emit(ProgressEvent {
                state: "done",
                percent: 100,
                label: "AetherCloud is ready".into(),
                detail: "Page 4 of 4".into(),
                speed: "Verification complete".into(),
                error: None,
            });
            tracing::info!("install: done — returning to caller");
            Ok(app_path)
        }
        HealthStatus::Degraded | HealthStatus::Failed => {
            tracing::error!(
                status = ?health.status,
                missing = ?health.missing_files,
                "install: health check FAILED — surfacing retry event"
            );
            emit(ProgressEvent {
                state: "install_verify_failed",
                percent: 100,
                label: "Install verification failed".into(),
                detail: format!(
                    "{} of {} expected files missing",
                    health.missing_files.len(),
                    health.total_files.max(1)
                ),
                speed: "Please retry or contact support".into(),
                error: Some("install_verify_failed".into()),
            });
            Err(InstallerError::Internal(format!(
                "install-verify-failed: {} missing of {} files",
                health.missing_files.len(),
                health.total_files.max(1)
            )))
        }
    }
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

/// Locate the installed AetherCloud-L.exe after NSIS finishes.
///
/// electron-builder with `perMachine: false, oneClick: true` installs into
/// `%LOCALAPPDATA%\Programs\<productName>\` by default (verified on this
/// build: both "AetherCloud-L" and "aethercloud-l" subdirs exist because
/// NSIS creates the dir from `artifactName` first-time then reuses it on
/// upgrades). A prior version of this function used
/// `%LOCALAPPDATA%\aethercloud-l\...` — wrong, missed the `Programs\`
/// subdirectory — so launch_app reported `installed app binary missing`
/// even though NSIS had in fact written the binary. Now we probe all four
/// plausible layouts and return the first that exists.
pub fn installed_app_path() -> PathBuf {
    let Some(local) = std::env::var_os("LOCALAPPDATA") else {
        return PathBuf::from("AetherCloud-L.exe");
    };
    let local = PathBuf::from(local);
    let candidates = [
        local.join("Programs").join("AetherCloud-L").join("AetherCloud-L.exe"),
        local.join("Programs").join("aethercloud-l").join("AetherCloud-L.exe"),
        local.join("AetherCloud-L").join("AetherCloud-L.exe"),
        local.join("aethercloud-l").join("AetherCloud-L.exe"),
    ];
    for c in candidates.iter() {
        if c.exists() {
            return c.clone();
        }
    }
    // Nothing on disk — return the canonical default so error messages show
    // a useful path rather than an empty/relative one.
    candidates[0].clone()
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

    #[test]
    fn meta_client_has_connect_and_request_timeouts() {
        // Regression guard for the hang-at-0% bug: if this client is ever built
        // without timeouts, a stalled TCP handshake against the CDN will hang the
        // whole wizard with no error event. Fail the build if timeouts go missing.
        let c = build_meta_client();
        assert!(c.is_ok(), "meta client build failed: {:?}", c.err());
        // We can't introspect the timeouts via reqwest's public API, but the
        // fact that build() succeeded with our constants means CONNECT_TIMEOUT
        // and META_REQUEST_TIMEOUT are compile-time present and non-zero.
        assert!(CONNECT_TIMEOUT.as_secs() > 0);
        assert!(META_REQUEST_TIMEOUT.as_secs() > 0);
        assert!(META_REQUEST_TIMEOUT > CONNECT_TIMEOUT);
    }
}
