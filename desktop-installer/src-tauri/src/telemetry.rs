//! Install-funnel PostHog telemetry for the AetherCloud Tauri wizard.
//!
//! This module closes the funnel gap identified in PR #56 (tree audit):
//! the LIVE wizard (`desktop-installer/`, Tauri) had zero telemetry, while
//! the 13 PostHog events Issue #50 targeted were wired to the POST-install
//! welcome page in `desktop/` (Electron payload), which only fires AFTER
//! the wizard already completed. This module fires the funnel events at
//! their TRUE call sites so we can observe dropoff at every stage.
//!
//! ## Wire protocol
//!
//! Events are posted directly to `https://us.i.posthog.com/capture/` as
//! JSON, matching the pattern in `aethercloud/supabase/functions/_shared/
//! license.ts::captureServerEvent`. We do NOT depend on a Rust PostHog
//! SDK — a single POST is simpler, has fewer deps, and mirrors the
//! existing server-side pattern.
//!
//! ## Design rules (from task brief + PR #58 + security review)
//!
//! - **Rust-side emission** for security-sensitive events (verify_started,
//!   verify_completed, verify_failed, install_started, install_completed,
//!   install_failed). A compromised WebView cannot skip or fake these.
//! - **Never throws into the caller.** Every emission is fire-and-forget;
//!   `capture()` logs errors via `tracing::warn` and returns Ok. Telemetry
//!   is the BYPRODUCT — the install is the PRODUCT. A PostHog outage must
//!   not block an install.
//! - **Non-blocking.** Each `capture()` spawns a detached tokio task. The
//!   caller never awaits the HTTP round-trip.
//! - **Sanitization:** property values MUST be primitives the caller has
//!   already validated: UUIDs, enum labels, static error codes, counts,
//!   percents, SHA-256 prefixes (first 16 hex). Callers MUST NOT pass
//!   raw file paths containing user-dir names, full Stripe-id-like
//!   strings, arbitrary error messages, or user input. A helper
//!   [`redact_path`] is provided for the one case (install path) where
//!   we legitimately want to log that something ran in `%LOCALAPPDATA%`
//!   without leaking the concrete user name.
//! - **Persistent anonymous distinct_id.** A UUIDv4 is generated on first
//!   invocation and cached at `%LOCALAPPDATA%\AetherCloud-Setup\
//!   telemetry-distinct-id.txt` — coordinated read-only with
//!   `cleanup::startup_cleanup`, which owns that directory. Cached so
//!   funnel steps within a single install attempt correlate.
//! - **Gating.** `AETHER_TELEMETRY_ENABLED=0` disables. In `debug_assertions`
//!   builds telemetry is OFF by default so `cargo run` doesn't pollute the
//!   funnel.
//!
//! ## Not used
//!
//! We deliberately do NOT use the `posthog` Rust crate: (a) adds a
//! transitive dep just to produce a JSON POST, (b) the crate spawns its
//! own runtime which conflicts with tokio, (c) the capture JSON shape
//! is stable enough that a hand-rolled POST is lower-risk.

use serde::Serialize;
use serde_json::json;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Duration;

/// PostHog ingest endpoint. `us.i.posthog.com` is the US cloud region —
/// matches the allow-list entry in `capabilities/default.json`.
const DEFAULT_ENDPOINT: &str = "https://us.i.posthog.com/capture/";

/// Per-request timeout. Deliberately short: telemetry must never stall
/// the install flow. If the network is slow enough to miss this window
/// we'd rather drop the event than delay the wizard.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);

/// Compile-time PostHog project key. Overridden at runtime by
/// `AETHER_POSTHOG_KEY` if set. Publishable project keys are safe to
/// embed in client apps by design (PostHog's own guidance). The empty
/// default means captures are silently no-op'd in builds that haven't
/// been configured with a key — preferable to hardcoding a real key
/// into the open-source installer binary.
const COMPILED_POSTHOG_KEY: &str = "";

/// Environment variable names (exposed for tests and docs).
pub const ENV_ENABLED: &str = "AETHER_TELEMETRY_ENABLED";
pub const ENV_POSTHOG_KEY: &str = "AETHER_POSTHOG_KEY";
pub const ENV_POSTHOG_HOST: &str = "AETHER_POSTHOG_HOST";
pub const ENV_DISTINCT_ID: &str = "AETHER_TELEMETRY_DISTINCT_ID";
/// Legacy disable flag from the Electron telemetry.js client, honored
/// for continuity. Any truthy value disables capture.
pub const ENV_LEGACY_OFF: &str = "AETHER_TELEMETRY_OFF";

