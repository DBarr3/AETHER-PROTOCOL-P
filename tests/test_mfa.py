"""
AetherCloud-L — MFA Tests
Tests for multi-factor authentication.
"""

import pytest
from auth.mfa import MFAManager


class TestMFAManager:
    """Tests for MFAManager TOTP implementation."""

    @pytest.fixture
    def mfa(self, tmp_path):
        """Isolated MFAManager — uses tmp_path so tests never share disk state."""
        return MFAManager(secrets_path=str(tmp_path / "mfa_secrets.json"))

    def test_mfa_creation(self, mfa):
        assert mfa is not None

    def test_enroll(self, mfa):
        secret = mfa.enroll("testuser")
        assert isinstance(secret, str)
        assert len(secret) > 0

    def test_is_enrolled(self, mfa):
        assert not mfa.is_enrolled("testuser")
        mfa.enroll("testuser")
        assert mfa.is_enrolled("testuser")

    def test_verify_totp_valid(self, mfa):
        mfa.enroll("testuser")
        # Generate a valid code using the internal method
        import time, struct
        secret = mfa._secrets["testuser"]
        counter = int(time.time()) // 30
        code = mfa._generate_totp(secret, counter)
        assert mfa.verify_totp("testuser", code)

    def test_verify_totp_invalid(self, mfa):
        mfa.enroll("testuser")
        assert not mfa.verify_totp("testuser", "000000")

    def test_verify_totp_unenrolled(self, mfa):
        assert not mfa.verify_totp("nobody", "123456")

    def test_unenroll(self, mfa):
        mfa.enroll("testuser")
        assert mfa.unenroll("testuser")
        assert not mfa.is_enrolled("testuser")

    def test_unenroll_not_enrolled(self, mfa):
        assert not mfa.unenroll("nobody")

    def test_totp_code_length(self, mfa):
        mfa.enroll("testuser")
        import time
        secret = mfa._secrets["testuser"]
        counter = int(time.time()) // 30
        code = mfa._generate_totp(secret, counter)
        assert len(code) == 6

    def test_totp_code_is_numeric(self, mfa):
        mfa.enroll("testuser")
        import time
        secret = mfa._secrets["testuser"]
        counter = int(time.time()) // 30
        code = mfa._generate_totp(secret, counter)
        assert code.isdigit()

    def test_different_users_different_secrets(self, mfa):
        s1 = mfa.enroll("user1")
        s2 = mfa.enroll("user2")
        assert s1 != s2
