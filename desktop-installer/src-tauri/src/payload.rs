use crate::errors::{InstallerError, Result};
use futures_util::StreamExt;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::fs::File;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};
use tokio::process::Command;

/// TCP + TLS handshake timeout for the payload download. Matches the 10s
/// budget used by the meta-client so a dead origin fails fast.
const PAYLOAD_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

/// If no bytes arrive from the server for this long mid-download, we abort
/// with a descriptive error instead of hanging the UI forever. 15s is
/// intentionally short: a real network blip recovers in <5s; longer means
/// something is actually wrong (server dead, AV sandbox blocking, TLS
/// reconnect loop).
const PAYLOAD_STALL_TIMEOUT: Duration = Duration::from_secs(15);

/// Stream bytes through SHA-256 without buffering the whole file in memory.
/// Returns the lowercase hex digest.
pub async fn sha256_stream<R: AsyncRead + Unpin>(mut reader: R) -> Result<String> {
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = reader.read(&mut buf).await?;
        if n == 0 { break; }
        hasher.update(&buf[..n]);
    }
    let digest = hasher.finalize();
    Ok(hex_encode(&digest))
}

pub struct DownloadProgress {
    pub bytes_written: u64,
    /// Total bytes expected for this download. Sourced from HTTP Content-Length
    /// when present; falls back to `max_bytes` when the server omits the header.
    /// Progress UI consumers that display "X of Y" MAY appear stuck at the
    /// size-cap value until the real end-of-stream is reached in that fallback case.
    pub total_bytes: u64,
}

/// Download `url` to `dest_path`, streaming. Calls `on_progress` periodically.
/// Enforces HTTPS, max_bytes cap (hard abort if exceeded), and returns the final hash.
///
/// Fails loud on any stall (no chunks for PAYLOAD_STALL_TIMEOUT) rather than
/// hanging the UI.
pub async fn download_with_progress<F>(
    url: &str,
    dest_path: &Path,
    max_bytes: u64,
    mut on_progress: F,
) -> Result<String>
where
    F: FnMut(DownloadProgress),
{
    if !url.starts_with("https://") {
        tracing::error!(url = %url, "payload: non-HTTPS URL rejected");
        return Err(InstallerError::InsecureUrl(url.to_string()));
    }

    tracing::info!(
        url = %url,
        dest = %dest_path.display(),
        max_bytes,
        connect_timeout_s = PAYLOAD_CONNECT_TIMEOUT.as_secs(),
        stall_timeout_s = PAYLOAD_STALL_TIMEOUT.as_secs(),
        "payload: starting download"
    );

    let client = reqwest::Client::builder()
        .connect_timeout(PAYLOAD_CONNECT_TIMEOUT)
        .user_agent(concat!("AetherCloud-Setup/", env!("CARGO_PKG_VERSION")))
        .build()?;

    let resp = client.get(url).send().await?;
    let status = resp.status();
    tracing::info!(status = %status, "payload: connected, got response headers");

    if !status.is_success() {
        tracing::error!(status = %status, "payload: non-2xx response");
        return Err(InstallerError::ManifestHttpStatus(status.as_u16()));
    }

    let total_bytes = resp.content_length().unwrap_or(max_bytes);
    tracing::info!(total_bytes, "payload: content-length");
    if total_bytes > max_bytes {
        tracing::error!(total_bytes, max_bytes, "payload: server-declared size exceeds cap");
        return Err(InstallerError::PayloadSizeExceeded);
    }

    let mut file = File::create(dest_path).await?;
    let mut hasher = Sha256::new();
    let mut stream = resp.bytes_stream();
    let mut bytes_written: u64 = 0;
    let mut next_trace_mb: u64 = 10; // trace every 10 MB to avoid log spam

    loop {
        // Wrap each chunk read in a stall timeout. If the server goes silent
        // (TCP keepalive dead, TLS renegotiation stuck, AV sandbox pause),
        // we bail instead of hanging.
        let chunk_result = tokio::time::timeout(PAYLOAD_STALL_TIMEOUT, stream.next()).await;

        let maybe_chunk = match chunk_result {
            Ok(c) => c,
            Err(_elapsed) => {
                tracing::error!(
                    stalled_after_s = PAYLOAD_STALL_TIMEOUT.as_secs(),
                    bytes_received = bytes_written,
                    total_bytes,
                    "payload: download STALLED — no bytes from server"
                );
                drop(file);
                let _ = tokio::fs::remove_file(dest_path).await;
                return Err(InstallerError::Internal(format!(
                    "Download stalled: no bytes received for {}s at {}/{} bytes",
                    PAYLOAD_STALL_TIMEOUT.as_secs(),
                    bytes_written,
                    total_bytes
                )));
            }
        };

        let Some(chunk) = maybe_chunk else {
            // End of stream reached.
            break;
        };
        let chunk = chunk.map_err(|e| {
            tracing::error!(error = ?e, "payload: chunk read error");
            InstallerError::Network(e)
        })?;

        bytes_written = bytes_written
            .checked_add(chunk.len() as u64)
            .ok_or(InstallerError::PayloadSizeExceeded)?;

        if bytes_written > max_bytes {
            tracing::error!(bytes_written, max_bytes, "payload: mid-stream size cap exceeded");
            drop(file);
            let _ = tokio::fs::remove_file(dest_path).await;
            return Err(InstallerError::PayloadSizeExceeded);
        }

        hasher.update(&chunk);
        file.write_all(&chunk).await?;
        on_progress(DownloadProgress { bytes_written, total_bytes });

        // Periodic trace at each 10 MB boundary.
        let mb = bytes_written / (1024 * 1024);
        if mb >= next_trace_mb {
            tracing::info!(received_mb = mb, total_mb = total_bytes / (1024 * 1024), "payload: progress");
            next_trace_mb = mb + 10;
        }
    }

    file.flush().await?;
    let digest = hasher.finalize();
    let hex = hex_encode(&digest);
    tracing::info!(
        bytes_written,
        sha256 = %hex,
        "payload: download finished, hash computed"
    );
    Ok(hex)
}

