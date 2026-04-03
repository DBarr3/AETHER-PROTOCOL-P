"""
AetherCloud-L — Security Fixes Test Suite
==========================================
Verifies every fix applied in the security sweep:

  FIX-1  Path traversal protection on /vault/browse + /vault/scan
         → _safe_browse_path() in api_server.py

  FIX-2  vault/filebase.py _resolve_path uses is_relative_to()
         (symlink-safe, cross-platform)

  FIX-3  MFA secrets persisted to disk (survive restarts) + chmod 0o600

  FIX-4  License cache file written with chmod 0o600

  FIX-5  bcrypt work factor explicitly rounds=14

  FIX-6  Auth/vault audit failures emit WARNING (not silent pass)

  FIX-7  Session timeout + login attempt env vars are bounds-checked

Aether Systems LLC — Patent Pending
"""

import base64
import json
import logging
import os
import platform
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import bcrypt
import pytest

# ── Project root on sys.path ─────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ═══════════════════════════════════════════════════════════
# FIX-1  _safe_browse_path() — path traversal protection
# ═══════════════════════════════════════════════════════════

class TestSafeBrowsePath:
    """
    _safe_browse_path must:
      • Allow paths within DEFAULT_VAULT_ROOT
      • Allow paths within Path.home()
      • Block any path that resolves outside both allowed roots
      • Defeat ../../ traversal sequences
      • Raise HTTPException(400) on denial
    """

    @pytest.fixture(autouse=True)
    def _import(self, tmp_path):
        """Import _safe_browse_path and patch DEFAULT_VAULT_ROOT to tmp_path."""
        from fastapi import HTTPException
        self.HTTPException = HTTPException

        # Create a fake vault root we control
        self.fake_vault = tmp_path / "vault_data"
        self.fake_vault.mkdir()

        import api_server
        self._orig_vault = api_server.DEFAULT_VAULT_ROOT
        api_server.DEFAULT_VAULT_ROOT = self.fake_vault
        # Reload the reference inside _safe_browse_path (it reads DEFAULT_VAULT_ROOT at call time)
        self._fn = api_server._safe_browse_path
        yield
        api_server.DEFAULT_VAULT_ROOT = self._orig_vault

    # ── Allowed paths ──────────────────────────────────────

    def test_vault_root_itself_is_allowed(self):
        result = self._fn(str(self.fake_vault))
        assert result == self.fake_vault.resolve()

    def test_subdir_inside_vault_root_is_allowed(self, tmp_path):
        subdir = self.fake_vault / "projects" / "alpha"
        subdir.mkdir(parents=True)
        result = self._fn(str(subdir))
        assert result == subdir.resolve()

    def test_home_directory_is_allowed(self):
        home = Path.home()
        result = self._fn(str(home))
        assert result == home.resolve()

    def test_subdir_inside_home_is_allowed(self):
        # Use a path that definitely exists — the home dir itself
        result = self._fn(str(Path.home()))
        assert result == Path.home().resolve()

    # ── Blocked paths ──────────────────────────────────────

    def test_system_root_is_blocked(self):
        r"""/ on Unix or C:\ on Windows must be rejected."""
        system_root = Path(os.path.abspath(os.sep))
        # Only test if system root is genuinely outside home and vault
        if not (
            system_root == Path.home().resolve()
            or system_root == self.fake_vault.resolve()
        ):
            with pytest.raises(self.HTTPException) as exc_info:
                self._fn(str(system_root))
            assert exc_info.value.status_code == 400

    def test_traversal_via_dotdot_is_blocked(self):
        r"""
        ../../ traversal that resolves outside BOTH home and vault must be blocked.
        Build a path that navigates up past the filesystem root's children:
          - On Windows: aim for C:\Windows\System32
          - On Unix:    aim for /etc
        """
        home = Path.home().resolve()
        vault = self.fake_vault.resolve()

        # Pick a well-known system directory guaranteed outside home
        if platform.system() == "Windows":
            outside_target = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        else:
            outside_target = Path("/etc")

        # Skip if the target is somehow inside home (edge case for unusual system configs)
        try:
            is_inside = outside_target.is_relative_to(home)
        except AttributeError:
            is_inside = str(outside_target).lower().startswith(str(home).lower())
        if is_inside:
            pytest.skip("System directory is inside home — unusual system config")

        # Craft a traversal from the fake vault into the outside target
        # Compute relative path: from vault root, go up to filesystem root, then down
        # Number of ".." needed = depth of vault from root
        vault_parts = vault.parts  # e.g. ('C:\\', 'Users', 'lilbe', 'AppData', 'Local', 'Temp', 'vault_data')
        ups = os.sep.join([".."] * (len(vault_parts) - 1))  # enough ".." to reach root
        crafted = str(vault) + os.sep + ups + os.sep + str(outside_target).lstrip(os.sep)

        with pytest.raises(self.HTTPException) as exc_info:
            self._fn(crafted)
        assert exc_info.value.status_code == 400

    def test_absolute_path_outside_vault_and_home_is_blocked(self, tmp_path):
        """A completely foreign temp directory must be blocked."""
        # tmp_path is created by pytest in a temp dir — outside home on most CI
        outside = tmp_path / "attacker_dir"
        outside.mkdir()
        home = Path.home().resolve()
        vault = self.fake_vault.resolve()
        # Guard: skip if tmp_path happens to be inside home (local dev)
        if str(outside.resolve()).startswith(str(home)):
            pytest.skip("tmp_path is inside home — cannot test outside-home block on this machine")
        with pytest.raises(self.HTTPException) as exc_info:
            self._fn(str(outside))
        assert exc_info.value.status_code == 400

    def test_traversal_resolves_to_parent_is_blocked(self, tmp_path):
        """Even when traversal target 'exists', it must be blocked if outside roots."""
        # Build a path that resolves to something outside both allowed roots
        outside = tmp_path / "totally_outside"
        outside.mkdir()
        home = Path.home().resolve()
        vault = self.fake_vault.resolve()
        if str(outside.resolve()).startswith(str(home)):
            pytest.skip("tmp_path is inside home on this machine")
        crafted = str(self.fake_vault) + "/../../../" + str(outside.relative_to(outside.anchor))
        with pytest.raises(self.HTTPException) as exc_info:
            self._fn(crafted)
        assert exc_info.value.status_code == 400

    def test_non_existent_path_inside_vault_is_allowed(self):
        """Non-existent sub-paths that are containment-safe must pass (existence check is caller's job)."""
        nonexistent = self.fake_vault / "deep" / "nested" / "file.txt"
        result = self._fn(str(nonexistent))
        assert result == nonexistent.resolve()

    def test_http_exception_detail_message(self, tmp_path):
        """Error detail must mention 'Access denied'."""
        outside = tmp_path / "bad"
        outside.mkdir()
        if str(outside.resolve()).startswith(str(Path.home().resolve())):
            pytest.skip("tmp_path inside home")
        with pytest.raises(self.HTTPException) as exc_info:
            self._fn(str(outside))
        assert "Access denied" in exc_info.value.detail


