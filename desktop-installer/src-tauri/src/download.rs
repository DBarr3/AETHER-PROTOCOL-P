use crate::errors::{InstallerError, Result};
use futures_util::StreamExt;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};
use tokio::fs::File;
use tokio::io::AsyncWriteExt;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(60);
const TOTAL_TIMEOUT: Duration = Duration::from_secs(600);
const MAX_DOWNLOAD_SIZE: u64 = 500 * 1024 * 1024;
const MAX_RETRIES: u32 = 3;
const STALL_TIMEOUT: Duration = Duration::from_secs(30);
const INITIAL_BACKOFF: Duration = Duration::from_secs(2);
const STALE_PART_MAX_AGE: Duration = Duration::from_secs(24 * 3600);

pub struct DownloadResult {
    pub path: PathBuf,
    pub sha256: String,
    pub bytes_written: u64,
}

pub struct DownloadProgress {
    pub bytes_written: u64,
    pub total_bytes: u64,
    pub attempt: u32,
}

pub fn part_path(final_path: &Path) -> PathBuf {
    let mut p = final_path.as_os_str().to_owned();
    p.push(".part");
    PathBuf::from(p)
}

fn build_client() -> reqwest::Result<reqwest::Client> {
    reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(TOTAL_TIMEOUT)
        .user_agent(concat!("AetherCloud-Setup/", env!("CARGO_PKG_VERSION")))
        .build()
}

/// Download `url` to `final_path` with full hygiene:
/// - Writes to a `.part` file first, renamed atomically only on SHA-256 match
/// - Enforces max download size (500 MB cap)
/// - 60s connect timeout, 10 min total timeout, 30s stall detection
/// - Retries with exponential backoff (max 3 attempts)
/// - Validates Content-Length header; warns if absent
/// - On any failure, the `.part` file is cleaned up
pub async fn download_verified<F>(
    url: &str,
    final_path: &Path,
    expected_sha256: &str,
    max_bytes: u64,
    mut on_progress: F,
) -> Result<DownloadResult>
where
    F: FnMut(DownloadProgress),
{
    if !url.starts_with("https://") {
        return Err(InstallerError::InsecureUrl(url.to_string()));
    }

    let cap = max_bytes.min(MAX_DOWNLOAD_SIZE);
    let client = build_client()?;
    let part = part_path(final_path);
    let expected = expected_sha256.to_ascii_lowercase();

    let mut last_err = None;
    for attempt in 1..=MAX_RETRIES {
        tracing::info!(attempt, max = MAX_RETRIES, url, "download: attempt starting");

        match download_to_part(&client, url, &part, cap, |bw, tb| {
            on_progress(DownloadProgress {
                bytes_written: bw,
                total_bytes: tb,
                attempt,
            });
        })
        .await
        {
            Ok((hash, bytes)) => {
                if hash != expected {
                    tracing::error!(expected = %expected, got = %hash, "download: SHA-256 mismatch — deleting .part");
                    let _ = tokio::fs::remove_file(&part).await;
                    return Err(InstallerError::PayloadHashMismatch {
                        expected: expected.clone(),
                        got: hash,
                    });
                }

                std::fs::rename(&part, final_path).map_err(|e| {
                    tracing::error!(error = ?e, "download: atomic rename failed");
                    InstallerError::Io(e)
                })?;

                tracing::info!(
                    path = %final_path.display(),
                    sha256 = %hash,
                    bytes = bytes,
                    "download: verified and finalized"
                );
                return Ok(DownloadResult {
                    path: final_path.to_path_buf(),
                    sha256: hash,
                    bytes_written: bytes,
                });
            }
            Err(e) => {
                tracing::warn!(attempt, error = ?e, "download: attempt failed");
                let _ = tokio::fs::remove_file(&part).await;
                last_err = Some(e);

                if attempt < MAX_RETRIES {
                    let backoff = INITIAL_BACKOFF * 2u32.pow(attempt - 1);
                    tracing::info!(backoff_s = backoff.as_secs(), "download: backing off");
                    tokio::time::sleep(backoff).await;
                }
            }
        }
    }

    Err(last_err.unwrap_or_else(|| {
        InstallerError::Internal("download exhausted all retries".into())
    }))
}

