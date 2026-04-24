//! Integration tests for the PostHog install-funnel telemetry module.
//!
//! Covers the contract documented at the top of `src/telemetry.rs`:
//!   1. Every event of the 13-event funnel can be captured and arrives
//!      at the mock PostHog endpoint with the expected wire name.
//!   2. Network failures (mock returns 500) do NOT throw into the
//!      caller path — `capture` returns an error that the caller can
//!      drop; `capture_fire_and_forget` never panics.
//!   3. Sanitization rules upheld:
//!      - `EventProperties::with_sha256_prefix` truncates to 16 hex
//!      - `redact_path` reduces user-home paths to static layout labels
//!      - No raw paths, no full-length hashes, no attacker-shaped strings
//!        leak into the POST body.
//!
//! Uses `wiremock` (already a dev-dependency, see Cargo.toml line 47).
//! We spin up a local mock for the `/capture/` route and point
//! `AETHER_POSTHOG_HOST` at it so the production endpoint is never
//! touched.
//!
//! Tests manipulate process-wide env vars; we serialize them under
//! `ENV_LOCK` and snapshot+restore via `EnvGuard` so no cross-test
//! leakage can occur even under the default multi-thread test harness.

use aethercloud_installer::telemetry::{
    capture, redact_path, Event, EventProperties, ENV_DISTINCT_ID, ENV_ENABLED,
    ENV_LEGACY_OFF, ENV_POSTHOG_HOST, ENV_POSTHOG_KEY,
};
use serde_json::Value;
use std::sync::Mutex;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// One test at a time manipulates env vars. We serialize via Mutex
/// rather than relying on `--test-threads=1` so the test suite still
/// works under default `cargo test`.
static ENV_LOCK: Mutex<()> = Mutex::new(());

/// RAII handle that snapshots a set of env vars at construction and
/// restores them on drop.
struct EnvGuard {
    prev: Vec<(String, Option<String>)>,
}
impl EnvGuard {
    fn new(keys: &[&str]) -> Self {
        let prev = keys
            .iter()
            .map(|k| (k.to_string(), std::env::var(k).ok()))
            .collect();
        Self { prev }
    }
}
impl Drop for EnvGuard {
    fn drop(&mut self) {
        for (k, v) in &self.prev {
            match v {
                Some(val) => std::env::set_var(k, val),
                None => std::env::remove_var(k),
            }
        }
    }
}

/// Spin up a wiremock server that accepts a single POST to `/capture/`,
/// sets env for the telemetry module to point at it with a synthetic
/// key + distinct_id, and returns the server plus the capture result.
async fn capture_with_mock(
    event: Event,
    props: EventProperties,
    mock_status: u16,
) -> (
    wiremock::MockServer,
    std::result::Result<(), aethercloud_installer::telemetry::TelemetryError>,
) {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/capture/"))
        .respond_with(ResponseTemplate::new(mock_status))
        .mount(&server)
        .await;

    std::env::set_var(ENV_ENABLED, "1");
    std::env::remove_var(ENV_LEGACY_OFF);
    std::env::set_var(ENV_POSTHOG_KEY, "ph_test_synthetic_key_0000");
    std::env::set_var(ENV_POSTHOG_HOST, server.uri());
    std::env::set_var(
        ENV_DISTINCT_ID,
        "11111111-2222-3333-4444-555555555555",
    );

    let r = capture(event, props).await;
    (server, r)
}

