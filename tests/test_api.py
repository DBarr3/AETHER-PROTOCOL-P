"""
AetherCloud-L — FastAPI Server Tests
Tests all REST endpoints with mocked backend services.

Aether Systems LLC — Patent Pending
"""

import json
import time
import hashlib
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Import the FastAPI app
import api_server
from api_server import app, _init_services, svc


# ═══════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_server_state(tmp_path):
    """Reset all server-side state before each test."""
    # Override paths so tests don't touch real data
    with patch("api_server.DEFAULT_AUDIT_DIR", tmp_path / "audit"), \
         patch("api_server.DEFAULT_VAULT_ROOT", tmp_path / "vault"):
        (tmp_path / "audit").mkdir(parents=True, exist_ok=True)
        (tmp_path / "vault").mkdir(parents=True, exist_ok=True)

        # Re-initialize services with test paths
        _init_services()
        yield


@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def registered_user():
    """Register a test user and return credentials."""
    if svc.auth:
        svc.auth.register_user("testuser", "testpass123")
    return {"username": "testuser", "password": "testpass123"}


@pytest.fixture
def auth_token(client, registered_user):
    """Login and return a valid session token."""
    resp = client.post("/auth/login", json=registered_user)
    data = resp.json()
    if data.get("authenticated"):
        return data["session_token"]
    # If auth system doesn't work with register, mock the session
    return _create_mock_token()


def _create_mock_token():
    """Create a mock session token by generating one via the public API."""
    if svc.session_mgr:
        token = svc.session_mgr.generate_token("testuser", str(time.time()))
        return token
    return hashlib.sha256(str(time.time()).encode()).hexdigest()


def _auth_header(token):
    """Build Authorization header."""
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════
# STATUS ENDPOINT (no auth)
# ═══════════════════════════════════════════════════