async fn download_to_part<F>(
    client: &reqwest::Client,
    url: &str,
    part_path: &Path,
    max_bytes: u64,
    mut on_progress: F,
) -> Result<(String, u64)>
where
    F: FnMut(u64, u64),
{
    let resp = client.get(url).send().await?;
    let status = resp.status();
    if !status.is_success() {
        return Err(InstallerError::ManifestHttpStatus(status.as_u16()));
    }

    let total_bytes = match resp.content_length() {
        Some(len) => {
            if len > max_bytes {
                tracing::error!(content_length = len, max = max_bytes, "download: declared size exceeds cap");
                return Err(InstallerError::PayloadSizeExceeded);
            }
            len
        }
        None => {
            tracing::warn!(max_bytes, "download: no Content-Length header; enforcing cap");
            max_bytes
        }
    };

    let mut file = File::create(part_path).await?;
    let mut hasher = Sha256::new();
    let mut stream = resp.bytes_stream();
    let mut bytes_written: u64 = 0;

    loop {
        let chunk_result = tokio::time::timeout(STALL_TIMEOUT, stream.next()).await;
        let maybe_chunk = match chunk_result {
            Ok(c) => c,
            Err(_) => {
                file.flush().await.ok();
                drop(file);
                tracing::error!(
                    stall_s = STALL_TIMEOUT.as_secs(),
                    bytes = bytes_written,
                    "download: stalled"
                );
                return Err(InstallerError::Internal(format!(
                    "Download stalled: no data for {}s at {}/{} bytes",
                    STALL_TIMEOUT.as_secs(),
                    bytes_written,
                    total_bytes
                )));
            }
        };

        let Some(chunk) = maybe_chunk else {
            break;
        };
        let chunk = chunk.map_err(InstallerError::Network)?;

        bytes_written = bytes_written
            .checked_add(chunk.len() as u64)
            .ok_or(InstallerError::PayloadSizeExceeded)?;

        if bytes_written > max_bytes {
            file.flush().await.ok();
            drop(file);
            tracing::error!(bytes = bytes_written, max = max_bytes, "download: exceeded cap mid-stream");
            return Err(InstallerError::PayloadSizeExceeded);
        }

        hasher.update(&chunk);
        file.write_all(&chunk).await?;
        on_progress(bytes_written, total_bytes);
    }

    file.flush().await?;
    let digest = hasher.finalize();
    Ok((hex_encode(&digest), bytes_written))
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

/// Scan a directory for `.part` files older than 24 hours and remove them.
/// Called on app startup to clean up interrupted downloads.
pub fn cleanup_stale_parts(dir: &Path) -> Vec<PathBuf> {
    cleanup_stale_parts_with_age(dir, STALE_PART_MAX_AGE)
}

pub fn cleanup_stale_parts_with_age(dir: &Path, max_age: Duration) -> Vec<PathBuf> {
    let mut removed = Vec::new();
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return removed,
    };

    let now = SystemTime::now();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().map_or(false, |e| e == "part") {
            if let Ok(meta) = path.metadata() {
                if let Ok(modified) = meta.modified() {
                    if let Ok(age) = now.duration_since(modified) {
                        if age > max_age {
                            if std::fs::remove_file(&path).is_ok() {
                                tracing::info!(
                                    path = %path.display(),
                                    age_h = age.as_secs() / 3600,
                                    "cleanup: removed stale .part file"
                                );
                                removed.push(path);
                            }
                        }
                    }
                }
            }
        }
    }
    removed
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn part_path_appends_suffix() {
        let p = part_path(Path::new("/tmp/installer.exe"));
        assert_eq!(p, PathBuf::from("/tmp/installer.exe.part"));
    }

    #[test]
    fn hex_encode_works() {
        assert_eq!(hex_encode(&[0xde, 0xad, 0xbe, 0xef]), "deadbeef");
        assert_eq!(hex_encode(&[]), "");
    }

    #[test]
    fn cleanup_removes_old_part_files() {
        let dir = std::env::temp_dir().join("aether_download_test_cleanup");
        let _ = fs::create_dir_all(&dir);

        let old_part = dir.join("old.exe.part");
        fs::write(&old_part, b"stale").unwrap();
        let removed = cleanup_stale_parts_with_age(&dir, Duration::from_secs(0));
        assert!(removed.contains(&old_part));
        assert!(!old_part.exists());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn cleanup_skips_non_part_files() {
        let dir = std::env::temp_dir().join("aether_download_test_skip");
        let _ = fs::create_dir_all(&dir);

        let keep = dir.join("keep.exe");
        fs::write(&keep, b"keep").unwrap();

        let removed = cleanup_stale_parts_with_age(&dir, Duration::from_secs(0));
        assert!(removed.is_empty());
        assert!(keep.exists());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn cleanup_handles_missing_dir() {
        let removed = cleanup_stale_parts(Path::new("/nonexistent/dir/aether_test_xxx"));
        assert!(removed.is_empty());
    }

    #[tokio::test]
    async fn rejects_http_url() {
        let tmp = std::env::temp_dir().join("aether_dl_test_http.exe");
        let err = download_verified(
            "http://example.com/x",
            &tmp,
            "deadbeef",
            1024,
            |_| {},
        )
        .await
        .unwrap_err();
        assert!(matches!(err, InstallerError::InsecureUrl(_)));
    }

    #[test]
    fn constants_are_sane() {
        assert!(CONNECT_TIMEOUT.as_secs() >= 10);
        assert!(CONNECT_TIMEOUT.as_secs() <= 120);
        assert!(TOTAL_TIMEOUT.as_secs() >= 300);
        assert!(TOTAL_TIMEOUT.as_secs() <= 1800);
        assert!(MAX_DOWNLOAD_SIZE <= 1024 * 1024 * 1024);
        assert!(MAX_RETRIES >= 2);
        assert!(MAX_RETRIES <= 10);
        assert!(STALL_TIMEOUT.as_secs() >= 10);
        assert!(STALE_PART_MAX_AGE.as_secs() == 24 * 3600);
    }
}
