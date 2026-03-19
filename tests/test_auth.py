"""
AetherCloud-L — Auth Tests
Tests for login, session management, and logout.
"""

import time
import pytest


class TestSessionManager:
    """Tests for SessionManager."""

    def test_generate_token_returns_64_hex(self, session_manager):
        token = session_manager.generate_token("user", "2026-03-19T00:00:00Z")
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_generate_unique_tokens(self, session_manager):
        t1 = session_manager.generate_token("user", "2026-03-19T00:00:00Z")
        t2 = session_manager.generate_token("user", "2026-03-19T00:00:00Z")
        assert t1 != t2

    def test_token_is_valid(self, session_manager):
        token = session_manager.generate_token("user", "2026-03-19T00:00:00Z")
        assert session_manager.is_valid(token)

    def test_invalid_token_rejected(self, session_manager):
        assert not session_manager.is_valid("nonexistent_token")

    def test_invalidate_token(self, session_manager):
        token = session_manager.generate_token("user", "2026-03-19T00:00:00Z")
        session_manager.invalidate(token)
        assert not session_manager.is_valid(token)

    def test_get_username(self, session_manager):
        token = session_manager.generate_token("alice", "2026-03-19T00:00:00Z")
        assert session_manager.get_username(token) == "alice"

    def test_get_username_invalid_token(self, session_manager):
        assert session_manager.get_username("bad_token") is None

    def test_active_count(self, session_manager):
        session_manager.generate_token("user1", "t1")
        session_manager.generate_token("user2", "t2")
        assert session_manager.active_count == 2

    def test_expired_token_rejected(self):
        from auth.session import SessionManager
        sm = SessionManager(timeout_seconds=0)
        token = sm.generate_token("user", "ts")
        time.sleep(0.1)
        assert not sm.is_valid(token)

    def test_invalidate_nonexistent_no_error(self, session_manager):
        session_manager.invalidate("does_not_exist")  # Should not raise


class TestAetherCloudAuth:
    """Tests for AetherCloudAuth login/logout."""

    def test_register_user(self, auth_instance):
        assert auth_instance.register_user("newuser", "password123")

    def test_register_duplicate_user(self, registered_auth):
        assert not registered_auth.register_user("testuser", "other")

    def test_login_success(self, registered_auth):
        result = registered_auth.login("testuser", "SecureP@ss123")
        assert result["authenticated"] is True
        assert result["session_token"] is not None
        assert result["commitment_hash"]
        assert result["audit_id"]

    def test_login_wrong_password(self, registered_auth):
        result = registered_auth.login("testuser", "wrong")
        assert result["authenticated"] is False
        assert result["session_token"] is None

    def test_login_unknown_user(self, registered_auth):
        result = registered_auth.login("nobody", "pass")
        assert result["authenticated"] is False

    def test_login_produces_commitment_hash(self, registered_auth):
        result = registered_auth.login("testuser", "SecureP@ss123")
        assert len(result["commitment_hash"]) == 64

    def test_login_produces_timestamp(self, registered_auth):
        result = registered_auth.login("testuser", "SecureP@ss123")
        assert "T" in result["timestamp"]

    def test_failed_login_still_has_audit_id(self, registered_auth):
        result = registered_auth.login("testuser", "wrong")
        assert result["audit_id"]

    def test_verify_session_after_login(self, registered_auth):
        result = registered_auth.login("testuser", "SecureP@ss123")
        assert registered_auth.verify_session(result["session_token"])

    def test_verify_invalid_session(self, registered_auth):
        assert not registered_auth.verify_session("fake_token")

    def test_logout(self, registered_auth):
        login_result = registered_auth.login("testuser", "SecureP@ss123")
        logout_result = registered_auth.logout(login_result["session_token"])
        assert logout_result["logged_out"] is True
        assert logout_result["commitment_hash"]

    def test_session_invalid_after_logout(self, registered_auth):
        login_result = registered_auth.login("testuser", "SecureP@ss123")
        token = login_result["session_token"]
        registered_auth.logout(token)
        assert not registered_auth.verify_session(token)

    def test_lockout_after_max_attempts(self, registered_auth):
        for _ in range(5):
            registered_auth.login("testuser", "wrong")
        result = registered_auth.login("testuser", "SecureP@ss123")
        assert result["authenticated"] is False

    def test_source_ip_logged(self, registered_auth):
        result = registered_auth.login(
            "testuser", "SecureP@ss123", source_ip="192.168.1.100"
        )
        assert result["authenticated"] is True
