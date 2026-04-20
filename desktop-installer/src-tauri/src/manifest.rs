use crate::errors::{InstallerError, Result};
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub version: String,
    pub payload_url: String,
    pub payload_sha256: String,
    pub payload_size_bytes: u64,
    pub min_wizard_version: String,
    pub released_at: String,
}

impl Manifest {
    pub fn parse(bytes: &[u8]) -> Result<Manifest> {
        let mut m: Manifest = serde_json::from_slice(bytes)?;
        // Normalize so downstream hash comparison is case-insensitive regardless
        // of how the manifest serialized the digest.
        m.payload_sha256 = m.payload_sha256.to_ascii_lowercase();
        m.validate()?;
        Ok(m)
    }

    fn validate(&self) -> Result<()> {
        if !self.payload_url.starts_with("https://") {
            return Err(InstallerError::InsecureUrl(self.payload_url.clone()));
        }
        if self.payload_sha256.len() != 64 || !self.payload_sha256.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(InstallerError::ManifestParse(
                serde_json::Error::io(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "payload_sha256 must be 64 hex chars",
                )),
            ));
        }
        if self.payload_size_bytes == 0 {
            return Err(InstallerError::ManifestParse(
                serde_json::Error::io(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "payload_size_bytes must be > 0",
                )),
            ));
        }
        Ok(())
    }
}

/// Verify that `manifest_bytes` matches `signature_bytes` under `public_key_bytes`.
/// Verifies BEFORE parsing the JSON — never trust a manifest you haven't authenticated.
pub fn verify_signature(
    manifest_bytes: &[u8],
    signature_bytes: &[u8],
    public_key_bytes: &[u8; 32],
) -> Result<()> {
    let vk = VerifyingKey::from_bytes(public_key_bytes)
        .map_err(|_| InstallerError::Internal("embedded public key is invalid".into()))?;
    if signature_bytes.len() != 64 {
        return Err(InstallerError::SignatureMismatch);
    }
    let sig_arr: [u8; 64] = signature_bytes.try_into().expect("length checked above");
    let sig = Signature::from_bytes(&sig_arr);
    vk.verify(manifest_bytes, &sig).map_err(|_| InstallerError::SignatureMismatch)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const VALID_JSON: &str = r#"{
      "version": "0.9.7",
      "payload_url": "https://aethersystems.io/downloads/x.exe",
      "payload_sha256": "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b",
      "payload_size_bytes": 94371840,
      "min_wizard_version": "1.0.0",
      "released_at": "2026-04-18T23:00:00Z"
    }"#;

    #[test]
    fn parses_valid_manifest() {
        let m = Manifest::parse(VALID_JSON.as_bytes()).unwrap();
        assert_eq!(m.version, "0.9.7");
        assert_eq!(m.payload_size_bytes, 94371840);
    }

    #[test]
    fn rejects_http_url() {
        let bad = VALID_JSON.replace("https://", "http://");
        let err = Manifest::parse(bad.as_bytes()).unwrap_err();
        assert!(matches!(err, InstallerError::InsecureUrl(_)));
    }

    #[test]
    fn rejects_missing_field() {
        let bad = r#"{"version":"0.9.7"}"#;
        assert!(Manifest::parse(bad.as_bytes()).is_err());
    }

    #[test]
    fn rejects_unknown_field() {
        let bad = VALID_JSON.replace("\"version\"", "\"extra_field\": \"bad\", \"version\"");
        assert!(Manifest::parse(bad.as_bytes()).is_err());
    }

    #[test]
    fn normalizes_uppercase_sha256() {
        let upper = VALID_JSON.replace(
            "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b",
            "3A7BD3E2360A3D29EEA436FCFB7E44C735D117C42D1C1835420B6B9942DD4F1B",
        );
        let m = Manifest::parse(upper.as_bytes()).unwrap();
        assert_eq!(m.payload_sha256, "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b");
    }

    #[test]
    fn rejects_bad_sha256_length() {
        let bad = VALID_JSON.replace(
            "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b",
            "deadbeef",
        );
        assert!(Manifest::parse(bad.as_bytes()).is_err());
    }

    #[test]
    fn rejects_zero_size() {
        let bad = VALID_JSON.replace("94371840", "0");
        assert!(Manifest::parse(bad.as_bytes()).is_err());
    }

    const TEST_PUBKEY: &[u8] = include_bytes!("../keys/manifest-signing-test.pub.bin");
    const TEST_MANIFEST: &[u8] = include_bytes!("../tests/fixtures/test-signed-manifest.json");
    const TEST_SIG: &[u8] = include_bytes!("../tests/fixtures/test-signed-manifest.sig");

    fn pubkey_arr() -> [u8; 32] {
        let mut arr = [0u8; 32];
        arr.copy_from_slice(TEST_PUBKEY);
        arr
    }

    #[test]
    fn verifies_good_signature() {
        verify_signature(TEST_MANIFEST, TEST_SIG, &pubkey_arr()).unwrap();
    }

    #[test]
    fn rejects_tampered_manifest() {
        let mut tampered = TEST_MANIFEST.to_vec();
        tampered[20] ^= 0x01;
        assert!(matches!(
            verify_signature(&tampered, TEST_SIG, &pubkey_arr()),
            Err(InstallerError::SignatureMismatch)
        ));
    }

    #[test]
    fn rejects_wrong_signature_length() {
        let short = &TEST_SIG[..30];
        assert!(matches!(
            verify_signature(TEST_MANIFEST, short, &pubkey_arr()),
            Err(InstallerError::SignatureMismatch)
        ));
    }

    #[test]
    fn rejects_with_different_key() {
        let mut wrong_key = pubkey_arr();
        wrong_key[0] ^= 0xFF;
        // A mutated 32-byte value may or may not be a valid key. If valid, it's just a different key and verify fails.
        match verify_signature(TEST_MANIFEST, TEST_SIG, &wrong_key) {
            Err(InstallerError::SignatureMismatch) | Err(InstallerError::Internal(_)) => (),
            Ok(_) => panic!("expected verify to fail with wrong key"),
            Err(other) => panic!("unexpected error: {:?}", other),
        }
    }
}
