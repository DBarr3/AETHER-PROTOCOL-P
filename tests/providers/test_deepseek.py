"""
Tests for lib/providers/deepseek.py — the DeepSeek V4 adapter (Phase 2).

Covers:
- build_request: URL, headers, payload shape, thinking param, tool conversion
- _normalize_tools: Anthropic → OpenAI format conversion
- _build_messages: system prompt prepending
- parse_usage: DeepSeek usage block → UsageBreakdown
- parse_response: choices → text, tool_uses, stop_reason
- _map_finish_reason: OpenAI → Anthropic stop_reason mapping
- _parse_arguments: JSON string → dict
- API key read from env

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import json

import pytest

from lib.providers import UsageBreakdown
from lib.providers import deepseek as adapter
from lib import model_registry


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test-fake")


_MSGS = [{"role": "user", "content": "hi"}]
_SYSTEM = "You are an AetherCloud orchestrator."
_TOOLS_ANTHROPIC = [
    {"name": "search", "description": "Search the web", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "read_file", "input_schema": {"type": "object"}},
]


def _fake_deepseek_response(
    text: str = "hello",
    prompt_tokens: int = 1200,
    completion_tokens: int = 500,
    cache_hit_tokens: int = 0,
    reasoning_tokens: int = 0,
    tool_calls: list | None = None,
    finish_reason: str = "stop",
) -> dict:
    message: dict = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_cache_hit_tokens": cache_hit_tokens,
            "completion_tokens_details": {
                "reasoning_tokens": reasoning_tokens,
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# _normalize_tools — Anthropic → OpenAI format
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalizeTools:

    def test_converts_anthropic_to_openai_format(self):
        result = adapter._normalize_tools(_TOOLS_ANTHROPIC)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["description"] == "Search the web"
        assert result[0]["function"]["parameters"] == {"type": "object", "properties": {"query": {"type": "string"}}}

    def test_passes_through_openai_format(self):
        openai_tools = [
            {"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}
        ]
        result = adapter._normalize_tools(openai_tools)
        assert result == openai_tools

    def test_handles_tool_without_description(self):
        tools = [{"name": "simple", "input_schema": {"type": "object"}}]
        result = adapter._normalize_tools(tools)
        assert "description" not in result[0]["function"]
        assert result[0]["function"]["name"] == "simple"

    def test_handles_parameters_key_instead_of_input_schema(self):
        tools = [{"name": "alt", "parameters": {"type": "object"}}]
        result = adapter._normalize_tools(tools)
        assert result[0]["function"]["parameters"] == {"type": "object"}

    def test_empty_tools_list(self):
        assert adapter._normalize_tools([]) == []

    def test_mixed_formats(self):
        tools = [
            {"name": "anthropic_tool", "input_schema": {"type": "object"}},
            {"type": "function", "function": {"name": "openai_tool", "parameters": {"type": "object"}}},
        ]
        result = adapter._normalize_tools(tools)
        assert result[0]["function"]["name"] == "anthropic_tool"
        assert result[1]["function"]["name"] == "openai_tool"


# ═══════════════════════════════════════════════════════════════════════════
# _build_messages — system prompt prepending
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildMessages:

    def test_prepends_system_message(self):
        result = adapter._build_messages(_MSGS, "Be helpful.")
        assert len(result) == 2
        assert result[0] == {"role": "system", "content": "Be helpful."}
        assert result[1] == {"role": "user", "content": "hi"}

    def test_no_system_skips_prepend(self):
        result = adapter._build_messages(_MSGS, None)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "hi"}

    def test_anthropic_cache_control_system_format(self):
        """Anthropic sends system as a list of blocks with cache_control.
        DeepSeek adapter must extract the text and flatten."""
        system_blocks = [
            {"type": "text", "text": "You are helpful.", "cache_control": {"type": "ephemeral"}},
        ]
        result = adapter._build_messages(_MSGS, system_blocks)
        assert result[0] == {"role": "system", "content": "You are helpful."}

    def test_empty_string_system_skips_prepend(self):
        result = adapter._build_messages(_MSGS, "")
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════════
# build_request — URL, headers, payload
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildRequest:

    def test_returns_deepseek_url(self):
        spec = model_registry.get("dsv4_flash")
        url, headers, payload = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert url == "https://api.deepseek.com/v1/chat/completions"

    def test_authorization_header(self):
        spec = model_registry.get("dsv4_flash")
        _, headers, _ = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert headers["Authorization"] == "Bearer sk-ds-test-fake"
        assert headers["Content-Type"] == "application/json"

    def test_model_id_in_payload(self):
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert payload["model"] == "deepseek-v4-flash"

    def test_pro_model_id(self):
        spec = model_registry.get("dsv4_pro")
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 4096)
        assert payload["model"] == "deepseek-v4-pro"

    def test_no_thinking_key_for_pro(self):
        """DeepSeek V4-Pro reports reasoning_tokens automatically based on
        model_id — no request-side 'thinking' flag. The old Anthropic-style
        payload['thinking'] was wrong and has been removed."""
        spec = model_registry.get("dsv4_pro")
        assert spec.reports_reasoning_tokens is True
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert "thinking" not in payload

    def test_no_thinking_key_for_flash(self):
        """dsv4_flash also has reports_reasoning_tokens=True but must not
        send a thinking flag on the request."""
        spec = model_registry.get("dsv4_flash")
        assert spec.reports_reasoning_tokens is True
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert "thinking" not in payload

    def test_stream_false(self):
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert payload["stream"] is False

    def test_system_prepended_to_messages(self):
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(spec, _MSGS, _SYSTEM, None, 2048)
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == _SYSTEM

    def test_tools_converted_to_openai_format(self):
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(spec, _MSGS, None, _TOOLS_ANTHROPIC, 2048)
        assert len(payload["tools"]) == 2
        assert payload["tools"][0]["type"] == "function"
        assert payload["tools"][0]["function"]["name"] == "search"

    def test_no_tools_key_when_none(self):
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 2048)
        assert "tools" not in payload

    def test_max_tokens_passed_through(self):
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(spec, _MSGS, None, None, 8192)
        assert payload["max_tokens"] == 8192

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        spec = model_registry.get("dsv4_flash")
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY not set"):
            adapter.build_request(spec, _MSGS, None, None, 2048)

    def test_mcp_servers_ignored(self):
        """DeepSeek doesn't support MCP — mcp_servers param is accepted but ignored."""
        spec = model_registry.get("dsv4_flash")
        _, _, payload = adapter.build_request(
            spec, _MSGS, None, None, 2048,
            mcp_servers=[{"type": "url", "url": "https://mcp.example.com"}],
        )
        assert "mcp_servers" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# parse_usage — DeepSeek usage block → UsageBreakdown
