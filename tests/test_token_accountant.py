"""
Tests for lib/token_accountant.py.

The Anthropic HTTP call is mocked — no network. We verify:
- prompt caching is applied to system + tool schemas (headers + payload shape)
- usage accounting is computed correctly from Anthropic's `usage` block
- rpc_record_usage is called with the exact parameter names the migration defined
- failures in rpc_record_usage fall through to the DLQ (never silently lose billing)

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from lib import token_accountant


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")


@pytest.fixture
def dlq_path(tmp_path, monkeypatch):
    path = tmp_path / "usage_dlq.jsonl"
    monkeypatch.setenv("AETHER_USAGE_DLQ", str(path))
    return path


def _fake_anthropic_response(
    text: str = "hi",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cached_input: int = 0,
    tool_uses: list | None = None,
) -> dict:
    content: list = [{"type": "text", "text": text}]
    if tool_uses:
        content.extend(tool_uses)
    return {
        "id": "msg_test",
        "content": content,
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cached_input,
        },
    }


class _MockTransport(httpx.AsyncBaseTransport):
    """Captures the outgoing request + returns a canned JSON response."""

    def __init__(self, response_body: dict):
        self.response_body = response_body
        self.captured_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_request = request
        return httpx.Response(200, json=self.response_body)


def _captured_payload(transport: _MockTransport) -> dict:
    assert transport.captured_request is not None
    return json.loads(transport.captured_request.content)


def _captured_headers(transport: _MockTransport) -> dict:
    assert transport.captured_request is not None
    return {k: v for k, v in transport.captured_request.headers.items()}


# ═══════════════════════════════════════════════════════════════════════════
# Entry-point validation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_none_user_id_skips_ledger_write(dlq_path):
    # Stage B transition mode: unattributed calls must succeed without
    # writing to the ledger (rpc_record_usage requires uuid not null).
    # PricingGuard in Stage E will refuse unattributed calls upstream.
    transport = _MockTransport(_fake_anthropic_response())
    supabase = MagicMock()
    async with httpx.AsyncClient(transport=transport) as client:
        result = await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id=None,
            supabase_client=supabase,
            _http_client=client,
        )
    assert result.uvt_consumed > 0           # call still runs + counts tokens
    assert supabase.rpc.call_count == 0      # but no ledger write
    assert not dlq_path.exists()             # and no DLQ write (unattributed != failure)


@pytest.mark.asyncio
async def test_disabled_model_raises(monkeypatch):
    # Temporarily disable haiku
    from lib import model_registry
    spec = model_registry.get("haiku")
    monkeypatch.setitem(
        model_registry.MODELS,
        "haiku",
        model_registry.ModelSpec(**{**spec.__dict__, "enabled": False}),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
        )


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
            await token_accountant.call(
                model="haiku",
                messages=[{"role": "user", "content": "hi"}],
                user_id="u1",
                _http_client=client,
            )


# ═══════════════════════════════════════════════════════════════════════════
# Prompt caching — cache_control applied to system + tools
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_system_prompt_gets_cache_control(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            system="You are an AetherCloud orchestrator.",
            _http_client=client,
        )

    payload = _captured_payload(transport)
    assert isinstance(payload["system"], list)
    assert payload["system"][0]["type"] == "text"
    assert payload["system"][0]["text"] == "You are an AetherCloud orchestrator."
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_string_system_without_caching_kept_as_string_when_unsupported(monkeypatch, dlq_path):
    # Flip haiku to not support caching; system must revert to plain string.
    from lib import model_registry
    spec = model_registry.get("haiku")
    monkeypatch.setitem(
        model_registry.MODELS,
        "haiku",
        model_registry.ModelSpec(**{**spec.__dict__, "supports_prompt_caching": False}),
    )
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            system="plain string",
            _http_client=client,
        )
    payload = _captured_payload(transport)
    assert payload["system"] == "plain string"


@pytest.mark.asyncio
async def test_tools_last_block_gets_cache_control(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    tools = [
        {"name": "search", "input_schema": {"type": "object"}},
        {"name": "read_file", "input_schema": {"type": "object"}},
    ]
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="sonnet",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            tools=tools,
            _http_client=client,
        )
    payload = _captured_payload(transport)
    # First tool untouched; last tool carries the cache breakpoint.
    assert "cache_control" not in payload["tools"][0]
    assert payload["tools"][1]["cache_control"] == {"type": "ephemeral"}
    # Original caller list not mutated
    assert "cache_control" not in tools[1]


@pytest.mark.asyncio
async def test_cache_beta_header_always_set(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            _http_client=client,
        )
    headers = _captured_headers(transport)
    assert "prompt-caching-2024-07-31" in headers["anthropic-beta"]


@pytest.mark.asyncio
async def test_mcp_beta_header_only_when_mcp_servers_passed(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            mcp_servers=[{"type": "url", "url": "https://mcp.example.com"}],
            _http_client=client,
        )
    headers = _captured_headers(transport)
    assert "mcp-client-2025-04-04" in headers["anthropic-beta"]
    payload = _captured_payload(transport)
    assert payload["mcp_servers"] == [{"type": "url", "url": "https://mcp.example.com"}]


# ═══════════════════════════════════════════════════════════════════════════
# Usage accounting — UVT + cost + ledger call parameters
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_response_envelope_has_correct_accounting(dlq_path):
    transport = _MockTransport(_fake_anthropic_response(
        text="hello",
        input_tokens=1000,
        output_tokens=500,
        cached_input=200,
    ))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await token_accountant.call(
            model="sonnet",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            _http_client=client,
        )
    # UVT = (1000 - 200) + 500 = 1300
    assert result.uvt_consumed == 1300
    # Cost: (800 × 300 + 200 × 300 × 0.1 + 500 × 1500) / 1M cents
    #     =  0.24 +           0.006      +   0.75
    #     =  0.996¢ — verify via the same formula in registry.
    from lib import model_registry
    expected = model_registry.cost_usd_cents("sonnet", 1000, 500, 200)
    assert result.cost_usd_cents == pytest.approx(expected)
    assert result.text == "hello"
    assert result.input_tokens == 1000
    assert result.output_tokens == 500
    assert result.cached_input_tokens == 200
    assert result.model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_rpc_record_usage_called_with_exact_param_names(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    supabase = MagicMock()
    rpc_builder = MagicMock()
    rpc_builder.execute.return_value = MagicMock(error=None)
    supabase.rpc.return_value = rpc_builder

    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="11111111-1111-1111-1111-111111111111",
            task_id="22222222-2222-2222-2222-222222222222",
            qopc_load="medium",
            supabase_client=supabase,
            _http_client=client,
        )

    assert supabase.rpc.call_count == 1
    fname, params = supabase.rpc.call_args.args
    assert fname == "rpc_record_usage"
    # Param names must match the SQL function signature exactly.
    assert set(params.keys()) == {
        "p_user_id", "p_task_id", "p_model", "p_input_tokens",
        "p_output_tokens", "p_cached_input_tokens",
        "p_cost_usd_cents_fractional", "p_qopc_load",
        "p_reasoning_tokens", "p_cache_write_tokens",
    }
    assert params["p_user_id"] == "11111111-1111-1111-1111-111111111111"
    assert params["p_task_id"] == "22222222-2222-2222-2222-222222222222"
    assert params["p_model"] == "haiku"
    assert params["p_qopc_load"] == "medium"
    assert params["p_input_tokens"] == 1000
    assert params["p_output_tokens"] == 500


@pytest.mark.asyncio
async def test_rpc_failure_appends_to_dlq(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    supabase = MagicMock()
    # Simulate rpc_record_usage returning an error
    supabase.rpc.return_value.execute.return_value = MagicMock(error="boom")

    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            supabase_client=supabase,
            _http_client=client,
        )

    # DLQ must contain one line with our event
    assert dlq_path.exists(), "DLQ file should have been created"
    lines = dlq_path.read_text().strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["user_id"] == "u1"
    assert event["model"] == "haiku"


@pytest.mark.asyncio
async def test_no_supabase_client_writes_to_dlq(dlq_path, caplog):
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            supabase_client=None,
            _http_client=client,
        )
    lines = dlq_path.read_text().strip().splitlines()
    assert len(lines) == 1


@pytest.mark.asyncio
async def test_tool_uses_surfaced_on_envelope(dlq_path):
    tool_use_block = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "search",
        "input": {"query": "aether"},
    }
    transport = _MockTransport(_fake_anthropic_response(tool_uses=[tool_use_block]))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await token_accountant.call(
            model="sonnet",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            tools=[{"name": "search", "input_schema": {"type": "object"}}],
            _http_client=client,
        )
    assert len(result.tool_uses) == 1
    assert result.tool_uses[0]["name"] == "search"


# ═══════════════════════════════════════════════════════════════════════════
# API key is read from env — never passed in
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_x_api_key_header_comes_from_env(dlq_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-NEW-VALUE")
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            _http_client=client,
        )
    headers = _captured_headers(transport)
    assert headers["x-api-key"] == "sk-ant-NEW-VALUE"


@pytest.mark.asyncio
async def test_correct_model_id_sent_to_anthropic(dlq_path):
    transport = _MockTransport(_fake_anthropic_response())
    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="opus",
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            _http_client=client,
        )
    payload = _captured_payload(transport)
    # Must send the literal Anthropic model_id, not our registry key.
    assert payload["model"] == "claude-opus-4-7"


# ═══════════════════════════════════════════════════════════════════════════
# Red Team #2 H3 — DLQ size gauge + threshold alert
# ═══════════════════════════════════════════════════════════════════════════


def test_dlq_gauge_emits_size_on_every_enqueue(dlq_path, caplog):
    """Every DLQ append should log a `dlq.size_gauge` record with the
    current line count."""
    import logging
    caplog.set_level(logging.INFO, logger="aethercloud.token_accountant")
    for i in range(3):
        token_accountant._append_to_dlq({"user_id": f"u{i}", "model": "haiku"})

    gauge_records = [
        r for r in caplog.records
        if getattr(r, "event", None) == "dlq.size_gauge"
    ]
    assert len(gauge_records) == 3
    # Line count must increase monotonically across the 3 appends.
    assert [getattr(r, "dlq_line_count", None) for r in gauge_records] == [1, 2, 3]


def test_dlq_threshold_fires_critical_tag(dlq_path, caplog, monkeypatch):
    """Red Team #2 H3: once DLQ crosses AETHER_DLQ_ALERT_THRESHOLD, the
    accountant emits a CRITICAL log tagged DLQ_OVER_THRESHOLD so ops can
    grep journalctl and Prometheus can alert on log_messages_total."""
    import logging
    monkeypatch.setenv("AETHER_DLQ_ALERT_THRESHOLD", "3")
    caplog.set_level(logging.CRITICAL, logger="aethercloud.token_accountant")

    # Two appends — under threshold, no CRITICAL.
    for i in range(2):
        token_accountant._append_to_dlq({"user_id": f"u{i}", "model": "haiku"})
    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 0

    # Third append → crosses threshold, CRITICAL fires.
    token_accountant._append_to_dlq({"user_id": "u2", "model": "haiku"})
    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 1
    assert "DLQ_OVER_THRESHOLD" in criticals[0].getMessage()


def test_dlq_threshold_defaults_to_fifty(dlq_path, caplog, monkeypatch):
    """If AETHER_DLQ_ALERT_THRESHOLD isn't set, the default is 50."""
    import logging
    monkeypatch.delenv("AETHER_DLQ_ALERT_THRESHOLD", raising=False)
    caplog.set_level(logging.CRITICAL, logger="aethercloud.token_accountant")

    # Seed 49 rows — still under the 50 default.
    for i in range(49):
        token_accountant._append_to_dlq({"user_id": f"u{i}", "model": "haiku"})
    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 0

    # 50th row crosses the default threshold.
    token_accountant._append_to_dlq({"user_id": "u49", "model": "haiku"})
    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1+2 — reasoning/cache_write params, adapter registration,
