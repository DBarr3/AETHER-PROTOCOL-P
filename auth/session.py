"""
AetherCloud-L — Session Manager
Quantum-seeded session token generator.
Aether Systems LLC — Patent Pending
"""

import os
import hashlib
import time
import threading
from typing import Optional

from config.settings import SESSION_TIMEOUT_SECONDS


class SessionManager:
    """
    Quantum-seeded session token generator.
    Uses os.urandom(32) for session entropy.
    Each session token is:
      - 64 character hex string
      - Bound to login timestamp via SHA-256
      - Stored in memory only (never to disk)
      - Invalidated on logout or timeout
    """

    def __init__(self, timeout_seconds: int = SESSION_TIMEOUT_SECONDS):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._timeout = timeout_seconds

    def generate_token(self, username: str, timestamp: str) -> str:
        """Generate a unique session token bound to username and timestamp."""
        entropy = os.urandom(32)
        payload = f"{username}:{timestamp}:{entropy.hex()}".encode()
        token = hashlib.sha256(payload).hexdigest()

        with self._lock:
            self._sessions[token] = {
                "username": username,
                "created_at": time.time(),
                "timestamp": timestamp,
            }
        return token

    def is_valid(self, token: str) -> bool:
        """Check if a session token is valid and not expired."""
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return False
            elapsed = time.time() - session["created_at"]
            if elapsed > self._timeout:
                del self._sessions[token]
                return False
            return True

    def invalidate(self, token: str) -> None:
        """Invalidate a session token (logout)."""
        with self._lock:
            self._sessions.pop(token, None)

    def refresh_token(self, old_token: str) -> Optional[str]:
        """
        Extend session by issuing a new token and invalidating the old one.
        Returns the new token, or None if the old token is invalid/expired.
        """
        with self._lock:
            session = self._sessions.get(old_token)
            if session is None:
                return None
            elapsed = time.time() - session["created_at"]
            if elapsed > self._timeout:
                del self._sessions[old_token]
                return None
            username = session["username"]
            # Invalidate old token
            del self._sessions[old_token]

        # Issue new token
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return self.generate_token(username, timestamp)

    def get_username(self, token: str) -> Optional[str]:
        """Get the username associated with a valid session token."""
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            elapsed = time.time() - session["created_at"]
            if elapsed > self._timeout:
                del self._sessions[token]
                return None
            return session["username"]

    @property
    def active_count(self) -> int:
        """Return the number of active sessions."""
        self._cleanup_expired()
        with self._lock:
            return len(self._sessions)

    def _cleanup_expired(self) -> None:
        """Remove expired sessions."""
        now = time.time()
        with self._lock:
            expired = [
                t for t, s in self._sessions.items()
                if now - s["created_at"] > self._timeout
            ]
            for t in expired:
                del self._sessions[t]
