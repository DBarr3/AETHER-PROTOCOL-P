"""
AetherCloud-L — Secure Login Gate
Every login attempt is logged via Protocol-L commitment layer.
Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import logging
import time
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("aethercloud.auth")

import bcrypt

from aether_protocol.audit import AuditLog
from aether_protocol.quantum_crypto import get_quantum_seed, QuantumSeedCommitment
from auth.session import SessionManager
from config.settings import (
    CREDENTIALS_FILE,
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_DURATION_SECONDS,
    DEFAULT_AUDIT_DIR,
)


class AetherCloudAuth:
    """
    Secure login gate for AetherCloud-L.
    Every login attempt is logged via Protocol-L
    commitment layer — success and failure both.
    A failed login produces a signed audit entry
    just like a successful one.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        audit_log: Optional[AuditLog] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        self._config_path = Path(config_path) if config_path else CREDENTIALS_FILE
        self._credentials = self._load_credentials()
        self._session_manager = session_manager or SessionManager()
        self._failed_attempts: dict[str, list[float]] = {}

        audit_dir = DEFAULT_AUDIT_DIR
        audit_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log = audit_log or AuditLog(
            str(audit_dir / "aethercloud_audit.jsonl")
        )

    def _load_credentials(self) -> dict:
        """Load hashed credentials from config file."""
        if self._config_path.exists():
            with open(self._config_path, "r") as f:
                return json.load(f)
        return {}

    def register_user(self, username: str, password: str) -> bool:
        """Register a new user with bcrypt-hashed password."""
        if username in self._credentials:
            return False
        salt = bcrypt.gensalt(rounds=14)  # Explicit work factor (higher than default 12)
        hashed = bcrypt.hashpw(password.encode(), salt).decode()
        self._credentials[username] = {"password_hash": hashed}
        self._save_credentials()
        # Create per-user directory structure
        try:
            from config.storage import ensure_user_dirs
            ensure_user_dirs(username)
        except Exception:
            pass  # Directory creation failure should not block registration
        return True

    def _save_credentials(self) -> None:
        """Save credentials to config file."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump(self._credentials, f, indent=2)

    def _is_locked_out(self, username: str) -> bool:
        """Check if user is locked out due to failed attempts."""
        attempts = self._failed_attempts.get(username, [])
        now = time.time()
        # Keep only recent attempts
        recent = [t for t in attempts if now - t < LOCKOUT_DURATION_SECONDS]
        self._failed_attempts[username] = recent
        return len(recent) >= MAX_LOGIN_ATTEMPTS

    def _record_failed_attempt(self, username: str) -> None:
        """Record a failed login attempt."""
        if username not in self._failed_attempts:
            self._failed_attempts[username] = []
        self._failed_attempts[username].append(time.time())

    def login(
        self,
        username: str,
        password: str,
        source_ip: str = "local",
    ) -> dict:
        """
        Authenticate user.
        Returns session token on success.
        Logs attempt via Protocol-L regardless of outcome.
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        audit_id = hashlib.sha256(
            f"{username}:{timestamp}:{os.urandom(8).hex()}".encode()
        ).hexdigest()[:16]

        # Check lockout
        if self._is_locked_out(username):
            return self._log_and_return(
                authenticated=False,
                username=username,
                source_ip=source_ip,
                timestamp=timestamp,
                audit_id=audit_id,
                reason="ACCOUNT_LOCKED",
            )

        # Verify credentials
        user_record = self._credentials.get(username)
        if user_record is None:
            self._record_failed_attempt(username)
            return self._log_and_return(
                authenticated=False,
                username=username,
                source_ip=source_ip,
                timestamp=timestamp,
                audit_id=audit_id,
                reason="USER_NOT_FOUND",
            )

        stored_hash = user_record["password_hash"].encode()
        if not bcrypt.checkpw(password.encode(), stored_hash):
            self._record_failed_attempt(username)
            return self._log_and_return(
                authenticated=False,
                username=username,
                source_ip=source_ip,
                timestamp=timestamp,
                audit_id=audit_id,
                reason="INVALID_PASSWORD",
            )

        # Success — generate session token
        session_token = self._session_manager.generate_token(username, timestamp)

        return self._log_and_return(
            authenticated=True,
            username=username,
            source_ip=source_ip,
            timestamp=timestamp,
            audit_id=audit_id,
            reason="LOGIN_SUCCESS",
            session_token=session_token,
        )

    def _log_and_return(
        self,
        authenticated: bool,
        username: str,
        source_ip: str,
        timestamp: str,
        audit_id: str,
        reason: str,
        session_token: Optional[str] = None,
    ) -> dict:
        """Log the auth event via Protocol-L and return result."""
        event_data = {
            "event_type": "AUTH_LOGIN",
            "authenticated": authenticated,
            "username": username,
            "source_ip": source_ip,
            "reason": reason,
            "timestamp": timestamp,
            "audit_id": audit_id,
        }

        # Create Protocol-L commitment for this auth event
        seed = os.urandom(32)
        seed_hash_val = hashlib.sha256(seed).hexdigest()
        now = int(time.time())
        commitment_hash = hashlib.sha256(
            json.dumps(event_data, sort_keys=True).encode()
        ).hexdigest()

        seed_commitment = QuantumSeedCommitment(
            seed_hash_val, now, "OS_URANDOM", now, now + 3600
        )

        audit_entry = {
            "order_id": f"auth_{audit_id}",
            "trade_details": event_data,
            "quantum_seed_commitment": seed_commitment.seed_hash,
            "seed_measurement_method": "OS_URANDOM",
            "timestamp": time.time(),
        }
        signature = {"commitment_hash": commitment_hash}

        try:
            self._audit_log.append_commitment(audit_entry, signature)
        except Exception as _audit_err:
            log.warning(
                "Auth audit log write failed — event=%s audit_id=%s: %s",
                reason, audit_id, _audit_err,
            )

        return {
            "authenticated": authenticated,
            "session_token": session_token,
            "commitment_hash": commitment_hash,
            "timestamp": timestamp,
            "audit_id": audit_id,
        }

    def logout(self, session_token: str) -> dict:
        """Terminate session. Log logout event via Protocol-L."""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        username = self._session_manager.get_username(session_token)

        self._session_manager.invalidate(session_token)

        event_data = {
            "event_type": "AUTH_LOGOUT",
            "username": username or "unknown",
            "timestamp": timestamp,
        }

        commitment_hash = hashlib.sha256(
            json.dumps(event_data, sort_keys=True).encode()
        ).hexdigest()

        seed = os.urandom(32)
        seed_hash_val = hashlib.sha256(seed).hexdigest()
        now = int(time.time())
        seed_commitment = QuantumSeedCommitment(
            seed_hash_val, now, "OS_URANDOM", now, now + 3600
        )

        audit_entry = {
            "order_id": f"logout_{hashlib.sha256(timestamp.encode()).hexdigest()[:16]}",
            "trade_details": event_data,
            "quantum_seed_commitment": seed_commitment.seed_hash,
            "seed_measurement_method": "OS_URANDOM",
            "timestamp": time.time(),
        }
        signature = {"commitment_hash": commitment_hash}

        try:
            self._audit_log.append_commitment(audit_entry, signature)
        except Exception as _ae:
            log.warning("Logout audit log write failed for %s: %s", username or "unknown", _ae)

        return {
            "logged_out": True,
            "commitment_hash": commitment_hash,
            "timestamp": timestamp,
        }

    def verify_session(self, token: str) -> bool:
        """Verify a session token is valid and not expired."""
        return self._session_manager.is_valid(token)
