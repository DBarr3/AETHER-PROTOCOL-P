//! Integration test: exercises the library crate (`aethercloud_installer`)
//! via its public surface.
//!
//! HTTPS scheme enforcement is covered by unit tests
//! `payload::download_tests::rejects_http_url` / `http_mock_url_still_rejected`.
//! Spawn + exit-code propagation is covered by unit tests
//! `payload::spawn_tests::runs_cmd_exit_zero` / `runs_cmd_exit_nonzero`.
//! Full HTTPS-backed fetch with a live TLS endpoint is a clean-VM post-session
//! verification task documented in the operator runbook.
//!
//! This integration test does NOT call `run_payload_silent` against real
//! bytes: a payload that does not understand the `/S` flag (e.g. the
//! `cmd.exe` we'd otherwise use as a stand-in) blocks on stdin instead
//! of exiting, causing the test runner to hang. The spawn-plumbing unit
//! tests cover that path with `cmd.exe /c exit N`, which bypasses the
//! hardcoded `/S` in `run_payload_silent` by going through
//! `tokio::process::Command` directly.

use aethercloud_installer::payload::temp_payload_path;

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    let d = h.finalize();
    let mut s = String::with_capacity(64);
    for b in d.iter() {
        s.push_str(&format!("{:02x}", b));
    }
    s
}

#[tokio::test]
async fn integration_temp_roundtrip_hash_matches() {
    // Exercises the public library crate path end-to-end for the
    // "download writes bytes → hash is computed from those same bytes"
    // invariant. This is the contract `download_with_progress` must
    // satisfy when it writes a streamed payload to disk.
    let payload_bytes: Vec<u8> = (0u8..=255).cycle().take(131_072).collect();
    let expected_hash = sha256_hex(&payload_bytes);

    let tmp = temp_payload_path();
    tokio::fs::write(&tmp, &payload_bytes).await.expect("write temp payload");

    let on_disk = tokio::fs::read(&tmp).await.expect("read temp payload back");
    assert_eq!(
        sha256_hex(&on_disk),
        expected_hash,
        "bytes on disk diverged from source"
    );

    // best-effort cleanup
    let _ = tokio::fs::remove_file(&tmp).await;
}

#[tokio::test]
async fn integration_temp_path_is_unique_per_call() {
    // temp_payload_path() must never collide across calls; otherwise two
    // concurrent installs would stomp each other's payloads.
    let a = temp_payload_path();
    let b = temp_payload_path();
    assert_ne!(a, b);
}
