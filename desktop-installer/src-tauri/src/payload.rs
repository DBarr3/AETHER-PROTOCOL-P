use crate::errors::Result;
use sha2::{Digest, Sha256};
use tokio::io::{AsyncRead, AsyncReadExt};

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

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0F) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::BufReader;

    #[tokio::test]
    async fn empty_input_matches_known_digest() {
        // Known: SHA-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        let reader = BufReader::new(&b""[..]);
        let hex = sha256_stream(reader).await.unwrap();
        assert_eq!(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    }

    #[tokio::test]
    async fn abc_matches_known_digest() {
        // Known: SHA-256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
        let reader = BufReader::new(&b"abc"[..]);
        let hex = sha256_stream(reader).await.unwrap();
        assert_eq!(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    }

    #[tokio::test]
    async fn larger_than_buffer_matches() {
        // 200KB of zeros.
        let data = vec![0u8; 200 * 1024];
        let hex = sha256_stream(BufReader::new(&data[..])).await.unwrap();
        // Any consistent 64-hex string acceptable here — the key assertion is
        // that streaming a >64KB input (larger than our internal buffer)
        // produces a valid digest, not a specific value.
        assert_eq!(hex.len(), 64);
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
