"""
Tests for /api/license/... endpoints and lib/license_validation.py.

Covers the 15 required cases from the Sequence 1 brief:
    1  Valid key + active subscription → 200, valid=true, correct plan
    2  Valid key + canceled subscription → 200, valid=false, reason
    3  Valid key + past_due → 200, valid=false, reason
    4  Nonexistent key (correct format) → 200, valid=false, license_not_found
    5  Malformed "FOO-BAR" → 400, error=malformed_key
    6  Empty string key → 400
    7  SQL-injection-looking key → 400 (rejected by regex before DB)
    8  Lowercase key → normalized, matches
    9  Leading/trailing whitespace → stripped, matches
    10 11 requests rapid-fire same IP → 11th returns 429
    11 Supabase raises → 500, error=upstream_error
    12 Response never contains SUPABASE_SERVICE_ROLE_KEY in any field
    13 Log capture shows "****-XXXX" pattern, never full key
    14 Both legacy and v2 paths return identical responses
    15 GET request → 405 Method Not Allowed

Supabase is mocked — no production calls.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import api_server
import lib.license_validation as lic
from api_server import app


# ═══════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════

@pytest.fixture
def client():
    """FastAPI TestClient for the app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_license_module_state(monkeypatch):
    """Reset cached Supabase client and required env vars between tests.

    Sets a sentinel SUPABASE_SERVICE_ROLE_KEY so test 12 can assert the
    value never leaks into any response body.
    """
    lic._reset_client_for_tests()
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_SENTINEL_MUST_NOT_LEAK")
    yield
    lic._reset_client_for_tests()


def _build_mock_supabase(rows=None, raises=None):
    """Return (client_mock, execute_mock) wired so that
    client.table(...).select(...).eq(...).limit(...).execute() returns a
    response with the given rows, OR raises the given exception."""
    execute_mock = MagicMock()
    if raises is not None:
        execute_mock.side_effect = raises
    else:
        response = MagicMock()
        response.data = rows or []
        execute_mock.return_value = response

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute = execute_mock

    client_mock = MagicMock()
    client_mock.table.return_value = chain
    return client_mock, execute_mock


def _patch_client(rows=None, raises=None):
    """Patch get_supabase_client to return a mock matching the given data."""
    client_mock, execute_mock = _build_mock_supabase(rows=rows, raises=raises)
    return patch.object(lic, "get_supabase_client", return_value=client_mock), execute_mock


LEGACY_PATH = "/api/license/license/cloud/validate"
# V2_PATH = "/api/license/v2/validate"  # added in Commit 4


# ═══════════════════════════════════════════════════
# 1–3: valid key, varying subscription states
# ═══════════════════════════════════════════════════

def test_1_valid_key_active_returns_valid_true(client):
    """Valid key + active subscription → 200, valid=true, plan=solo."""
    rows = [{
        "tier": "solo",
        "subscription_status": "active",
        "email": "alice@example.com",
        "current_period_end": "2026-05-18T00:00:00+00:00",
    }]
    ctx, _ = _patch_client(rows=rows)
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "AETH-CLD-ABCD-EFGH-1234", "version": "0.9.6"},
            headers={"Authorization": "Bearer test-1"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["plan"] == "solo"
    assert body["expires_at"] == "2026-05-18T00:00:00+00:00"
    assert body["client_id"] == "alice@example.com"
    assert body["grace_mode"] is False
    assert body["reason"] is None


def test_2_valid_key_canceled_returns_valid_false(client):
    """Valid key + canceled subscription → 200, valid=false, reason set."""
    rows = [{
        "tier": "pro",
        "subscription_status": "canceled",
        "email": "bob@example.com",
        "current_period_end": "2026-04-01T00:00:00+00:00",
    }]
    ctx, _ = _patch_client(rows=rows)
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "AETH-CLD-ABCD-EFGH-1234"},
            headers={"Authorization": "Bearer test-2"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["plan"] == "pro"
    assert body["reason"] == "subscription_canceled"
    # Key metadata still returned so desktop UI can show "expired on X"
    assert body["expires_at"] == "2026-04-01T00:00:00+00:00"
    assert body["client_id"] == "bob@example.com"


def test_3_valid_key_past_due_returns_valid_false(client):
    """Valid key + past_due → 200, valid=false, reason=subscription_past_due."""
    rows = [{
        "tier": "team",
        "subscription_status": "past_due",
        "email": "carol@example.com",
        "current_period_end": "2026-04-10T00:00:00+00:00",
    }]
    ctx, _ = _patch_client(rows=rows)
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "AETH-CLD-ABCD-EFGH-1234"},
            headers={"Authorization": "Bearer test-3"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["plan"] == "team"
    assert body["reason"] == "subscription_past_due"


# ═══════════════════════════════════════════════════
# 4: nonexistent key
# ═══════════════════════════════════════════════════

def test_4_nonexistent_key_returns_license_not_found(client):
    """Correct format but key not in DB → 200, valid=false, license_not_found."""
    ctx, _ = _patch_client(rows=[])
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "AETH-CLD-ZZZZ-ZZZZ-ZZZZ"},
            headers={"Authorization": "Bearer test-4"},
        )
    # Must be 200 (not 404) to prevent status-code-based key enumeration.
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["plan"] is None
    assert body["expires_at"] is None
    assert body["client_id"] is None
    assert body["reason"] == "license_not_found"