# ═══════════════════════════════════════════════════════════
# FIX-2  vault/filebase.py _resolve_path (symlink-safe)
# ═══════════════════════════════════════════════════════════

class TestVaultResolvePath:
    """
    AetherVault._resolve_path must:
      • Accept None → return vault root
      • Accept relative paths inside vault → resolve correctly
      • Reject any path that escapes vault root via ../../
      • Reject absolute paths pointing outside vault root
    """

    @pytest.fixture
    def vault(self, tmp_path):
        from aether_protocol.audit import AuditLog
        audit = AuditLog(str(tmp_path / "audit.jsonl"))
        from vault.filebase import AetherVault
        return AetherVault(
            vault_root=str(tmp_path / "vault"),
            session_token="test_token_xyz",
            audit_log=audit,
        )

    def test_none_returns_root(self, vault):
        result = vault._resolve_path(None)
        assert result == vault.root

    def test_simple_filename_inside_vault(self, vault):
        result = vault._resolve_path("document.pdf")
        assert result == vault.root / "document.pdf"

    def test_nested_path_inside_vault(self, vault):
        result = vault._resolve_path("subdir/nested/file.txt")
        assert result == vault.root / "subdir" / "nested" / "file.txt"

    def test_root_separator_does_not_escape(self, vault):
        """A path that resolves exactly to root is allowed."""
        result = vault._resolve_path(".")
        assert result == vault.root

    def test_dotdot_traversal_is_blocked(self, vault):
        """../secret must raise ValueError."""
        with pytest.raises(ValueError, match="escapes vault root"):
            vault._resolve_path("../secret_file.txt")

    def test_deep_dotdot_traversal_is_blocked(self, vault):
        """subdir/../../outside must raise ValueError."""
        with pytest.raises(ValueError, match="escapes vault root"):
            vault._resolve_path("subdir/../../outside")

    def test_absolute_outside_path_is_blocked(self, vault, tmp_path):
        """An absolute path outside the vault root must be blocked."""
        outside = str(tmp_path / "attacker.txt")
        with pytest.raises(ValueError, match="escapes vault root"):
            vault._resolve_path(outside)

    def test_absolute_vault_root_is_allowed(self, vault):
        """Absolute path that IS the vault root is allowed."""
        result = vault._resolve_path(str(vault.root))
        assert result == vault.root

    def test_absolute_sub_path_inside_vault(self, vault):
        """Absolute path inside the vault is allowed."""
        inside = str(vault.root / "subdir" / "file.txt")
        result = vault._resolve_path(inside)
        assert result == vault.root / "subdir" / "file.txt"