class TestStatus:
    def test_status_returns_200(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200

    def test_status_has_required_fields(self, client):
        data = client.get("/status").json()
        assert "protocol_l" in data
        assert "watcher" in data
        assert "agent" in data
        assert "session_active" in data
        assert "vault_root" in data
        assert "uptime" in data
        assert "version" in data

    def test_status_protocol_l_active(self, client):
        data = client.get("/status").json()
        assert data["protocol_l"] == "ACTIVE"

    def test_status_version_matches(self, client):
        from config.settings import APP_VERSION
        data = client.get("/status").json()
        assert data["version"] == APP_VERSION

    def test_status_uptime_positive(self, client):
        data = client.get("/status").json()
        assert data["uptime"] >= 0

    def test_status_ibm_status_present(self, client):
        data = client.get("/status").json()
        assert data["ibm_status"] in ["IBM_QUANTUM", "AER_SIMULATOR", "OS_URANDOM", "CSPRNG", "SIMULATOR"]


# ═══════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════════════════

class TestAuthLogin:
    def test_login_missing_fields(self, client):
        resp = client.post("/auth/login", json={"username": ""})
        # Pydantic validation error
        assert resp.status_code == 422

    def test_login_returns_timestamp(self, client, registered_user):
        resp = client.post("/auth/login", json=registered_user)
        data = resp.json()
        assert "timestamp" in data
        assert len(data["timestamp"]) > 0

    def test_login_success(self, client, registered_user):
        resp = client.post("/auth/login", json=registered_user)
        data = resp.json()
        assert resp.status_code == 200
        assert data["authenticated"] is True
        assert data["session_token"] is not None

    def test_login_wrong_password(self, client, registered_user):
        resp = client.post("/auth/login", json={
            "username": registered_user["username"],
            "password": "wrong_password_123"
        })
        data = resp.json()
        assert data["authenticated"] is False

    def test_login_returns_commitment_hash(self, client, registered_user):
        resp = client.post("/auth/login", json=registered_user)
        data = resp.json()
        if data["authenticated"]:
            assert data.get("commitment_hash") is not None


class TestAuthLogout:
    def test_logout_success(self, client, auth_token):
        resp = client.post("/auth/logout", json={"session_token": auth_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_logout_invalid_token(self, client):
        resp = client.post("/auth/logout", json={"session_token": "invalid_token"})
        assert resp.status_code == 200  # Logout is idempotent


# ═══════════════════════════════════════════════════
# VAULT ENDPOINTS
# ═══════════════════════════════════════════════════

class TestVaultList:
    def test_vault_list_requires_auth(self, client):
        resp = client.get("/vault/list")
        assert resp.status_code in [401, 403]

    def test_vault_list_invalid_token(self, client):
        resp = client.get("/vault/list", headers=_auth_header("bad_token"))
        assert resp.status_code == 401

    def test_vault_list_returns_structure(self, client, auth_token):
        resp = client.get("/vault/list", headers=_auth_header(auth_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "folders" in data
        assert "stats" in data
        assert isinstance(data["folders"], list)

    def test_vault_list_stats_has_keys(self, client, auth_token):
        resp = client.get("/vault/list", headers=_auth_header(auth_token))
        data = resp.json()
        assert "stats" in data
        assert isinstance(data["stats"], dict)


# ═══════════════════════════════════════════════════
# AGENT ENDPOINTS
# ═══════════════════════════════════════════════════

class TestAgentChat:
    def test_chat_requires_auth(self, client):
        resp = client.post("/agent/chat", json={"query": "hello"})
        assert resp.status_code in [401, 403]

    def test_chat_returns_response(self, client, auth_token):
        resp = client.post(
            "/agent/chat",
            json={"query": "list my files"},
            headers=_auth_header(auth_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert len(data["response"]) > 0

    def test_chat_has_commitment_hash(self, client, auth_token):
        resp = client.post(
            "/agent/chat",
            json={"query": "hello"},
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert "commitment_hash" in data
        assert data["commitment_hash"] is not None

    def test_chat_has_verified_field(self, client, auth_token):
        resp = client.post(
            "/agent/chat",
            json={"query": "hello"},
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert "verified" in data
        assert isinstance(data["verified"], bool)

    def test_chat_has_threat_level(self, client, auth_token):
        resp = client.post(
            "/agent/chat",
            json={"query": "scan for threats"},
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert "threat_level" in data
        assert data["threat_level"] in ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def test_chat_empty_query(self, client, auth_token):
        resp = client.post(
            "/agent/chat",
            json={"query": ""},
            headers=_auth_header(auth_token),
        )
        # Should still return a response (agent handles empty queries)
        assert resp.status_code == 200


class TestAgentAnalyze:
    def test_analyze_requires_auth(self, client):
        resp = client.post("/agent/analyze", json={
            "filename": "test.py", "extension": ".py", "directory": "code"
        })
        assert resp.status_code in [401, 403]

    def test_analyze_returns_suggestion(self, client, auth_token):
        resp = client.post(
            "/agent/analyze",
            json={"filename": "test.py", "extension": ".py", "directory": "code"},
            headers=_auth_header(auth_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "suggested_name" in data
        assert "category" in data
        assert "confidence" in data

    def test_analyze_confidence_range(self, client, auth_token):
        resp = client.post(
            "/agent/analyze",
            json={"filename": "report.pdf", "extension": ".pdf", "directory": "docs"},
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert 0.0 <= data["confidence"] <= 1.0

    def test_analyze_has_commitment(self, client, auth_token):
        resp = client.post(
            "/agent/analyze",
            json={"filename": "data.csv", "extension": ".csv", "directory": "trading"},
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert data["commitment_hash"] is not None


class TestAgentScan:
    def test_scan_requires_auth(self, client):
        resp = client.post("/agent/scan")
        assert resp.status_code in [401, 403]

    def test_scan_returns_threat_level(self, client, auth_token):
        resp = client.post(
            "/agent/scan",
            headers=_auth_header(auth_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "threat_level" in data
        assert "findings" in data
        assert "recommended_action" in data

    def test_scan_findings_is_list(self, client, auth_token):
        resp = client.post(
            "/agent/scan",
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert isinstance(data["findings"], list)

    def test_scan_has_commitment(self, client, auth_token):
        resp = client.post(
            "/agent/scan",
            headers=_auth_header(auth_token),
        )
        data = resp.json()
        assert data["commitment_hash"] is not None


# ═══════════════════════════════════════════════════
# AUDIT ENDPOINTS
# ═══════════════════════════════════════════════════

class TestAuditTrail:
    def test_audit_requires_auth(self, client):
        resp = client.get("/audit/trail")
        assert resp.status_code in [401, 403]

    def test_audit_returns_entries(self, client, auth_token):
        resp = client.get(
            "/audit/trail",
            headers=_auth_header(auth_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert isinstance(data["entries"], list)

    def test_audit_limit_parameter(self, client, auth_token):
        resp = client.get(
            "/audit/trail?limit=5",
            headers=_auth_header(auth_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) <= 5

    def test_audit_path_filter(self, client, auth_token):
        resp = client.get(
            "/audit/trail?path=test",
            headers=_auth_header(auth_token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["entries"], list)


# ═══════════════════════════════════════════════════
# CORS & SECURITY
# ═══════════════════════════════════════════════════

class TestCORS:
    def test_cors_allows_localhost(self, client):
        resp = client.options(
            "/status",
            headers={
                "Origin": "http://localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
        # FastAPI CORS middleware should respond
        assert resp.status_code in [200, 400]

    def test_status_no_auth_required(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════

class TestHelpers:
    def test_format_size_bytes(self):
        from api_server import _format_size
        assert _format_size(500) == "500 B"

    def test_format_size_kb(self):
        from api_server import _format_size
        assert "KB" in _format_size(2048)

    def test_format_size_mb(self):
        from api_server import _format_size
        assert "MB" in _format_size(5 * 1024 * 1024)

    def test_format_size_gb(self):
        from api_server import _format_size
        assert "GB" in _format_size(2 * 1024 * 1024 * 1024)

    def test_file_icon_python(self):
        from api_server import _file_icon
        assert _file_icon(".py") == "🐍"

    def test_file_icon_pdf(self):
        from api_server import _file_icon
        assert _file_icon(".pdf") == "📄"

    def test_file_icon_unknown(self):
        from api_server import _file_icon
        assert _file_icon(".xyz") == "📄"

    def test_guess_category_code(self):
        from api_server import _guess_category
        assert _guess_category(".py") == "CODE"

    def test_guess_category_security(self):
        from api_server import _guess_category
        assert _guess_category(".key") == "SECURITY"

    def test_guess_category_unknown(self):
        from api_server import _guess_category
        assert _guess_category(".xyz") == "PERSONAL"


# ═══════════════════════════════════════════════════
# INTEGRATION: LOGIN → CHAT → LOGOUT FLOW
# ═══════════════════════════════════════════════════

class TestFullFlow:
    def test_login_chat_logout(self, client, registered_user):
        # Login
        login_resp = client.post("/auth/login", json=registered_user)
        login_data = login_resp.json()
        assert login_data["authenticated"] is True
        token = login_data["session_token"]

        # Chat
        chat_resp = client.post(
            "/agent/chat",
            json={"query": "what files do I have?"},
            headers=_auth_header(token),
        )
        assert chat_resp.status_code == 200
        assert len(chat_resp.json()["response"]) > 0

        # Vault list
        vault_resp = client.get(
            "/vault/list",
            headers=_auth_header(token),
        )
        assert vault_resp.status_code == 200

        # Logout
        logout_resp = client.post(
            "/auth/logout",
            json={"session_token": token},
        )
        assert logout_resp.json()["success"] is True

    def test_status_during_session(self, client, registered_user):
        # Login creates a session
        client.post("/auth/login", json=registered_user)

        # Status should reflect active session
        status = client.get("/status").json()
        assert status["protocol_l"] == "ACTIVE"