#              resolve_model_key deepseek branches
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rpc_params_include_reasoning_and_cache_write_values(dlq_path):
    """The new Phase 1 params must pass through to rpc_record_usage with
    correct default values (0 for Anthropic, which doesn't emit them)."""
    transport = _MockTransport(_fake_anthropic_response())
    supabase = MagicMock()
    rpc_builder = MagicMock()
    rpc_builder.execute.return_value = MagicMock(error=None)
    supabase.rpc.return_value = rpc_builder

    async with httpx.AsyncClient(transport=transport) as client:
        await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": "hi"}],
            user_id="11111111-1111-1111-1111-111111111111",
            supabase_client=supabase,
            _http_client=client,
        )

    _, params = supabase.rpc.call_args.args
    # Anthropic adapter sets these to 0
    assert params["p_reasoning_tokens"] == 0
    assert params["p_cache_write_tokens"] == 0


def test_deepseek_adapter_registered():
    """The deepseek adapter must be in the _ADAPTERS dispatch dict."""
    assert "deepseek" in token_accountant._ADAPTERS
    adapter = token_accountant._ADAPTERS["deepseek"]
    assert hasattr(adapter, "build_request")
    assert hasattr(adapter, "parse_usage")
    assert hasattr(adapter, "parse_response")


def test_resolve_model_key_deepseek_flash():
    assert token_accountant.resolve_model_key("dsv4_flash") == "dsv4_flash"
    assert token_accountant.resolve_model_key("deepseek-v4-flash") == "dsv4_flash"


