"""
Tests for lib/health_routes.py — the /healthz family.

Mounts just the health_router on a bare FastAPI + asserts:
- /healthz always returns 200 + ok:true (no DB dep)
- /healthz/flags matches feature_flags.flag_snapshot()
- /healthz/deep returns 200 when Supabase is happy, 503 when it errors

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib import health_routes


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(health_routes.health_router)
    health_routes.supabase_client = None
    yield TestClient(app)
    health_routes.supabase_client = None


# ═══════════════════════════════════════════════════════════════════════════
# /healthz — liveness
# ═══════════════════════════════════════════════════════════════════════════


def test_healthz_always_returns_200(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "sha" in body
    assert isinstance(body["uptime_s"], (int, float))
    assert body["uptime_s"] >= 0


def test_healthz_works_even_with_supabase_unconfigured(client):
    # Precisely what should happen: shallow check is dependency-free.
    health_routes.supabase_client = None
    r = client.get("/healthz")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# /healthz/flags
# ═══════════════════════════════════════════════════════════════════════════


def test_flags_default_shape(client, monkeypatch):
    for v in ("AETHER_UVT_ENABLED", "AETHER_UVT_ROLLOUT_PCT", "AETHER_UVT_USER_OVERRIDES"):
        monkeypatch.delenv(v, raising=False)
    r = client.get("/healthz/flags")
    assert r.status_code == 200
    body = r.json()
    assert body["AETHER_UVT_ENABLED"] == "false"
    assert body["AETHER_UVT_ROLLOUT_PCT"] == 0
    assert body["override_count"] == 0


def test_flags_reflect_env_updates(client, monkeypatch):
    monkeypatch.setenv("AETHER_UVT_ENABLED", "true")
    monkeypatch.setenv("AETHER_UVT_ROLLOUT_PCT", "25")
    monkeypatch.setenv("AETHER_UVT_USER_OVERRIDES", "uid-1:true,uid-2:false")
    r = client.get("/healthz/flags")
    body = r.json()
    assert body["AETHER_UVT_ENABLED"] == "true"
    assert body["AETHER_UVT_ROLLOUT_PCT"] == 25
    assert body["override_count"] == 2
    # Never leaks user IDs
    raw = r.text
    assert "uid-1" not in raw
    assert "uid-2" not in raw


def test_flags_response_contains_literal_string_for_cron_grep(client):
    """deploy/healthcheck.sh greps for 'AETHER_UVT_ENABLED' literally —
    the snapshot JSON must include that key name."""
    r = client.get("/healthz/flags")
    assert "AETHER_UVT_ENABLED" in r.text


# ═══════════════════════════════════════════════════════════════════════════
# /healthz/deep
# ═══════════════════════════════════════════════════════════════════════════


def test_deep_503_when_supabase_unconfigured(client):
    health_routes.supabase_client = None
    r = client.get("/healthz/deep")
    assert r.status_code == 503
    assert r.json()["db"] == "not_configured"


def test_deep_200_when_supabase_returns_data(client):
    sb = MagicMock()
    sb.table.return_value.select.return_value.limit.return_value.execute.return_value = \
        MagicMock(data=[{"tier": "free"}])
    health_routes.supabase_client = sb
    r = client.get("/healthz/deep")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"] == "ok"
    # Stripe is skipped by design — documented
    assert body["stripe"] == "skipped_by_design"


def test_deep_503_when_supabase_raises(client):
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("connection refused")
    health_routes.supabase_client = sb
    r = client.get("/healthz/deep")
    assert r.status_code == 503
    body = r.json()
    assert "error" in body["db"]