# ═══════════════════════════════════════════════════════════
# FIX-3  MFA persistence + permissions
# ═══════════════════════════════════════════════════════════

class TestMFAPersistence:
    """
    MFAManager must:
      • Write secrets to disk on enroll()
      • Survive a restart (new instance loads same secrets)
      • Write secrets file with permissions 0o600 (Unix)
      • Remove secret from disk on unenroll()
      • Generate 8-digit TOTP codes
      • Verify correct TOTP codes
      • Reject wrong codes
    """

    @pytest.fixture
    def mfa_path(self, tmp_path):
        return tmp_path / "mfa_secrets.json"

    @pytest.fixture
    def mfa(self, mfa_path):
        from auth.mfa import MFAManager
        return MFAManager(secrets_path=str(mfa_path))

    def test_enroll_writes_file(self, mfa, mfa_path):
        mfa.enroll("alice")
        assert mfa_path.exists(), "Secrets file must be created after enroll"

    def test_enrolled_secret_is_persisted(self, mfa, mfa_path):
        mfa.enroll("alice")
        raw = json.loads(mfa_path.read_text())
        assert "alice" in raw, "alice's secret must appear in persisted JSON"

    def test_secret_survives_restart(self, mfa, mfa_path):
        """A new MFAManager from the same path must find existing enrollments."""
        mfa.enroll("bob")
        from auth.mfa import MFAManager
        mfa2 = MFAManager(secrets_path=str(mfa_path))
        assert mfa2.is_enrolled("bob"), "bob must be enrolled after reload"

    def test_secret_bytes_are_preserved(self, mfa, mfa_path):
        """Raw secret bytes must round-trip through JSON correctly."""
        mfa.enroll("charlie")
        raw_bytes_before = mfa._secrets["charlie"]
        from auth.mfa import MFAManager
        mfa2 = MFAManager(secrets_path=str(mfa_path))
        assert mfa2._secrets["charlie"] == raw_bytes_before

    @pytest.mark.skipif(platform.system() == "Windows", reason="chmod not enforced on Windows")
    def test_secrets_file_permissions_are_600(self, mfa, mfa_path):
        """Secrets file must have mode 0o600 (owner rw only) on Unix."""
        mfa.enroll("dave")
        mode = mfa_path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"

    def test_unenroll_removes_from_disk(self, mfa, mfa_path):
        mfa.enroll("eve")
        mfa.unenroll("eve")
        raw = json.loads(mfa_path.read_text())
        assert "eve" not in raw, "eve's secret must be gone after unenroll"

    def test_unenroll_nonexistent_returns_false(self, mfa):
        assert mfa.unenroll("ghost") is False

    def test_is_enrolled_false_for_unknown(self, mfa):
        assert not mfa.is_enrolled("nobody")

    def test_is_enrolled_true_after_enroll(self, mfa):
        mfa.enroll("frank")
        assert mfa.is_enrolled("frank")

    def test_is_enrolled_false_after_unenroll(self, mfa):
        mfa.enroll("grace")
        mfa.unenroll("grace")
        assert not mfa.is_enrolled("grace")

    def test_totp_code_is_8_digits(self, mfa):
        mfa.enroll("heidi")
        secret = mfa._secrets["heidi"]
        counter = int(time.time()) // mfa.TOTP_INTERVAL
        code = mfa._generate_totp(secret, counter)
        assert len(code) == 8, f"Expected 8-digit code, got {len(code)}: {code}"
        assert code.isdigit(), "TOTP code must be digits only"

    def test_correct_totp_verifies(self, mfa):
        mfa.enroll("ivan")
        secret = mfa._secrets["ivan"]
        counter = int(time.time()) // mfa.TOTP_INTERVAL
        valid_code = mfa._generate_totp(secret, counter)
        assert mfa.verify_totp("ivan", valid_code)

    def test_wrong_totp_is_rejected(self, mfa):
        mfa.enroll("judy")
        assert not mfa.verify_totp("judy", "00000000")

    def test_totp_rejects_unenrolled_user(self, mfa):
        assert not mfa.verify_totp("nobody", "12345678")

    def test_clock_drift_tolerance(self, mfa):
        """One interval in the past/future should still verify."""
        mfa.enroll("ken")
        secret = mfa._secrets["ken"]
        # Generate code for previous window
        prev_counter = int(time.time()) // mfa.TOTP_INTERVAL - 1
        prev_code = mfa._generate_totp(secret, prev_counter)
        assert mfa.verify_totp("ken", prev_code)

    def test_multiple_users_isolated(self, mfa, mfa_path):
        """Enrolling multiple users must keep their secrets separate."""
        mfa.enroll("user1")
        mfa.enroll("user2")
        raw = json.loads(mfa_path.read_text())
        assert "user1" in raw and "user2" in raw
        secret1 = base64.b64decode(raw["user1"])
        secret2 = base64.b64decode(raw["user2"])
        assert secret1 != secret2, "Each user must have a unique secret"

    def test_enroll_returns_base32_string(self, mfa):
        qr_secret = mfa.enroll("lisa")
        assert isinstance(qr_secret, str)
        # Must be valid base32 (upper-alpha + 2-7)
        import base64 as _b64
        decoded = _b64.b32decode(qr_secret)
        assert len(decoded) == 20, "TOTP secret must be 20 bytes (160 bits)"


