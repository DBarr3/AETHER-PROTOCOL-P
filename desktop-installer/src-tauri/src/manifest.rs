use crate::errors::{InstallerError, Result};
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
        let m: Manifest = serde_json::from_slice(bytes)?;
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
}