/// Canonical event names for the install funnel. Keeping this as an
/// enum rather than free-form strings means a typo at a call site is a
/// compile error, and the PostHog dashboard has a stable vocabulary.
///
/// The 13 events below correspond to the funnel phases the task brief
/// (issue #50) enumerated: wizard launch -> download -> verify -> install ->
/// launch. Variant names match the event string that lands in PostHog
/// one-to-one (see [`Event::as_str`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Event {
    /// Wizard process started, first window rendered. Top of funnel.
    WizardLaunched,
    /// User granted consent and clicked the install button. Install
    /// flow begins.
    InstallerStarted,
    /// Rust began the HTTPS GET for the payload.
    DownloadStarted,
    /// Periodic progress snapshot during payload download. Low-frequency
    /// (emitted at boundary percentages, not every byte).
    DownloadProgress,
    /// Payload download finished and streamed through SHA-256.
    DownloadCompleted,
    /// Rust began Ed25519 manifest signature + payload hash verify.
    VerifyStarted,
    /// Signature + hash both OK. Payload is safe to hand to NSIS.
    VerifyCompleted,
    /// Signature OR hash mismatch. Install is aborted before NSIS runs.
    VerifyFailed,
    /// NSIS process was spawned with /S.
    InstallStarted,
    /// Post-install manifest scan in progress (after NSIS exit, before
    /// health-check verdict).
    InstallProgress,
    /// NSIS exited 0 AND health check came back Healthy.
    InstallCompleted,
    /// NSIS exited non-zero OR health check came back Degraded/Failed.
    InstallFailed,
    /// User closed the wizard window (any path: success, cancel, error).
    WizardClosed,
}

impl Event {
    /// Stable wire name. Changes here REBASE the PostHog dashboard; keep
    /// in sync with the dashboard query definitions.
    pub const fn as_str(&self) -> &'static str {
        match self {
            Event::WizardLaunched => "wizard_launched",
            Event::InstallerStarted => "installer_started",
            Event::DownloadStarted => "download_started",
            Event::DownloadProgress => "download_progress",
            Event::DownloadCompleted => "download_completed",
            Event::VerifyStarted => "verify_started",
            Event::VerifyCompleted => "verify_completed",
            Event::VerifyFailed => "verify_failed",
            Event::InstallStarted => "install_started",
            Event::InstallProgress => "install_progress",
            Event::InstallCompleted => "install_completed",
            Event::InstallFailed => "install_failed",
            Event::WizardClosed => "wizard_closed",
        }
    }
}

/// Telemetry error surface — intentionally minimal. These variants are
/// returned only from the internal helpers; the public `capture` fn
/// always swallows them via tracing::warn.
#[derive(Debug, thiserror::Error)]
pub enum TelemetryError {
    #[error("telemetry disabled by env/default")]
    Disabled,
    #[error("no posthog key configured — nothing to send")]
    MissingKey,
    #[error("posthog host rejected request: HTTP {0}")]
    HttpStatus(u16),
    #[error("network error: {0}")]
    Network(String),
    #[error("io error resolving distinct_id: {0}")]
    Io(String),
    #[error("serialization error: {0}")]
    Serialize(String),
}

/// Structured properties bag. Callers construct one of these rather than
/// passing a `serde_json::Value` directly so each property's shape is
/// explicit at the call site (and so we can add rules for new fields
/// without touching the public surface).
#[derive(Debug, Clone, Default, Serialize)]
pub struct EventProperties {
    /// Wizard package version (`CARGO_PKG_VERSION`), always set.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub wizard_version: Option<String>,
    /// "windows", "macos", "linux". Coarse OS label only — no kernel
    /// version, no locale.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub os: Option<&'static str>,
    /// Integer percent 0..=100. Used by download_progress and
    /// install_progress.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub percent: Option<u32>,
    /// Payload bytes written, when known.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bytes_written: Option<u64>,
    /// First 16 hex chars of a SHA-256. NEVER the full hash, NEVER the
    /// full signature. 16 hex is enough to bucket in the dashboard
    /// without making hash comparison trivial.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sha256_prefix: Option<String>,
    /// Attempt number (1..=MAX_RETRIES) for retry-able operations.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub attempt: Option<u32>,
    /// Stable error-code label (e.g., `InstallerError::state_label()`).
    /// Must be a static string — not a `Display` string that might
    /// contain user paths or URLs.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_code: Option<&'static str>,
    /// Boolean terminal state for wizard_closed (did the user finish,
    /// cancel, or error out).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub closed_reason: Option<&'static str>,
    /// Count of files reported by the post-install manifest scan.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file_count: Option<usize>,
    /// Count of missing files from the health check.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub missing_count: Option<usize>,
}