# ═══════════════════════════════════════════════════════════════════════════


class TestParseUsage:

    def test_extracts_all_fields(self):
        data = _fake_deepseek_response(
            prompt_tokens=1200,
            completion_tokens=500,
            cache_hit_tokens=800,
            reasoning_tokens=200,
        )
        usage = adapter.parse_usage(data)
        assert usage == UsageBreakdown(
            input_tokens=1200,
            output_tokens=500,
            cached_input_tokens=800,
            reasoning_tokens=200,
            cache_write_tokens=0,
        )

    def test_handles_missing_usage_block(self):
        usage = adapter.parse_usage({})
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cached_input_tokens == 0
        assert usage.reasoning_tokens == 0

    def test_handles_none_usage(self):
        usage = adapter.parse_usage({"usage": None})
        assert usage.input_tokens == 0

    def test_handles_missing_completion_details(self):
        data = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "prompt_cache_hit_tokens": 0,
            }
        }
        usage = adapter.parse_usage(data)
        assert usage.reasoning_tokens == 0
        assert usage.output_tokens == 50

    def test_handles_none_completion_details(self):
        data = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "prompt_cache_hit_tokens": 0,
                "completion_tokens_details": None,
            }
        }
        usage = adapter.parse_usage(data)
        assert usage.reasoning_tokens == 0

    def test_cache_write_always_zero(self):
        """DeepSeek doesn't report cache writes separately."""
        data = _fake_deepseek_response(cache_hit_tokens=500)
        usage = adapter.parse_usage(data)
        assert usage.cache_write_tokens == 0

    def test_zero_usage(self):
        data = _fake_deepseek_response(
            prompt_tokens=0, completion_tokens=0, cache_hit_tokens=0, reasoning_tokens=0,
        )
        usage = adapter.parse_usage(data)
        assert usage == UsageBreakdown(0, 0, 0, 0, 0)


