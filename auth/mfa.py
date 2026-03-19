"""
AetherCloud-L — Multi-Factor Authentication (Scaffold)
Optional MFA layer for enhanced security.
Aether Systems LLC — Patent Pending
"""

import hashlib
import hmac
import os
import struct
import time
from typing import Optional


class MFAManager:
    """
    Optional MFA layer for AetherCloud-L.
    Implements TOTP (Time-based One-Time Password) compatible
    with standard authenticator apps.

    Phase 1: TOTP scaffold
    Phase 2: Hardware key support (YubiKey)
    """

    TOTP_INTERVAL = 30  # seconds
    TOTP_DIGITS = 6

    def __init__(self):
        self._secrets: dict[str, bytes] = {}

    def enroll(self, username: str) -> str:
        """
        Generate a new TOTP secret for user enrollment.
        Returns the secret as a base32-encoded string for QR code generation.
        """
        import base64
        secret = os.urandom(20)
        self._secrets[username] = secret
        return base64.b32encode(secret).decode()

    def verify_totp(self, username: str, code: str) -> bool:
        """
        Verify a TOTP code against the stored secret.
        Allows 1 interval of clock drift.
        """
        secret = self._secrets.get(username)
        if secret is None:
            return False

        now = int(time.time())
        for offset in [-1, 0, 1]:
            counter = (now // self.TOTP_INTERVAL) + offset
            expected = self._generate_totp(secret, counter)
            if hmac.compare_digest(code, expected):
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

    def is_enrolled(self, username: str) -> bool:
        """Check if a user has MFA enrolled."""
        return username in self._secrets

    def unenroll(self, username: str) -> bool:
        """Remove MFA enrollment for a user."""
        return self._secrets.pop(username, None) is not None
