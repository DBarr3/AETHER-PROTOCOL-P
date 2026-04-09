"""
AetherCloud-L — Multi-Factor Authentication
Optional MFA layer for enhanced security.
Aether Systems LLC — Patent Pending
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import stat
import struct
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("aethercloud.mfa")


class MFAManager:
    """
    Optional MFA layer for AetherCloud-L.
    Implements TOTP (Time-based One-Time Password) compatible
    with standard authenticator apps.

    Secrets are persisted to disk (permissions 0o600) so MFA
    survives server restarts.  The file contains base64-encoded
    raw bytes for each enrolled username.
    """

    TOTP_INTERVAL = 30   # seconds per code window
    TOTP_DIGITS   = 6    # 6-digit TOTP codes (standard RFC 6238)

    def __init__(self, secrets_path: Optional[str] = None):
        from config.storage import CRYPTO_ROOT
        self._path = Path(secrets_path) if secrets_path else CRYPTO_ROOT / "mfa_secrets.json"
        self._secrets: dict[str, bytes] = self._load()

    # ── Persistence ───────────────────────────────────────
    def _load(self) -> dict[str, bytes]:
        """Load persisted MFA secrets from disk."""
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
            return {u: base64.b64decode(s) for u, s in raw.items()}
        except Exception as e:
            log.warning("Failed to load MFA secrets: %s", e)
            return {}

    def _save(self) -> None:
        """Persist MFA secrets to disk with restrictive permissions."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {u: base64.b64encode(s).decode() for u, s in self._secrets.items()}
            self._path.write_text(json.dumps(payload, indent=2))
            # chmod 600 — owner read/write only
            self._path.chmod(0o600)
        except Exception as e:
            log.error("Failed to persist MFA secrets: %s", e)

    # ── Enrollment ────────────────────────────────────────
    def enroll(self, username: str) -> str:
        """
        Generate a new TOTP secret for user enrollment.
        Returns the secret as a base32-encoded string for QR code generation.
        Persists secret to disk immediately.
        """
        secret = os.urandom(20)
        self._secrets[username] = secret
        self._save()
        return base64.b32encode(secret).decode()

    def unenroll(self, username: str) -> bool:
        """Remove MFA enrollment for a user and persist the change."""
        removed = self._secrets.pop(username, None) is not None
        if removed:
            self._save()
        return removed

    def is_enrolled(self, username: str) -> bool:
        """Check if a user has MFA enrolled."""
        return username in self._secrets

    # ── Verification ──────────────────────────────────────
    def verify_totp(self, username: str, code: str) -> bool:
        """
        Verify a TOTP code against the stored secret.
        Allows ±1 interval of clock drift (90-second window).
        """
        secret = self._secrets.get(username)
        if secret is None:
            return False

        now = int(time.time())
        for offset in [-1, 0, 1]:
            counter = (now // self.TOTP_INTERVAL) + offset
            expected = self._generate_totp(secret, counter)
            if hmac.compare_digest(code.strip(), expected):
                return True
        return False

    def _generate_totp(self, secret: bytes, counter: int) -> str:
        """Generate a TOTP code for the given counter value."""
        counter_bytes = struct.pack(">Q", counter)
        h = hmac.new(secret, counter_bytes, hashlib.sha1).digest()
        offset = h[-1] & 0x0F
        truncated = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
        code = truncated % (10 ** self.TOTP_DIGITS)
        return str(code).zfill(self.TOTP_DIGITS)