# ═══════════════════════════════════════════════════
# 5–7: malformed keys (rejected by regex before DB)
# ═══════════════════════════════════════════════════

def test_5_malformed_key_returns_400(client):
    """'FOO-BAR' fails regex → 400, error=malformed_key."""
    ctx, execute_mock = _patch_client()
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "FOO-BAR"},
            headers={"Authorization": "Bearer test-5"},
        )
    assert resp.status_code == 400
    assert resp.json() == {"error": "malformed_key"}
    # Crucially: no Supabase call was made for the malformed key
    execute_mock.assert_not_called()


def test_6_empty_key_returns_400(client):
    """Empty string → 400."""
    ctx, execute_mock = _patch_client()
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": ""},
            headers={"Authorization": "Bearer test-6"},
        )
    assert resp.status_code == 400
    assert resp.json() == {"error": "malformed_key"}
    execute_mock.assert_not_called()


def test_7_sql_injection_key_rejected_before_db(client):
    """SQL-injection-looking input → 400 via regex, never reaches DB."""
    ctx, execute_mock = _patch_client()
    evil = "AETH-CLD-' OR 1=1--"  # would be a problem if regex didn't catch it
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": evil},
            headers={"Authorization": "Bearer test-7"},
        )
    assert resp.status_code == 400
    assert resp.json() == {"error": "malformed_key"}
    # Crucial: regex gate blocks the string before any parameterized query runs
    execute_mock.assert_not_called()


# ═══════════════════════════════════════════════════
# 8–9: normalization
# ═══════════════════════════════════════════════════

def test_8_lowercase_key_is_normalized_and_matches(client):
    """Lowercase key input → uppercased → queried."""
    rows = [{
        "tier": "free",
        "subscription_status": "active",
        "email": "dan@example.com",
        "current_period_end": None,
    }]
    ctx, execute_mock = _patch_client(rows=rows)
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "aeth-cld-abcd-efgh-1234"},
            headers={"Authorization": "Bearer test-8"},
        )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
    assert resp.json()["plan"] == "free"


def test_9_whitespace_is_stripped(client):
    """Leading/trailing whitespace → stripped → queried."""
    rows = [{
        "tier": "solo",
        "subscription_status": "active",
        "email": "eve@example.com",
        "current_period_end": None,
    }]
    ctx, _ = _patch_client(rows=rows)
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "   AETH-CLD-ABCD-EFGH-1234\n\t  "},
            headers={"Authorization": "Bearer test-9"},
        )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


# ═══════════════════════════════════════════════════
# 10: rate limit
# ═══════════════════════════════════════════════════

def test_10_rate_limit_after_10_requests_same_key(client):
    """10 requests with same Bearer token pass; the 11th is rate-limited."""
    rows = [{
        "tier": "solo",
        "subscription_status": "active",
        "email": "f@example.com",
        "current_period_end": None,
    }]
    ctx, _ = _patch_client(rows=rows)
    shared_auth = {"Authorization": "Bearer rl-test-shared"}
    with ctx:
        for i in range(10):
            resp = client.post(
                LEGACY_PATH,
                json={"key": "AETH-CLD-ABCD-EFGH-1234"},
                headers=shared_auth,
            )
            assert resp.status_code == 200, (
                f"Request {i + 1}/10 should succeed but got {resp.status_code}"
            )
        # 11th attempt — must be rate-limited
        resp = client.post(
            LEGACY_PATH,
            json={"key": "AETH-CLD-ABCD-EFGH-1234"},
            headers=shared_auth,
        )
        assert resp.status_code == 429, (
            f"11th request should be rate-limited (429) but got {resp.status_code}"
        )