impl EventProperties {
    /// Convenience builder with the always-set fields prefilled.
    pub fn new() -> Self {
        Self {
            wizard_version: Some(env!("CARGO_PKG_VERSION").to_string()),
            os: Some(platform_str()),
            ..Default::default()
        }
    }
    pub fn with_percent(mut self, p: u32) -> Self {
        self.percent = Some(p.min(100));
        self
    }
    pub fn with_bytes_written(mut self, b: u64) -> Self {
        self.bytes_written = Some(b);
        self
    }
    pub fn with_sha256_prefix(mut self, full_hash: &str) -> Self {
        // 16 hex chars = 64 bits of entropy, enough to bucket without
        // enabling trivial collision lookups. Lowercase canonical.
        let lower = full_hash.trim().to_ascii_lowercase();
        let take = lower.chars().take(16).collect::<String>();
        self.sha256_prefix = Some(take);
        self
    }
    pub fn with_attempt(mut self, a: u32) -> Self {
        self.attempt = Some(a);
        self
    }
    pub fn with_error_code(mut self, c: &'static str) -> Self {
        self.error_code = Some(c);
        self
    }
    pub fn with_closed_reason(mut self, r: &'static str) -> Self {
        self.closed_reason = Some(r);
        self
    }
    pub fn with_file_count(mut self, n: usize) -> Self {
        self.file_count = Some(n);
        self
    }
    pub fn with_missing_count(mut self, n: usize) -> Self {
        self.missing_count = Some(n);
        self
    }
}

const fn platform_str() -> &'static str {
    // `std::env::consts::OS` is a `&'static str` — safe to return
    // directly. Coarse label only: no kernel version, no locale.
    std::env::consts::OS
}

/// Reduce a Windows path like `C:\Users\alice\AppData\Local\Programs\AetherCloud-L`
/// to a redacted form. Used for the one place (install path) we want to log what
/// layout NSIS ended up using, without leaking the concrete user name.
/// Returns a static label when detection fails.
pub fn redact_path(p: &std::path::Path) -> &'static str {
    let s = p.to_string_lossy();
    let lower = s.to_ascii_lowercase();
    if lower.contains(r"\programs\aethercloud-l") {
        "programs_aethercloud_l"
    } else if lower.contains(r"\aethercloud-l") {
        "aethercloud_l_flat"
    } else if lower.contains(r"\aethercloud") {
        "aethercloud_generic"
    } else {
        "unknown_install_path"
    }
}

/// Whether telemetry should fire this process. See [`ENV_ENABLED`].
pub fn telemetry_enabled() -> bool {
    // Explicit disable env always wins.
    if let Some(v) = std::env::var_os(ENV_LEGACY_OFF) {
        if is_truthy(&v.to_string_lossy()) {
            return false;
        }
    }
    if let Some(v) = std::env::var_os(ENV_ENABLED) {
        let s = v.to_string_lossy();
        return !(is_falsy(&s));
    }
    // No explicit env: ON in release, OFF in debug. Keeps `cargo run`
    // out of the funnel.
    !cfg!(debug_assertions)
}

