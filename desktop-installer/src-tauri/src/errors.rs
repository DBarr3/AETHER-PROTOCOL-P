use thiserror::Error;

#[derive(Debug, Error)]
pub enum InstallerError {
    #[error("Cannot reach AetherCloud. Check your internet connection and try again.")]
    Network(#[from] reqwest::Error),

    #[error("Install service is temporarily unavailable. Please try again in a few minutes.")]
    ManifestHttpStatus(u16),

    #[error("Install data is invalid. Please reinstall from aethersystems.io/download.")]
    ManifestParse(#[from] serde_json::Error),

    #[error("Install verification failed. Do not proceed — download was tampered with. Please reinstall from aethersystems.io/download.")]
    SignatureMismatch,

    #[error("Install verification failed. Do not proceed — download was corrupted or tampered. Please retry.")]
    PayloadHashMismatch { expected: String, got: String },

    #[error("Installation was not completed. Error code: {code}. Please contact support@aethersystems.io.")]
    PayloadExit { code: i32 },

    #[error("Please download the latest AetherCloud installer from aethersystems.io/download.")]
    MinWizardVersion { required: String, current: String },

    #[error("Download was larger than declared — aborted.")]
    PayloadSizeExceeded,

    #[error("Insecure URL rejected (must be HTTPS): {0}")]
    InsecureUrl(String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Consent was not granted — install refused.")]
    NoConsent,

    #[error("Install was cancelled by user.")]
    Cancelled,

    #[error("Internal error: {0}")]
    Internal(String),
}

impl InstallerError {
    /// User-facing one-line message (same as Display).
    pub fn user_message(&self) -> String { self.to_string() }

    /// Short state label for progress events.
    pub fn state_label(&self) -> &'static str {
        match self {
            InstallerError::Network(_) => "Offline",
            InstallerError::ManifestHttpStatus(_) => "Service unavailable",
            InstallerError::ManifestParse(_) => "Bad manifest",
            InstallerError::SignatureMismatch => "Signature failed",
            InstallerError::PayloadHashMismatch { .. } => "Hash failed",
            InstallerError::PayloadExit { .. } => "Install failed",
            InstallerError::MinWizardVersion { .. } => "Update wizard",
            InstallerError::PayloadSizeExceeded => "Oversize download",
            InstallerError::InsecureUrl(_) => "Bad URL",
            InstallerError::Io(_) => "Disk error",
            InstallerError::NoConsent => "Consent needed",
            InstallerError::Cancelled => "Cancelled",
            InstallerError::Internal(_) => "Internal error",
        }
    }
}

pub type Result<T> = std::result::Result<T, InstallerError>;