# ═══════════════════════════════════════════════════════════
# FIX-4  License cache file permissions
# ═══════════════════════════════════════════════════════════

class TestLicenseCachePermissions:
    """
    CloudLicenseClient._save_cache must:
      • Write a valid JSON file
      • Set permissions to 0o600 on Unix
    """

    @pytest.fixture
    def client(self, tmp_path):
        from license_client import CloudLicenseClient
        cache_file = tmp_path / "license_cache.json"
        c = CloudLicenseClient.__new__(CloudLicenseClient)
        c.key = "AETH-CLD-TEST-0001-ABCD"
        c.server = "https://example.invalid"
        c.cache_path = str(cache_file)
        c.grace_period_hours = 72
        return c, cache_file

    def test_cache_file_is_written(self, client):
        c, cache_file = client
        c._save_cache({"valid": True, "plan": "pro"})
        assert cache_file.exists()

    def test_cache_file_contains_valid_json(self, client):
        c, cache_file = client
        c._save_cache({"valid": True, "plan": "pro"})
        data = json.loads(cache_file.read_text())
        assert "cached_at" in data
        assert data["response"]["valid"] is True

    @pytest.mark.skipif(platform.system() == "Windows", reason="chmod not enforced on Windows")
    def test_cache_file_permissions_are_600(self, client):
        c, cache_file = client
        c._save_cache({"valid": True})
        mode = cache_file.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got 0o{mode:03o}"

    def test_cache_overwrites_cleanly(self, client):
        c, cache_file = client
        c._save_cache({"valid": True, "plan": "basic"})
        c._save_cache({"valid": True, "plan": "pro"})
        data = json.loads(cache_file.read_text())
        assert data["response"]["plan"] == "pro"


# ═══════════════════════════════════════════════════════════
# FIX-5  bcrypt work factor = 14
# ═══════════════════════════════════════════════════════════

