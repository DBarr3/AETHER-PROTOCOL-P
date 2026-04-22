"""
Tests for lib/uvt_routes.py — the HTTP surface for UVT billing.

Strategy: stand up a minimal FastAPI app that mounts ONLY the uvt_router,
and patch the `api_server.svc` session manager to avoid pulling in the full
live backend (which has pre-existing `security.prompt_guard` import issues
unrelated to UVT work).

Every test hits the router through the real FastAPI stack (TestClient) so
dependency injection, request validation, and response serialization are
exercised end-to-end.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════════════
# Shim api_server.svc before importing uvt_routes
# ═══════════════════════════════════════════════════════════════════════════
# uvt_routes imports `from api_server import svc` at call time (not module
# load time), but TestClient dependency resolution triggers that import.
# Rather than pull in the full api_server (which has security.prompt_guard
# issues in this worktree), we build a stand-in module with just the
# session_mgr surface uvt_routes needs.

_session_mgr = MagicMock()
_session_mgr.is_valid = MagicMock(return_value=True)
_session_mgr.get_username = MagicMock(return_value="test@example.com")

_stub_svc = types.SimpleNamespace(session_mgr=_session_mgr)
_stub_api_server = types.ModuleType("api_server")
_stub_api_server.svc = _stub_svc
sys.modules["api_server"] = _stub_api_server

from lib import uvt_routes  # noqa: E402 — must follow the shim
from lib.router import Router  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


_PLAN_ROWS = {
    "free": dict(
        tier="free", display_name="Free",
        price_usd_cents=0, uvt_monthly=15_000,
        sub_agent_cap=5, output_cap=8_000,
        opus_pct_cap=0.0, concurrency_cap=1,
        overage_rate_usd_cents_per_million=None,
        context_budget_tokens=8_000, stripe_price_id=None,
    ),
    "pro": dict(
        tier="pro", display_name="Pro",
        price_usd_cents=4999, uvt_monthly=1_500_000,
        sub_agent_cap=15, output_cap=32_000,
        opus_pct_cap=0.10, concurrency_cap=3,
        overage_rate_usd_cents_per_million=3500,
        context_budget_tokens=80_000, stripe_price_id="price_pro",
    ),
}


def _fake_supabase(
    *,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    email: str = "test@example.com",
    tier: str = "pro",
    subscription_status: str = "active",
    monthly_used: int = 0,
    daily_used: int = 0,
    active_tasks: int = 0,
    overage_enabled: bool = False,
    overage_cap_cents=None,
) -> MagicMock:
    state = {"table": None, "select_cols": None, "filters": {}, "op": None}

    def table(name):
        state["table"] = name
        state["filters"] = {}
        state["op"] = None
        return sb

    def select(cols="*", **kwargs):
        state["select_cols"] = cols
        state["op"] = "select"
        return sb

    def update(payload):
        state["op"] = "update"
        state["update_payload"] = payload
        return sb

    def eq(col, val):
        state["filters"][col] = val
        return sb

    def execute():
        name = state["table"]
        op = state["op"]
        f = state["filters"]

        if op == "update":
            return MagicMock(data=[{"id": f.get("id")}])

        if name == "users":
            cols = state.get("select_cols", "")
            # Email → user_id+tier lookup
            if "id, tier" in cols and f.get("email") == email:
                return MagicMock(data=[{"id": user_id, "tier": tier}])
            # Overage state lookup
            if "overage_enabled" in cols and f.get("id") == user_id:
                return MagicMock(data=[{
                    "overage_enabled": overage_enabled,
                    "overage_cap_usd_cents": overage_cap_cents,
                }])
            # subscription_status lookup
            if "subscription_status" in cols and f.get("id") == user_id:
                return MagicMock(data=[{"subscription_status": subscription_status}])
            return MagicMock(data=[])

        if name == "plans":
            row = _PLAN_ROWS.get(f.get("tier"))
            return MagicMock(data=[row] if row else [])

        if name == "tasks":
            m = MagicMock()
            m.count = active_tasks
            m.data = [{"id": f"t-{i}"} for i in range(active_tasks)]
            return m

        if name == "uvt_balances":
            if monthly_used == 0:
                return MagicMock(data=[])
            return MagicMock(data=[{
                "total_uvt": monthly_used,
                "period_started_at": "2026-04-01T00:00:00Z",
            }])

        if name == "usage_events":
            if daily_used <= 0:
                return MagicMock(data=[])
            return MagicMock(data=[{"uvt_counted": daily_used}])

        return MagicMock(data=[])

    sb = MagicMock()
    sb.table = MagicMock(side_effect=table)
    sb.select = MagicMock(side_effect=select)
    sb.update = MagicMock(side_effect=update)
    sb.eq = MagicMock(side_effect=eq)
    sb.in_ = MagicMock(return_value=sb)
    sb.gte = MagicMock(return_value=sb)
    sb.order = MagicMock(return_value=sb)
    sb.limit = MagicMock(return_value=sb)
    sb.execute = MagicMock(side_effect=execute)
    return sb


@dataclass
class _FakeRouterResp:
    text: str = "hi"
    orchestrator_model: str = "haiku"
    qopc_load: str = "light"
    confidence: float = 0.9
    reason: str = "simple"
    total_uvt: int = 100
    classifier_uvt: int = 50
    reclassified: bool = False


@pytest.fixture
def client_and_state(monkeypatch):
    """Stand up a minimal FastAPI app with just uvt_router mounted, and
    wire a fresh supabase mock + router stub into module-level slots.

    The UVT feature flag (Stage J) is forced ON by default — individual
    tests can monkeypatch it OFF to exercise the 404 gate."""
    monkeypatch.setenv("AETHER_UVT_ENABLED", "true")
    from lib import feature_flags
    feature_flags._reset_first_time_cache_for_tests()

    sb = _fake_supabase()
    router = Router(sb)
    uvt_routes.supabase_client = sb
    uvt_routes.router_instance = router

    app = FastAPI()
    app.include_router(uvt_routes.uvt_router)
    client = TestClient(app)
    yield client, sb, router

    # Cleanup
    uvt_routes.supabase_client = None
    uvt_routes.router_instance = None


def _auth_headers() -> dict:
    return {"Authorization": "Bearer test-token"}


# ═══════════════════════════════════════════════════════════════════════════
# POST /agent/run — happy path
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_run_happy_path(client_and_state):
    client, sb, router = client_and_state
    fake_resp = _FakeRouterResp(text="42", orchestrator_model="haiku",
                                qopc_load="light", confidence=0.95,
                                reason="arithmetic", total_uvt=80, classifier_uvt=40)
    with patch.object(router, "route", new=AsyncMock(return_value=fake_resp)):
        r = client.post(
            "/agent/run",
            json={"prompt": "What's 6*7?"},
            headers=_auth_headers(),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "42"
    assert body["orchestrator_model"] == "haiku"
    assert body["total_uvt"] == 80
    assert body["classifier_uvt"] == 40
    assert body["qopc_load"] == "light"
    assert body["confidence"] == pytest.approx(0.95)
    assert body["overage_in_effect"] is False


# ═══════════════════════════════════════════════════════════════════════════
# POST /agent/run — auth failures
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_run_missing_auth_header(client_and_state):
    client, _, _ = client_and_state
    r = client.post("/agent/run", json={"prompt": "hi"})
    assert r.status_code == 401


def test_agent_run_invalid_session(client_and_state):
    client, _, _ = client_and_state
    _session_mgr.is_valid.return_value = False
    try:
        r = client.post("/agent/run", json={"prompt": "hi"}, headers=_auth_headers())
        assert r.status_code == 401
    finally:
        _session_mgr.is_valid.return_value = True


# ═══════════════════════════════════════════════════════════════════════════
# POST /agent/run — quota gates surface the right HTTP status + detail
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_run_over_monthly_quota_returns_402(client_and_state):
    client, _, _ = client_and_state
    # Pro tier: monthly cap 1.5M, daily cap 225k. Put user at 1,499k monthly
    # with 0 daily used — estimate (~1500 UVT typical) slips past daily cap
    # but still overshoots monthly (1,499k + ~1,500 > 1,500k).
    uvt_routes.supabase_client = _fake_supabase(monthly_used=1_499_000, tier="pro")
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)

    r = client.post(
        "/agent/run",
        json={"prompt": "do a thing"},
        headers=_auth_headers(),
    )
    assert r.status_code == 402
    body = r.json()["detail"]
    assert body["error"] == "monthly_quota"
    assert body["upgrade_to"] == "team"


def test_agent_run_concurrency_cap_returns_429(client_and_state):
    client, _, _ = client_and_state
    # Free tier cap = 1. Set active_tasks=1 so the user has one in-flight.
    uvt_routes.supabase_client = _fake_supabase(active_tasks=1, tier="free")
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)

    r = client.post("/agent/run", json={"prompt": "hi"}, headers=_auth_headers())
    assert r.status_code == 429
    body = r.json()["detail"]
    assert body["error"] == "concurrency"
    assert body["concurrency_cap"] == 1


def test_agent_run_overage_enabled_bypasses_quota(client_and_state):
    client, _, router = client_and_state
    uvt_routes.supabase_client = _fake_supabase(
        monthly_used=1_499_999, tier="pro", overage_enabled=True,
    )
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)
    router = uvt_routes.router_instance

    fake_resp = _FakeRouterResp()
    with patch.object(router, "route", new=AsyncMock(return_value=fake_resp)):
        r = client.post("/agent/run", json={"prompt": "x" * 10},
                        headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["overage_in_effect"] is True


# ═══════════════════════════════════════════════════════════════════════════
# POST /agent/run — request validation
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_run_empty_prompt_rejected(client_and_state):
    client, _, _ = client_and_state
    r = client.post("/agent/run", json={"prompt": ""}, headers=_auth_headers())
    assert r.status_code == 422


def test_agent_run_prompt_too_large_rejected(client_and_state):
    client, _, _ = client_and_state
    r = client.post("/agent/run", json={"prompt": "x" * 60_000}, headers=_auth_headers())
    assert r.status_code == 422


def test_agent_run_missing_prompt_rejected(client_and_state):
    client, _, _ = client_and_state
    r = client.post("/agent/run", json={}, headers=_auth_headers())
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# GET /account/usage
# ═══════════════════════════════════════════════════════════════════════════


def test_account_usage_returns_dashboard_fields(client_and_state):
    client, _, _ = client_and_state
    uvt_routes.supabase_client = _fake_supabase(
        monthly_used=200_000, daily_used=50_000, active_tasks=1,
        tier="pro", overage_enabled=True, overage_cap_cents=5000,
    )
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)

    r = client.get("/account/usage", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "pro"
    assert body["monthly_uvt_used"] == 200_000
    assert body["monthly_uvt_cap"] == 1_500_000
    assert body["monthly_uvt_remaining"] == 1_300_000
    assert body["daily_uvt_used"] == 50_000
    assert body["daily_uvt_cap"] == 225_000
    assert body["concurrency_used"] == 1
    assert body["concurrency_cap"] == 3
    assert body["overage_enabled"] is True
    assert body["overage_cap_usd_cents"] == 5000


def test_account_usage_fresh_user_zero_usage(client_and_state):
    client, _, _ = client_and_state
    r = client.get("/account/usage", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["monthly_uvt_used"] == 0
    assert body["daily_uvt_used"] == 0
    assert body["concurrency_used"] == 0


def test_account_usage_requires_auth(client_and_state):
    client, _, _ = client_and_state
    r = client.get("/account/usage")
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# POST /account/overage
# ═══════════════════════════════════════════════════════════════════════════


def test_overage_enable_requires_active_subscription(client_and_state):
    client, _, _ = client_and_state
    uvt_routes.supabase_client = _fake_supabase(
        subscription_status="inactive", tier="free",
    )
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)

    r = client.post("/account/overage", json={"enabled": True},
                    headers=_auth_headers())
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "payment_required"


def test_overage_enable_allowed_for_active_subscriber(client_and_state):
    client, _, _ = client_and_state
    uvt_routes.supabase_client = _fake_supabase(
        subscription_status="active", tier="pro",
    )
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)

    r = client.post("/account/overage", json={"enabled": True, "cap_usd_cents": 5000},
                    headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["overage_enabled"] is True
    assert body["overage_cap_usd_cents"] == 5000


def test_overage_disable_does_not_require_active_subscription(client_and_state):
    # Disabling is always allowed — users should be able to opt out regardless
    # of subscription state.
    client, _, _ = client_and_state
    uvt_routes.supabase_client = _fake_supabase(
        subscription_status="inactive", tier="free",
    )
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)

    r = client.post("/account/overage", json={"enabled": False},
                    headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["overage_enabled"] is False


def test_overage_cap_negative_rejected(client_and_state):
    client, _, _ = client_and_state
    r = client.post("/account/overage", json={"enabled": True, "cap_usd_cents": -1},
                    headers=_auth_headers())
    assert r.status_code == 422


def test_overage_cap_too_large_rejected(client_and_state):
    client, _, _ = client_and_state
    # 10 billion cents = $100M. Field max is $10M ceiling.
    r = client.post("/account/overage",
                    json={"enabled": True, "cap_usd_cents": 10_000_000_000},
                    headers=_auth_headers())
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Stage J — feature-flag gating
# ═══════════════════════════════════════════════════════════════════════════


def test_agent_run_returns_404_when_flag_off(client_and_state, monkeypatch):
    """When AETHER_UVT_ENABLED=false and no per-user override, the endpoint
    pretends it doesn't exist — 404 with error=uvt_not_enabled. Desktop
    falls back to the legacy /agent/chat path."""
    client, _, _ = client_and_state
    monkeypatch.setenv("AETHER_UVT_ENABLED", "false")
    r = client.post("/agent/run", json={"prompt": "hi"}, headers=_auth_headers())
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "uvt_not_enabled"


def test_account_usage_returns_404_when_flag_off(client_and_state, monkeypatch):
    client, _, _ = client_and_state
    monkeypatch.setenv("AETHER_UVT_ENABLED", "false")
    r = client.get("/account/usage", headers=_auth_headers())
    assert r.status_code == 404


def test_account_overage_returns_404_when_flag_off(client_and_state, monkeypatch):
    client, _, _ = client_and_state
    monkeypatch.setenv("AETHER_UVT_ENABLED", "false")
    r = client.post("/account/overage", json={"enabled": True},
                    headers=_auth_headers())
    assert r.status_code == 404


def test_flag_off_but_user_override_on_bypasses_gate(client_and_state, monkeypatch):
    """The canary-for-yourself pattern: flag off globally, but your user_id
    is in overrides. You get UVT; everyone else gets 404."""
    client, _, router = client_and_state
    monkeypatch.setenv("AETHER_UVT_ENABLED", "false")

    # Build supabase that returns a specific user_id for our session email
    overridden_uid = "33333333-3333-3333-3333-333333333333"
    uvt_routes.supabase_client = _fake_supabase(user_id=overridden_uid, tier="pro")
    uvt_routes.router_instance = Router(uvt_routes.supabase_client)
    router = uvt_routes.router_instance
    monkeypatch.setenv("AETHER_UVT_USER_OVERRIDES", f"{overridden_uid}:true")

    from unittest.mock import AsyncMock
    fake_resp = _FakeRouterResp()
    with patch.object(router, "route", new=AsyncMock(return_value=fake_resp)):
        r = client.post("/agent/run", json={"prompt": "hi"},
                        headers=_auth_headers())
    assert r.status_code == 200
