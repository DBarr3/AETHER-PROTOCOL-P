"""
Tests for lib/router_client.py.

PolicyGate HTTP is mocked — no network. We verify:
- 200 response parses into RoutingDecision
- 402/413/429 with router_gate body raises RouterGateRejected (typed fields)
- Timeout / 5xx / network-error raises RouterUnreachable (NEVER returns a fallback)
- Service token is forwarded in x-aether-internal header

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from lib import router_client
from lib.router_client import (
    RoutingDecision,
    RouterGateRejected,
    RouterUnreachable,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AETHER_ROUTER_URL", "http://policygate.test/api/internal/router/pick")
    monkeypatch.setenv("AETHER_INTERNAL_SERVICE_TOKEN", "test-token-abc")


@pytest.fixture
def reset_client():
    router_client._client = None
    yield
    router_client._client = None


def _mock_client(post_mock: AsyncMock, monkeypatch):
    fake = MagicMock()
    fake.post = post_mock
    monkeypatch.setattr(router_client, "_get_client", lambda: fake)


def _json_response(status: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=body)
    return resp


VALID_CTX = {
    # C1/C2/C3: opusPctMtd, activeConcurrentTasks, uvtBalance are
    # server-resolved by the TS PolicyGate route and are NOT part of
    # the Python-side request contract anymore. See
    # tests/security/redteam_policygate_report.md and lib/uvt_routes.py
    # (H1 fix removed the hardcoded bypass values from the shadow
    # dispatch).
    "userId": "00000000-0000-0000-0000-000000000001",
    "tier": "pro",
    "taskKind": "chat",
    "estimatedInputTokens": 100,
    "estimatedOutputTokens": 100,
    "requestId": "req_1",
    "traceId": "trace_1",
}


@pytest.mark.asyncio
async def test_200_parses_into_RoutingDecision(monkeypatch, reset_client):
    body = {
        "chosen_model": "claude-sonnet-4",
        "reason_code": "default_by_tier_and_task",
        "predicted_uvt_cost": 300,
        "predicted_uvt_cost_simple": 200,
        "decision_schema_version": 1,
        "uvt_weight_version": 1,
        "latency_ms": 2,
    }
    post = AsyncMock(return_value=_json_response(200, body))
    _mock_client(post, monkeypatch)

    decision = await router_client.pick(VALID_CTX)
    assert isinstance(decision, RoutingDecision)
    assert decision.chosen_model == "claude-sonnet-4"
    assert decision.predicted_uvt_cost == 300
    assert decision.predicted_uvt_cost_simple == 200
    assert decision.decision_schema_version == 1


@pytest.mark.asyncio
async def test_forwards_service_token_header(monkeypatch, reset_client):
    body = {
        "chosen_model": "claude-sonnet-4",
        "reason_code": "default_by_tier_and_task",
        "predicted_uvt_cost": 0,
        "predicted_uvt_cost_simple": 0,
        "decision_schema_version": 1,
        "uvt_weight_version": 1,
        "latency_ms": 1,
    }
    post = AsyncMock(return_value=_json_response(200, body))
    _mock_client(post, monkeypatch)

    await router_client.pick(VALID_CTX)
    call = post.await_args
    assert call.kwargs["headers"]["x-aether-internal"] == "test-token-abc"


@pytest.mark.asyncio
async def test_429_router_gate_raises_RouterGateRejected(monkeypatch, reset_client):
    body = {
        "error": "router_gate",
        "gate_type": "concurrency_cap_exceeded",
        "user_message_code": "concurrency_exceeded",
        "gate_cap_key": "concurrency_cap",
        "plan_cap_value": 3,
        "observed_value": 3,
        "trace_id": "trace_1",
    }
    post = AsyncMock(return_value=_json_response(429, body))
    _mock_client(post, monkeypatch)

    with pytest.raises(RouterGateRejected) as ei:
        await router_client.pick(VALID_CTX)
    assert ei.value.gate_type == "concurrency_cap_exceeded"
    assert ei.value.user_message_code == "concurrency_exceeded"
    assert ei.value.gate_cap_key == "concurrency_cap"
    assert ei.value.http_status == 429


@pytest.mark.asyncio
async def test_402_opus_budget_router_gate_raises(monkeypatch, reset_client):
    body = {
        "error": "router_gate",
        "gate_type": "opus_budget_exceeded",
        "user_message_code": "opus_budget_exceeded",
        "gate_cap_key": "opus_pct_cap",
        "plan_cap_value": 0.1,
        "observed_value": 0.12,
        "trace_id": "trace_1",
    }
    post = AsyncMock(return_value=_json_response(402, body))
    _mock_client(post, monkeypatch)

    with pytest.raises(RouterGateRejected) as ei:
        await router_client.pick(VALID_CTX)
    assert ei.value.gate_type == "opus_budget_exceeded"


@pytest.mark.asyncio
async def test_timeout_raises_RouterUnreachable_never_fallback(monkeypatch, reset_client):
    post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    _mock_client(post, monkeypatch)

    with pytest.raises(RouterUnreachable):
        await router_client.pick(VALID_CTX)


@pytest.mark.asyncio
async def test_network_error_raises_RouterUnreachable(monkeypatch, reset_client):
    post = AsyncMock(side_effect=httpx.NetworkError("connection refused"))
    _mock_client(post, monkeypatch)

    with pytest.raises(RouterUnreachable):
        await router_client.pick(VALID_CTX)


@pytest.mark.asyncio
async def test_500_raises_RouterUnreachable(monkeypatch, reset_client):
    post = AsyncMock(return_value=_json_response(500, {"error": "internal"}))
    _mock_client(post, monkeypatch)

    with pytest.raises(RouterUnreachable):
        await router_client.pick(VALID_CTX)


@pytest.mark.asyncio
async def test_400_non_gate_raises_RouterUnreachable(monkeypatch, reset_client):
    # A 4xx that isn't a router_gate body is treated as protocol failure.
    post = AsyncMock(return_value=_json_response(400, {"error": "validation_failed"}))
    _mock_client(post, monkeypatch)

    with pytest.raises(RouterUnreachable):
        await router_client.pick(VALID_CTX)