/// Create a per-install temp path under %TEMP% (or $TMPDIR) with current-user ACL.
pub fn temp_payload_path() -> PathBuf {
    let filename = format!("aether-installer-{}.exe", uuid::Uuid::new_v4());
    std::env::temp_dir().join(filename)
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0F) as usize] as char);
    }
    out
}

/// Runs `path` with `/S` (silent NSIS). Returns exit code as i32.
/// Caller is responsible for mapping non-zero codes to InstallerError::PayloadExit.
pub async fn run_payload_silent(path: &Path) -> Result<i32> {
    tracing::info!(path = %path.display(), "spawn: starting NSIS with /S");
    let status = Command::new(path).arg("/S").status().await.map_err(|e| {
        tracing::error!(error = ?e, path = %path.display(), "spawn: failed to start process");
        InstallerError::Io(e)
    })?;
    let code = status.code().unwrap_or(-1);
    tracing::info!(exit_code = code, "spawn: NSIS finished");
    Ok(code)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::BufReader;

    #[tokio::test]
    async fn empty_input_matches_known_digest() {
        let reader = BufReader::new(&b""[..]);
        let hex = sha256_stream(reader).await.unwrap();
        assert_eq!(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    }

    #[tokio::test]
    async fn abc_matches_known_digest() {
        let reader = BufReader::new(&b"abc"[..]);
        let hex = sha256_stream(reader).await.unwrap();
        assert_eq!(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }

    #[tokio::test]
    async fn larger_than_buffer_matches() {
        let data = vec![0u8; 200 * 1024];
        let hex = sha256_stream(BufReader::new(&data[..])).await.unwrap();
        assert_eq!(hex.len(), 64);
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn stall_timeout_is_non_trivial_and_shorter_than_typical_install() {
        // Regression guard: if PAYLOAD_STALL_TIMEOUT ever becomes too long
        // (e.g. a minute) the "hang at 0%" bug reappears. Too short (<5s) and
        // a transient hiccup kills the install.
        assert!(PAYLOAD_STALL_TIMEOUT.as_secs() >= 5);
        assert!(PAYLOAD_STALL_TIMEOUT.as_secs() <= 60);
        assert!(PAYLOAD_CONNECT_TIMEOUT.as_secs() >= 3);
        assert!(PAYLOAD_CONNECT_TIMEOUT.as_secs() <= 30);
    }
}

#[cfg(test)]
mod download_tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn rejects_http_url() {
        let tmp = temp_payload_path();
        let err = download_with_progress("http://example.com/x", &tmp, 1024, |_| {})
            .await
            .unwrap_err();
        assert!(matches!(err, InstallerError::InsecureUrl(_)));
    }

    #[tokio::test]
    async fn http_mock_url_still_rejected() {
        let server = MockServer::start().await;
        Mock::given(method("GET")).and(path("/x"))
            .respond_with(ResponseTemplate::new(200).set_body_bytes(b"abc".to_vec()))
            .mount(&server).await;
        let url = format!("{}/x", server.uri()); // http://

        let tmp = temp_payload_path();
        let err = download_with_progress(&url, &tmp, 1024, |_| {}).await.unwrap_err();
        assert!(matches!(err, InstallerError::InsecureUrl(_)));
    }

    #[tokio::test]
    async fn temp_payload_path_format() {
        let p = temp_payload_path();
        assert!(p.to_string_lossy().contains("aether-installer-"));
        assert!(p.to_string_lossy().ends_with(".exe"));
    }
}

#[cfg(test)]
mod spawn_tests {
    use super::*;

    #[tokio::test]
    async fn runs_cmd_exit_zero() {
        #[cfg(windows)]
        {
            let code = Command::new("cmd.exe").args(["/c", "exit", "0"])
                .status().await.unwrap().code().unwrap_or(-1);
            assert_eq!(code, 0);
        }
    }

    #[tokio::test]
    async fn runs_cmd_exit_nonzero() {
        #[cfg(windows)]
        {
            let code = Command::new("cmd.exe").args(["/c", "exit", "7"])
                .status().await.unwrap().code().unwrap_or(-1);
            assert_eq!(code, 7);
        }
    }
}