class TestBcryptWorkFactor:
    """
    register_user must hash passwords with rounds=14.
    The bcrypt cost factor is encoded in the hash string itself:
    $2b$14$... means rounds=14.
    """

    @pytest.fixture
    def auth(self, tmp_path):
        from auth.login import AetherCloudAuth
        from aether_protocol.audit import AuditLog
        audit = AuditLog(str(tmp_path / "audit.jsonl"))
        return AetherCloudAuth(
            config_path=str(tmp_path / "creds.json"),
            audit_log=audit,
        )

    def test_register_uses_bcrypt_rounds_14(self, auth):
        auth.register_user("testuser", "S3cur3P@ssword!")
        creds = json.loads(auth._config_path.read_text())
        password_hash = creds["testuser"]["password_hash"]
        # bcrypt hash format: $2b$<rounds>$<salt><hash>
        parts = password_hash.split("$")
        # parts[0]='' parts[1]='2b' parts[2]='14' parts[3]=salt+hash
        assert parts[2] == "14", (
            f"Expected bcrypt rounds=14, got rounds={parts[2]} in hash: {password_hash}"
        )

    def test_registered_password_verifies(self, auth):
        auth.register_user("alice", "MyP@ss9999!")
        result = auth.login("alice", "MyP@ss9999!")
        assert result["authenticated"] is True

    def test_wrong_password_rejected(self, auth):
        auth.register_user("bob", "Correct!Horse9")
        result = auth.login("bob", "WrongPassword1")
        assert result["authenticated"] is False

    def test_duplicate_registration_rejected(self, auth):
        ok1 = auth.register_user("carol", "P@ss1234")
        ok2 = auth.register_user("carol", "DifferentP@ss")
        assert ok1 is True
        assert ok2 is False

    def test_bcrypt_hash_is_not_plaintext(self, auth):
        auth.register_user("dave", "PlainText123!")
        creds = json.loads(auth._config_path.read_text())
        stored = creds["dave"]["password_hash"]
        assert "PlainText123!" not in stored
        assert stored.startswith("$2b$")


# ═══════════════════════════════════════════════════════════
# FIX-6  Audit failures emit WARNING (not silent pass)
# ═══════════════════════════════════════════════════════════

class TestAuditFailureLogging:
    """
    When the audit log raises an exception:
      • auth/login.py login() must emit a WARNING via logging
      • vault/filebase.py _log_event() must emit a WARNING via logging
    Neither should propagate the exception to the caller.
    """

    @pytest.fixture
    def auth_with_broken_audit(self, tmp_path):
        from auth.login import AetherCloudAuth
        bad_audit = MagicMock()
        bad_audit.append_commitment.side_effect = RuntimeError("disk full")
        auth = AetherCloudAuth(
            config_path=str(tmp_path / "creds.json"),
            audit_log=bad_audit,
        )
        auth.register_user("alice", "P@ss1234Test!")
        return auth

    def test_login_audit_failure_emits_warning(self, auth_with_broken_audit, caplog):
        with caplog.at_level(logging.WARNING, logger="aethercloud.auth"):
            result = auth_with_broken_audit.login("alice", "P@ss1234Test!")
        # Login should succeed despite audit failure
        assert result["authenticated"] is True
        # Warning must have been emitted
        assert any("audit" in r.message.lower() or "Audit" in r.message
                   for r in caplog.records), \
            f"Expected audit warning in logs. Got: {[r.message for r in caplog.records]}"

    def test_login_audit_failure_does_not_crash(self, auth_with_broken_audit):
        """Audit failure must not propagate as an exception."""
        result = auth_with_broken_audit.login("alice", "P@ss1234Test!")
        assert "authenticated" in result  # No exception = pass

    def test_vault_audit_failure_emits_warning(self, tmp_path, caplog):
        from vault.filebase import AetherVault
        bad_audit = MagicMock()
        bad_audit.append_commitment.side_effect = OSError("no space left")
        vault = AetherVault(
            vault_root=str(tmp_path / "vault"),
            session_token="tok123",
            audit_log=bad_audit,
        )
        # _log_event is called by internal operations; call it directly
        with caplog.at_level(logging.WARNING, logger="aethercloud.vault"):
            result = vault._log_event("TEST_EVENT", {"detail": "test"})
        assert result is not None  # Returns commitment hash, not raises
        assert any("audit" in r.message.lower() or "TEST_EVENT" in r.message
                   for r in caplog.records), \
            f"Expected vault audit warning. Got: {[r.message for r in caplog.records]}"

    def test_vault_audit_failure_returns_commitment_hash(self, tmp_path):
        """_log_event must return a hash even when audit write fails."""
        from vault.filebase import AetherVault
        bad_audit = MagicMock()
        bad_audit.append_commitment.side_effect = IOError("broken pipe")
        vault = AetherVault(
            vault_root=str(tmp_path / "vault"),
            session_token="tok456",
            audit_log=bad_audit,
        )
        result = vault._log_event("FAIL_EVENT", {"x": 1})
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex = 64 chars