def test_resolve_model_key_deepseek_pro():
    assert token_accountant.resolve_model_key("dsv4_pro") == "dsv4_pro"
    assert token_accountant.resolve_model_key("deepseek-v4-pro") == "dsv4_pro"


def test_resolve_model_key_deepseek_reasoner():
    """Legacy deepseek-reasoner alias should map to dsv4_pro."""
    assert token_accountant.resolve_model_key("deepseek-reasoner") == "dsv4_pro"
    assert token_accountant.resolve_model_key("deepseek-chat") == "dsv4_flash"


def test_resolve_model_key_empty_defaults_sonnet():
    assert token_accountant.resolve_model_key("") == "sonnet"
    assert token_accountant.resolve_model_key("unknown-model-xyz") == "sonnet"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1+2 Amendment — OpenAI adapter + resolve_model_key GPT-5 family
# ═══════════════════════════════════════════════════════════════════════════


def test_openai_adapter_registered():
    """The openai adapter must be in the _ADAPTERS dispatch dict."""
    assert "openai" in token_accountant._ADAPTERS
    adapter = token_accountant._ADAPTERS["openai"]
    assert hasattr(adapter, "build_request")
    assert hasattr(adapter, "parse_usage")
    assert hasattr(adapter, "parse_response")


def test_all_three_providers_registered():
    """_ADAPTERS must have exactly anthropic, deepseek, and openai."""
    assert set(token_accountant._ADAPTERS.keys()) == {"anthropic", "deepseek", "openai"}


def test_resolve_model_key_gpt55():
    assert token_accountant.resolve_model_key("gpt-5.5") == "gpt55"
    assert token_accountant.resolve_model_key("gpt55") == "gpt55"


def test_resolve_model_key_gpt54():
    assert token_accountant.resolve_model_key("gpt-5.4") == "gpt54"
    assert token_accountant.resolve_model_key("gpt54") == "gpt54"


def test_resolve_model_key_gpt54_mini():
    assert token_accountant.resolve_model_key("gpt-5.4-mini") == "gpt54_mini"
    assert token_accountant.resolve_model_key("gpt54_mini") == "gpt54_mini"


def test_resolve_model_key_gpt_mini_takes_precedence():
    """Any gpt string with 'mini' in it should resolve to gpt54_mini."""
    assert token_accountant.resolve_model_key("gpt-mini") == "gpt54_mini"


def test_resolve_model_key_gpt_ambiguous_defaults_gpt54():
    """A bare 'gpt' or ambiguous gpt string defaults to mid-tier gpt54."""
    assert token_accountant.resolve_model_key("gpt") == "gpt54"
    assert token_accountant.resolve_model_key("gpt-unknown") == "gpt54"