# ═══════════════════════════════════════════════════
# 11: Supabase raises
# ═══════════════════════════════════════════════════

def test_11_supabase_raises_returns_500_upstream_error(client):
    """Supabase query raises → 500, error=upstream_error, no stack trace."""
    ctx, _ = _patch_client(raises=RuntimeError("connection refused"))
    with ctx:
        resp = client.post(
            LEGACY_PATH,
            json={"key": "AETH-CLD-ABCD-EFGH-1234"},
            headers={"Authorization": "Bearer test-11"},
        )
    assert resp.status_code == 500
    body = resp.json()
    assert body == {"error": "upstream_error"}
    # Stack trace must not leak in the response
    serialized = json.dumps(body)
    assert "connection refused" not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


# ═══════════════════════════════════════════════════
# 12: response never contains service role key
# ═══════════════════════════════════════════════════

def test_12_response_never_contains_service_role_key(client):
    """Every response body path must not leak SUPABASE_SERVICE_ROLE_KEY."""
    sentinel = "sb_secret_SENTINEL_MUST_NOT_LEAK"  # set by autouse fixture
    rows = [{
        "tier": "solo",
        "subscription_status": "active",
        "email": "g@example.com",
        "current_period_end": None,
    }]
    ctx, _ = _patch_client(rows=rows)
    with ctx:
        # Valid
        r1 = client.post(
            LEGACY_PATH, json={"key": "AETH-CLD-ABCD-EFGH-1234"},
            headers={"Authorization": "Bearer test-12a"},
        )
        # Not found
        ctx2, _ = _patch_client(rows=[])
        with ctx2:
            r2 = client.post(
                LEGACY_PATH, json={"key": "AETH-CLD-ZZZZ-ZZZZ-ZZZZ"},
                headers={"Authorization": "Bearer test-12b"},
            )
        # Malformed
        r3 = client.post(
            LEGACY_PATH, json={"key": "bad"},
            headers={"Authorization": "Bearer test-12c"},
        )
        # Upstream error
        ctx3, _ = _patch_client(raises=RuntimeError("boom"))
        with ctx3:
            r4 = client.post(
                LEGACY_PATH, json={"key": "AETH-CLD-ABCD-EFGH-1234"},
                headers={"Authorization": "Bearer test-12d"},
            )
    for r in (r1, r2, r3, r4):
        assert sentinel not in r.text, (
            f"service role key leaked in response: {r.text}"
        )


# ═══════════════════════════════════════════════════
# 13: log redaction
# ═══════════════════════════════════════════════════

def test_13_logs_redact_license_key_last4(client, caplog):
    """Logs must never contain the full license key — only last 4 chars."""
    full_key = "AETH-CLD-ABCD-EFGH-1234"
    rows = [{
        "tier": "solo",
        "subscription_status": "active",
        "email": "h@example.com",
        "current_period_end": None,
    }]
    ctx, _ = _patch_client(rows=rows)
    with caplog.at_level(logging.INFO, logger="aethercloud.license"):
        with ctx:
            client.post(
                LEGACY_PATH, json={"key": full_key},
                headers={"Authorization": "Bearer test-13"},
            )
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "****-1234" in log_text, "expected redacted last4 marker in logs"
    # Full key (minus the last 4 that are part of the redacted form) must not appear
    assert "AETH-CLD-ABCD-EFGH-1234" not in log_text
    # The full middle of the key must never appear
    assert "ABCD-EFGH" not in log_text


# ═══════════════════════════════════════════════════
# 14: legacy and v2 paths behave identically
#     (deferred to Commit 4 — v2 route does not exist yet in this commit)
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 15: GET → 405
# ═══════════════════════════════════════════════════

def test_15_get_method_returns_405(client):
    """Keys must never appear in URLs/query strings/logs — GET is rejected."""
    # v2 path coverage added in Commit 4 alongside the route itself.
    resp = client.get(LEGACY_PATH)
    assert resp.status_code == 405, (
        f"GET {LEGACY_PATH} should return 405, got {resp.status_code}"
    )