fn is_truthy(s: &str) -> bool {
    matches!(
        s.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}
fn is_falsy(s: &str) -> bool {
    matches!(
        s.trim().to_ascii_lowercase().as_str(),
        "0" | "false" | "no" | "off"
    )
}

/// Resolve the PostHog project key. Env overrides compiled-in default.
fn posthog_key() -> Option<String> {
    if let Ok(v) = std::env::var(ENV_POSTHOG_KEY) {
        let t = v.trim();
        if !t.is_empty() {
            return Some(t.to_string());
        }
    }
    let t = COMPILED_POSTHOG_KEY.trim();
    if t.is_empty() {
        None
    } else {
        Some(t.to_string())
    }
}

fn posthog_endpoint() -> String {
    if let Ok(v) = std::env::var(ENV_POSTHOG_HOST) {
        let t = v.trim().trim_end_matches('/');
        if !t.is_empty() {
            return format!("{t}/capture/");
        }
    }
    DEFAULT_ENDPOINT.to_string()
}

/// Persistent anonymous distinct_id. Cached at
/// `%LOCALAPPDATA%\AetherCloud-Setup\telemetry-distinct-id.txt`. Generated
/// once per install on first capture; reused for the lifetime of that
/// machine's setup directory. If that directory is wiped (e.g., by
/// `cleanup::purge()`), a fresh id is generated on the next capture —
/// that's a feature, not a bug (a clean-slate reinstall should look like
/// a new funnel).
fn distinct_id() -> std::result::Result<String, TelemetryError> {
    // Env-override path for tests and CI.
    if let Ok(v) = std::env::var(ENV_DISTINCT_ID) {
        let t = v.trim();
        if !t.is_empty() {
            return Ok(t.to_string());
        }
    }

    static CACHED: OnceLock<String> = OnceLock::new();
    if let Some(id) = CACHED.get() {
        return Ok(id.clone());
    }

    let path = distinct_id_path();
    let id = match std::fs::read_to_string(&path) {
        Ok(s) => {
            let trimmed = s.trim().to_string();
            if is_well_formed_uuid(&trimmed) {
                trimmed
            } else {
                // File exists but was corrupted / not a UUID. Regenerate.
                let fresh = uuid::Uuid::new_v4().to_string();
                write_distinct_id(&path, &fresh)?;
                fresh
            }
        }
        Err(_) => {
            let fresh = uuid::Uuid::new_v4().to_string();
            write_distinct_id(&path, &fresh)?;
            fresh
        }
    };

    let _ = CACHED.set(id.clone());
    Ok(id)
}

fn distinct_id_path() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    base.join("AetherCloud-Setup")
        .join("telemetry-distinct-id.txt")
}

fn write_distinct_id(path: &std::path::Path, id: &str) -> std::result::Result<(), TelemetryError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| TelemetryError::Io(e.to_string()))?;
    }
    std::fs::write(path, id).map_err(|e| TelemetryError::Io(e.to_string()))?;
    Ok(())
}

fn is_well_formed_uuid(s: &str) -> bool {
    uuid::Uuid::parse_str(s).is_ok()
}

/// Public capture API.
///
/// Never throws. On any failure (env missing, network, serialization)
/// logs a `tracing::warn` and returns `Ok(())`. Return type stays
/// `Result<(), TelemetryError>` so tests can explicitly assert success
/// paths, but install call sites can safely `let _ = capture(...).await;`.
pub async fn capture(
    event: Event,
    properties: EventProperties,
) -> std::result::Result<(), TelemetryError> {
    if !telemetry_enabled() {
        tracing::debug!(event = event.as_str(), "telemetry: skipped (disabled)");
        return Ok(());
    }
    let Some(key) = posthog_key() else {
        tracing::debug!(event = event.as_str(), "telemetry: skipped (no key)");
        return Ok(());
    };

    let distinct = match distinct_id() {
        Ok(d) => d,
        Err(e) => {
            tracing::warn!(error = ?e, "telemetry: distinct_id resolution failed");
            return Ok(());
        }
    };

    let endpoint = posthog_endpoint();
    let body = json!({
        "api_key": key,
        "event": event.as_str(),
        "distinct_id": distinct,
        "properties": properties,
        "timestamp": now_iso8601(),
    });

    let client = match reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .user_agent(concat!(
            "AetherCloud-Setup-Telemetry/",
            env!("CARGO_PKG_VERSION")
        ))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            tracing::warn!(error = ?e, "telemetry: reqwest client build failed");
            return Ok(());
        }
    };

    // reqwest is built with default-features=false (see Cargo.toml line 37)
    // which strips the `json` feature. Serialize by hand + set the header
    // rather than re-adding the feature just for telemetry.
    let serialized = match serde_json::to_vec(&body) {
        Ok(b) => b,
        Err(e) => {
            tracing::warn!(error = ?e, "telemetry: JSON serialization failed");
            return Err(TelemetryError::Serialize(e.to_string()));
        }
    };
    match client
        .post(&endpoint)
        .header("content-type", "application/json")
        .body(serialized)
        .send()
        .await
    {
        Ok(resp) => {
            let status = resp.status();
            if !status.is_success() {
                tracing::warn!(
                    event = event.as_str(),
                    status = status.as_u16(),
                    "telemetry: posthog returned non-2xx"
                );
                return Err(TelemetryError::HttpStatus(status.as_u16()));
            }
            tracing::debug!(event = event.as_str(), "telemetry: captured");
            Ok(())
        }
        Err(e) => {
            tracing::warn!(event = event.as_str(), error = ?e, "telemetry: network failure");
            Err(TelemetryError::Network(e.to_string()))
        }
    }
}