# ═══════════════════════════════════════════════════════════════════════════
# parse_response — choices → text, tool_uses, stop_reason
# ═══════════════════════════════════════════════════════════════════════════


class TestParseResponse:

    def test_extracts_text(self):
        data = _fake_deepseek_response(text="  hello world  ", finish_reason="stop")
        parsed = adapter.parse_response(data)
        assert parsed["text"] == "hello world"
        assert parsed["stop_reason"] == "end_turn"
        assert parsed["tool_uses"] == []

    def test_extracts_tool_calls(self):
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "search",
                    "arguments": '{"query": "aether"}',
                },
            }
        ]
        data = _fake_deepseek_response(
            text="searching...",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
        )
        parsed = adapter.parse_response(data)
        assert len(parsed["tool_uses"]) == 1
        assert parsed["tool_uses"][0]["type"] == "tool_use"
        assert parsed["tool_uses"][0]["id"] == "call_abc"
        assert parsed["tool_uses"][0]["name"] == "search"
        assert parsed["tool_uses"][0]["input"] == {"query": "aether"}
        assert parsed["stop_reason"] == "tool_use"

    def test_multiple_tool_calls(self):
        tool_calls = [
            {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "b", "arguments": '{"x": 1}'}},
        ]
        data = _fake_deepseek_response(tool_calls=tool_calls, finish_reason="tool_calls")
        parsed = adapter.parse_response(data)
        assert len(parsed["tool_uses"]) == 2
        assert parsed["tool_uses"][0]["name"] == "a"
        assert parsed["tool_uses"][1]["name"] == "b"
        assert parsed["tool_uses"][1]["input"] == {"x": 1}

    def test_handles_empty_choices(self):
        parsed = adapter.parse_response({"choices": []})
        assert parsed["text"] == ""
        assert parsed["tool_uses"] == []
        assert parsed["stop_reason"] == ""

    def test_handles_no_choices_key(self):
        parsed = adapter.parse_response({})
        assert parsed["text"] == ""

    def test_handles_none_content(self):
        data = {
            "choices": [
                {"message": {"content": None}, "finish_reason": "stop"}
            ]
        }
        parsed = adapter.parse_response(data)
        assert parsed["text"] == ""

    def test_handles_none_tool_calls(self):
        data = {
            "choices": [
                {"message": {"content": "hi", "tool_calls": None}, "finish_reason": "stop"}
            ]
        }
        parsed = adapter.parse_response(data)
        assert parsed["tool_uses"] == []


# ═══════════════════════════════════════════════════════════════════════════
# _map_finish_reason — OpenAI → Anthropic stop_reason
# ═══════════════════════════════════════════════════════════════════════════


class TestMapFinishReason:

    @pytest.mark.parametrize("openai,expected", [
        ("stop", "end_turn"),
        ("tool_calls", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "content_filter"),
    ])
    def test_known_mappings(self, openai: str, expected: str):
        assert adapter._map_finish_reason(openai) == expected

    def test_unknown_passed_through(self):
        assert adapter._map_finish_reason("some_new_reason") == "some_new_reason"

    def test_none_returns_empty(self):
        assert adapter._map_finish_reason(None) == ""

    def test_empty_returns_empty(self):
        assert adapter._map_finish_reason("") == ""


# ═══════════════════════════════════════════════════════════════════════════
# _parse_arguments — JSON string → dict
# ═══════════════════════════════════════════════════════════════════════════