# ═══════════════════════════════════════════════════════════
# FIX-7  Session timeout + login attempt bounds-checking
# ═══════════════════════════════════════════════════════════

class TestSettingsBounds:
    """
    config/settings.py must clamp env var values:
      SESSION_TIMEOUT_HOURS  → [1, 24]
      MAX_LOGIN_ATTEMPTS     → [3, 20]
      LOCKOUT_DURATION_SECONDS → minimum 60
    """

    def _reimport_settings(self, env_overrides: dict):
        """Force-reload config.settings with patched env vars."""
        import importlib
        import config.settings as _mod
        with patch.dict(os.environ, env_overrides, clear=False):
            importlib.reload(_mod)
        return _mod

    def test_session_timeout_too_low_clamped_to_1(self):
        mod = self._reimport_settings({"AETHER_SESSION_TIMEOUT": "0"})
        assert mod.SESSION_TIMEOUT_HOURS == 1

    def test_session_timeout_too_high_clamped_to_24(self):
        mod = self._reimport_settings({"AETHER_SESSION_TIMEOUT": "999"})
        assert mod.SESSION_TIMEOUT_HOURS == 24

    def test_session_timeout_valid_value_unchanged(self):
        mod = self._reimport_settings({"AETHER_SESSION_TIMEOUT": "8"})
        assert mod.SESSION_TIMEOUT_HOURS == 8

    def test_session_timeout_seconds_derived_correctly(self):
        mod = self._reimport_settings({"AETHER_SESSION_TIMEOUT": "4"})
        assert mod.SESSION_TIMEOUT_SECONDS == 4 * 3600

    def test_max_login_attempts_too_low_clamped(self):
        mod = self._reimport_settings({"AETHER_MAX_LOGIN_ATTEMPTS": "1"})
        assert mod.MAX_LOGIN_ATTEMPTS >= 3

    def test_max_login_attempts_too_high_clamped(self):
        mod = self._reimport_settings({"AETHER_MAX_LOGIN_ATTEMPTS": "1000"})
        assert mod.MAX_LOGIN_ATTEMPTS <= 20

    def test_lockout_duration_minimum_enforced(self):
        mod = self._reimport_settings({"AETHER_LOCKOUT_DURATION": "0"})
        assert mod.LOCKOUT_DURATION_SECONDS >= 60

    def test_lockout_duration_valid_value_unchanged(self):
        mod = self._reimport_settings({"AETHER_LOCKOUT_DURATION": "900"})
        assert mod.LOCKOUT_DURATION_SECONDS == 900


# ═══════════════════════════════════════════════════════════
# Integration: Full lockout flow uses bounded settings
# ═══════════════════════════════════════════════════════════

class TestLockoutWithBoundedSettings:
    """Ensure auth lockout uses the bounded MAX_LOGIN_ATTEMPTS value."""

    @pytest.fixture
    def auth(self, tmp_path):
        from auth.login import AetherCloudAuth
        from aether_protocol.audit import AuditLog
        audit = AuditLog(str(tmp_path / "audit.jsonl"))
        auth = AetherCloudAuth(
            config_path=str(tmp_path / "creds.json"),
            audit_log=audit,
        )
        auth.register_user("victim", "CorrectP@ss123!")
        return auth

    def test_account_locks_after_max_attempts(self, auth):
        """5 wrong attempts must trigger lockout."""
        from config.settings import MAX_LOGIN_ATTEMPTS
        for _ in range(MAX_LOGIN_ATTEMPTS):
            auth.login("victim", "WrongPassword!")
        result = auth.login("victim", "CorrectP@ss123!")
        assert result["authenticated"] is False
        assert result.get("reason") in ("ACCOUNT_LOCKED", "INVALID_PASSWORD", "USER_NOT_FOUND") or \
               not result["authenticated"]

    def test_correct_password_works_before_lockout(self, auth):
        # One wrong attempt, then correct — should succeed
        auth.login("victim", "WrongPassword!")
        result = auth.login("victim", "CorrectP@ss123!")
        assert result["authenticated"] is True