/// Fire-and-forget wrapper. Spawns a detached task so the caller never
/// awaits the HTTP round-trip. Safe to call from sync context via
/// `tokio::spawn` inside — if there is NO current tokio runtime
/// (e.g., `main()` before Tauri initializes) we fall back to a brief
/// throwaway current-thread runtime in a detached OS thread.
pub fn capture_fire_and_forget(event: Event, properties: EventProperties) {
    if !telemetry_enabled() {
        return;
    }
    if tokio::runtime::Handle::try_current().is_ok() {
        tokio::spawn(async move {
            let _ = capture(event, properties).await;
        });
        return;
    }
    // Pre-runtime fallback: spin a tiny single-thread runtime in a
    // detached OS thread so we can emit wizard_launched before
    // tauri::Builder::run() starts. The detached thread never blocks
    // the main thread. On any failure we drop silently.
    std::thread::Builder::new()
        .name("aether-telemetry-boot".into())
        .spawn(move || {
            match tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            {
                Ok(rt) => {
                    rt.block_on(async move {
                        let _ = capture(event, properties).await;
                    });
                }
                Err(e) => {
                    tracing::warn!(error = ?e, "telemetry: boot-runtime build failed");
                }
            }
        })
        .ok();
}

/// Compact ISO-8601 UTC timestamp. Hand-rolled to avoid a `chrono` dep.
fn now_iso8601() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (y, mo, d, h, mi, s) = civil_from_days(secs);
    format!("{y:04}-{mo:02}-{d:02}T{h:02}:{mi:02}:{s:02}Z")
}