class TestParseArguments:

    def test_parses_json_string(self):
        assert adapter._parse_arguments('{"key": "value"}') == {"key": "value"}

    def test_passes_through_dict(self):
        assert adapter._parse_arguments({"key": "value"}) == {"key": "value"}

    def test_invalid_json_returns_empty(self):
        assert adapter._parse_arguments("not json") == {}

    def test_empty_string_returns_empty(self):
        assert adapter._parse_arguments("") == {}

    def test_none_returns_empty(self):
        assert adapter._parse_arguments(None) == {}


# ═══════════════════════════════════════════════════════════════════════════
# DeepSeek pricing in ModelRegistry
# ═══════════════════════════════════════════════════════════════════════════


class TestDeepSeekRegistryEntries:

    def test_dsv4_flash_exists(self):
        spec = model_registry.get("dsv4_flash")
        assert spec.provider == "deepseek"
        assert spec.model_id == "deepseek-v4-flash"

    def test_dsv4_pro_exists(self):
        spec = model_registry.get("dsv4_pro")
        assert spec.provider == "deepseek"
        assert spec.model_id == "deepseek-v4-pro"

    def test_dsv4_flash_pricing(self):
        spec = model_registry.get("dsv4_flash")
        assert spec.input_cents_per_million == 14.0
        assert spec.output_cents_per_million == 28.0
        assert spec.cache_read_cents_per_million == 2.8

    def test_dsv4_pro_pricing(self):
        spec = model_registry.get("dsv4_pro")
        assert spec.input_cents_per_million == 174.0
        assert spec.output_cents_per_million == 348.0
        assert spec.cache_read_cents_per_million == 14.5

    def test_both_report_reasoning_tokens(self):
        assert model_registry.get("dsv4_flash").reports_reasoning_tokens is True
        assert model_registry.get("dsv4_pro").reports_reasoning_tokens is True

    def test_both_jurisdiction_cn(self):
        assert model_registry.get("dsv4_flash").jurisdiction == "cn"
        assert model_registry.get("dsv4_pro").jurisdiction == "cn"

    def test_both_disabled_by_default(self):
        assert model_registry.get("dsv4_flash").enabled is False
        assert model_registry.get("dsv4_pro").enabled is False

    def test_both_support_prompt_caching(self):
        assert model_registry.get("dsv4_flash").supports_prompt_caching is True
        assert model_registry.get("dsv4_pro").supports_prompt_caching is True

    def test_context_window_1m(self):
        assert model_registry.get("dsv4_flash").context_window_tokens == 1_000_000
        assert model_registry.get("dsv4_pro").context_window_tokens == 1_000_000

    def test_cache_write_none_for_deepseek(self):
        """DeepSeek uses automatic prefix caching — no write surcharge."""
        assert model_registry.get("dsv4_flash").cache_write_cents_per_million is None
        assert model_registry.get("dsv4_pro").cache_write_cents_per_million is None

    def test_cost_dsv4_flash_million_input_million_output(self):
        # 1M input × 14¢/M + 1M output × 28¢/M = 42¢
        cost = model_registry.cost_usd_cents("dsv4_flash", 1_000_000, 1_000_000, 0)
        assert cost == pytest.approx(42.0)

    def test_cost_dsv4_pro_million_input_million_output(self):
        # 1M input × 174¢/M + 1M output × 348¢/M = 522¢
        cost = model_registry.cost_usd_cents("dsv4_pro", 1_000_000, 1_000_000, 0)
        assert cost == pytest.approx(522.0)

    def test_cost_dsv4_flash_with_cache(self):
        # 1M input, 800k cached, 200k output
        # miss = 200k × 14/1M = 2.8, hit = 800k × 2.8/1M = 2.24, output = 200k × 28/1M = 5.6
        # total = 10.64
        cost = model_registry.cost_usd_cents("dsv4_flash", 1_000_000, 200_000, 800_000)
        assert cost == pytest.approx(10.64)