#[tokio::test]
async fn every_event_is_captured_with_correct_wire_name() {
    let _g = ENV_LOCK.lock().unwrap();
    let _env = EnvGuard::new(&[
        ENV_ENABLED,
        ENV_LEGACY_OFF,
        ENV_POSTHOG_KEY,
        ENV_POSTHOG_HOST,
        ENV_DISTINCT_ID,
    ]);

    let events = [
        (Event::WizardLaunched, "wizard_launched"),
        (Event::InstallerStarted, "installer_started"),
        (Event::DownloadStarted, "download_started"),
        (Event::DownloadProgress, "download_progress"),
        (Event::DownloadCompleted, "download_completed"),
        (Event::VerifyStarted, "verify_started"),
        (Event::VerifyCompleted, "verify_completed"),
        (Event::VerifyFailed, "verify_failed"),
        (Event::InstallStarted, "install_started"),
        (Event::InstallProgress, "install_progress"),
        (Event::InstallCompleted, "install_completed"),
        (Event::InstallFailed, "install_failed"),
        (Event::WizardClosed, "wizard_closed"),
    ];
    assert_eq!(events.len(), 13, "funnel is promised to be 13 events wide");

    for (event, wire_name) in events {
        let (server, result) =
            capture_with_mock(event, EventProperties::new(), 200).await;
        assert!(
            result.is_ok(),
            "capture for {wire_name} should return Ok, got {result:?}"
        );

        let requests = server.received_requests().await.expect("mock captures");
        assert_eq!(
            requests.len(),
            1,
            "{wire_name}: expected one POST, got {}",
            requests.len()
        );
        let body: Value = serde_json::from_slice(&requests[0].body)
            .unwrap_or_else(|e| panic!("{wire_name}: bad JSON in POST body: {e}"));
        assert_eq!(
            body.get("event").and_then(Value::as_str),
            Some(wire_name),
            "{wire_name}: wrong event field"
        );
        assert_eq!(
            body.get("distinct_id").and_then(Value::as_str),
            Some("11111111-2222-3333-4444-555555555555"),
            "{wire_name}: distinct_id must match injected env"
        );
        let ts = body
            .get("timestamp")
            .and_then(Value::as_str)
            .expect("timestamp field");
        assert_eq!(ts.len(), 20, "{wire_name}: ts must be YYYY-MM-DDTHH:MM:SSZ");
        assert!(ts.ends_with('Z'), "{wire_name}: ts must end with Z");
    }
}

#[tokio::test]
async fn failure_in_posthog_does_not_propagate_to_caller() {
    let _g = ENV_LOCK.lock().unwrap();
    let _env = EnvGuard::new(&[
        ENV_ENABLED,
        ENV_LEGACY_OFF,
        ENV_POSTHOG_KEY,
        ENV_POSTHOG_HOST,
        ENV_DISTINCT_ID,
    ]);

    let (_server, result) =
        capture_with_mock(Event::InstallFailed, EventProperties::new(), 500).await;
    assert!(result.is_err(), "500 should surface as Err, got {result:?}");
    // Reaching this line proves: no panic.
}

#[tokio::test]
async fn disabled_by_legacy_env_returns_ok_without_posting() {
    let _g = ENV_LOCK.lock().unwrap();
    let _env = EnvGuard::new(&[
        ENV_ENABLED,
        ENV_LEGACY_OFF,
        ENV_POSTHOG_KEY,
        ENV_POSTHOG_HOST,
    ]);

    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/capture/"))
        .respond_with(ResponseTemplate::new(200))
        .mount(&server)
        .await;

    std::env::set_var(ENV_LEGACY_OFF, "1");
    std::env::set_var(ENV_POSTHOG_KEY, "ph_test_synthetic_key_0000");
    std::env::set_var(ENV_POSTHOG_HOST, server.uri());

    let r = capture(Event::WizardLaunched, EventProperties::new()).await;
    assert!(r.is_ok(), "disabled must return Ok, got {r:?}");

    let requests = server.received_requests().await.expect("mock captures");
    assert!(
        requests.is_empty(),
        "disabled telemetry must not POST anything (got {} reqs)",
        requests.len()
    );
}

#[tokio::test]
async fn missing_key_returns_ok_without_posting() {
    let _g = ENV_LOCK.lock().unwrap();
    let _env = EnvGuard::new(&[
        ENV_ENABLED,
        ENV_LEGACY_OFF,
        ENV_POSTHOG_KEY,
        ENV_POSTHOG_HOST,
    ]);

    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/capture/"))
        .respond_with(ResponseTemplate::new(200))
        .mount(&server)
        .await;

    std::env::set_var(ENV_ENABLED, "1");
    std::env::remove_var(ENV_LEGACY_OFF);
    std::env::remove_var(ENV_POSTHOG_KEY);
    std::env::set_var(ENV_POSTHOG_HOST, server.uri());

    let r = capture(Event::WizardLaunched, EventProperties::new()).await;
    assert!(r.is_ok(), "no-key path must return Ok, got {r:?}");

    let requests = server.received_requests().await.expect("mock captures");
    assert!(
        requests.is_empty(),
        "no-key must not POST anything (got {} reqs)",
        requests.len()
    );
}