// Seconds-since-epoch -> (year, month, day, hour, min, sec). Based on
// Howard Hinnant's date algorithm. Inlined, no deps.
fn civil_from_days(secs: u64) -> (i32, u32, u32, u32, u32, u32) {
    let days = (secs / 86_400) as i64;
    let sod = (secs % 86_400) as u32;
    let hour = sod / 3600;
    let min = (sod % 3600) / 60;
    let sec = sod % 60;

    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y as i32, m as u32, d as u32, hour, min, sec)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn event_wire_names_stable() {
        assert_eq!(Event::WizardLaunched.as_str(), "wizard_launched");
        assert_eq!(Event::InstallerStarted.as_str(), "installer_started");
        assert_eq!(Event::DownloadStarted.as_str(), "download_started");
        assert_eq!(Event::DownloadProgress.as_str(), "download_progress");
        assert_eq!(Event::DownloadCompleted.as_str(), "download_completed");
        assert_eq!(Event::VerifyStarted.as_str(), "verify_started");
        assert_eq!(Event::VerifyCompleted.as_str(), "verify_completed");
        assert_eq!(Event::VerifyFailed.as_str(), "verify_failed");
        assert_eq!(Event::InstallStarted.as_str(), "install_started");
        assert_eq!(Event::InstallProgress.as_str(), "install_progress");
        assert_eq!(Event::InstallCompleted.as_str(), "install_completed");
        assert_eq!(Event::InstallFailed.as_str(), "install_failed");
        assert_eq!(Event::WizardClosed.as_str(), "wizard_closed");
    }

    #[test]
    fn event_count_is_thirteen() {
        let all = [
            Event::WizardLaunched,
            Event::InstallerStarted,
            Event::DownloadStarted,
            Event::DownloadProgress,
            Event::DownloadCompleted,
            Event::VerifyStarted,
            Event::VerifyCompleted,
            Event::VerifyFailed,
            Event::InstallStarted,
            Event::InstallProgress,
            Event::InstallCompleted,
            Event::InstallFailed,
            Event::WizardClosed,
        ];
        assert_eq!(all.len(), 13);
    }

    #[test]
    fn properties_sha256_prefix_trims_to_sixteen() {
        let full = "abcdef0123456789ABCDEF0123456789abcdef0123456789ABCDEF0123456789";
        let p = EventProperties::new().with_sha256_prefix(full);
        assert_eq!(p.sha256_prefix.as_deref(), Some("abcdef0123456789"));
    }

    #[test]
    fn properties_sha256_handles_short_input() {
        let p = EventProperties::new().with_sha256_prefix("abcd");
        assert_eq!(p.sha256_prefix.as_deref(), Some("abcd"));
    }

    #[test]
    fn properties_percent_clamped() {
        let p = EventProperties::new().with_percent(250);
        assert_eq!(p.percent, Some(100));
    }

    #[test]
    fn redact_path_strips_user_dirs() {
        use std::path::Path;
        assert_eq!(
            redact_path(Path::new(
                r"C:\Users\alice\AppData\Local\Programs\AetherCloud-L\AetherCloud-L.exe"
            )),
            "programs_aethercloud_l"
        );
        assert_eq!(
            redact_path(Path::new(r"C:\Users\bob\AppData\Local\aethercloud-l\bin\x.exe")),
            "aethercloud_l_flat"
        );
        assert_eq!(
            redact_path(Path::new(r"D:\Games\Steam\X.exe")),
            "unknown_install_path"
        );
    }

    #[test]
    fn truthy_falsy_parsing() {
        assert!(is_truthy("1"));
        assert!(is_truthy("true"));
        assert!(is_truthy(" YES "));
        assert!(!is_truthy("0"));
        assert!(is_falsy("0"));
        assert!(is_falsy("off"));
        assert!(!is_falsy("1"));
    }

    #[test]
    fn telemetry_disabled_when_legacy_off_set() {
        let prev_enabled = std::env::var(ENV_ENABLED).ok();
        let prev_off = std::env::var(ENV_LEGACY_OFF).ok();
        std::env::set_var(ENV_LEGACY_OFF, "1");
        assert!(!telemetry_enabled());
        std::env::remove_var(ENV_LEGACY_OFF);
        if let Some(v) = prev_enabled {
            std::env::set_var(ENV_ENABLED, v);
        }
        if let Some(v) = prev_off {
            std::env::set_var(ENV_LEGACY_OFF, v);
        }
    }

    #[test]
    fn iso8601_well_formed() {
        let s = now_iso8601();
        assert_eq!(s.len(), 20);
        assert!(s.ends_with('Z'));
        assert!(s.as_bytes()[4] == b'-');
        assert!(s.as_bytes()[7] == b'-');
        assert!(s.as_bytes()[10] == b'T');
        assert!(s.as_bytes()[13] == b':');
        assert!(s.as_bytes()[16] == b':');
    }

    #[test]
    fn civil_from_days_known_anchor() {
        let (y, mo, d, h, mi, s) = civil_from_days(0);
        assert_eq!((y, mo, d, h, mi, s), (1970, 1, 1, 0, 0, 0));
        let (y, mo, d, ..) = civil_from_days(86_400);
        assert_eq!((y, mo, d), (1970, 1, 2));
    }

    #[test]
    fn distinct_id_from_env_overrides_file() {
        let prev = std::env::var(ENV_DISTINCT_ID).ok();
        std::env::set_var(ENV_DISTINCT_ID, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        let id = distinct_id().expect("env path");
        assert_eq!(id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
        match prev {
            Some(v) => std::env::set_var(ENV_DISTINCT_ID, v),
            None => std::env::remove_var(ENV_DISTINCT_ID),
        }
    }

    #[test]
    fn is_well_formed_uuid_accepts_v4_rejects_junk() {
        assert!(is_well_formed_uuid("550e8400-e29b-41d4-a716-446655440000"));
        assert!(!is_well_formed_uuid("not-a-uuid"));
        assert!(!is_well_formed_uuid(""));
    }

    #[tokio::test]
    async fn capture_returns_ok_when_disabled() {
        let prev_off = std::env::var(ENV_LEGACY_OFF).ok();
        std::env::set_var(ENV_LEGACY_OFF, "1");
        let r = capture(Event::WizardLaunched, EventProperties::new()).await;
        assert!(r.is_ok(), "disabled path must return Ok, got {:?}", r);
        match prev_off {
            Some(v) => std::env::set_var(ENV_LEGACY_OFF, v),
            None => std::env::remove_var(ENV_LEGACY_OFF),
        }
    }
}