#[tokio::test]
async fn properties_payload_shape_and_sanitization() {
    let _g = ENV_LOCK.lock().unwrap();
    let _env = EnvGuard::new(&[
        ENV_ENABLED,
        ENV_LEGACY_OFF,
        ENV_POSTHOG_KEY,
        ENV_POSTHOG_HOST,
        ENV_DISTINCT_ID,
    ]);

    // Hand-crafted properties covering every optional field. We verify:
    // - sha256_prefix is truncated to 16 hex chars
    // - percent / bytes_written / attempt / file_count / missing_count
    //   serialize as JSON numbers
    // - error_code / closed_reason serialize as JSON strings
    // - wizard_version and os are always set
    let (server, result) = capture_with_mock(
        Event::DownloadCompleted,
        EventProperties::new()
            .with_percent(99)
            .with_bytes_written(1_234_567)
            .with_sha256_prefix(
                "abcdef0123456789ABCDEF0123456789abcdef0123456789ABCDEF0123456789",
            )
            .with_attempt(2)
            .with_error_code("download_ok")
            .with_closed_reason("success")
            .with_file_count(42)
            .with_missing_count(0),
        200,
    )
    .await;
    assert!(result.is_ok(), "{result:?}");

    let reqs = server.received_requests().await.unwrap();
    assert_eq!(reqs.len(), 1);
    let body: Value = serde_json::from_slice(&reqs[0].body).unwrap();
    let p = body.get("properties").expect("properties");
    assert_eq!(
        p.get("sha256_prefix").and_then(Value::as_str),
        Some("abcdef0123456789"),
        "sha256_prefix MUST be truncated to 16 hex — current length violates sanitization"
    );
    assert_eq!(p.get("percent").and_then(Value::as_u64), Some(99));
    assert_eq!(p.get("bytes_written").and_then(Value::as_u64), Some(1_234_567));
    assert_eq!(p.get("attempt").and_then(Value::as_u64), Some(2));
    assert_eq!(p.get("error_code").and_then(Value::as_str), Some("download_ok"));
    assert_eq!(p.get("closed_reason").and_then(Value::as_str), Some("success"));
    assert_eq!(p.get("file_count").and_then(Value::as_u64), Some(42));
    assert_eq!(p.get("missing_count").and_then(Value::as_u64), Some(0));
    assert!(p.get("wizard_version").is_some(), "wizard_version always set");
    assert!(p.get("os").is_some(), "os always set");

    // Sanitization regression guards: the POST body must not contain
    // any user-home-path, Stripe-id-like string, or the full hash.
    let body_str = String::from_utf8_lossy(&reqs[0].body);
    assert!(
        !body_str.to_ascii_lowercase().contains(r"c:\users\"),
        "body leaked a Windows user-home path: {body_str}"
    );
    assert!(
        !body_str.contains("cs_test_"),
        "body leaked a Stripe-session-id-like string: {body_str}"
    );
    assert!(
        !body_str.contains("pi_live_"),
        "body leaked a Stripe-payment-intent-live-like string: {body_str}"
    );
    // Full 64-char hash must NEVER appear — only the 16-char prefix.
    assert!(
        !body_str.contains(
            "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
        ),
        "full hash leaked into body: {body_str}"
    );
}

#[test]
fn redact_path_never_returns_caller_supplied_string() {
    // Property-style: regardless of the input path, the returned label
    // must be one of the four static tokens the module defines.
    use std::path::Path;
    let candidates = [
        r"C:\Users\alice\AppData\Local\Programs\AetherCloud-L\app.exe",
        r"C:\Users\bob\AppData\Local\aethercloud-l\bin\x.exe",
        r"C:\Users\charlie\AppData\Local\AetherCloud\x",
        r"D:\Games\Steam\x.exe",
        r"\\server\share\AetherCloud-L\x.exe",
        "/etc/passwd",
        "",
    ];
    let allowed: &[&str] = &[
        "programs_aethercloud_l",
        "aethercloud_l_flat",
        "aethercloud_generic",
        "unknown_install_path",
    ];
    for c in candidates {
        let label = redact_path(Path::new(c));
        assert!(
            allowed.contains(&label),
            "redact_path leaked non-static label for {c:?}: {label:?}"
        );
        assert!(
            !label.contains('\\') && !label.contains('/') && !label.contains(':'),
            "label {label:?} contains path chars"
        );
    }
}
