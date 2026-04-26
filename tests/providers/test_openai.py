"""
Tests for lib/providers/openai.py — OpenAI GPT-5 provider adapter.

Covers: build_request, tool conversion, system message handling, parse_usage,
parse_response, finish reasons, API key validation, malformed arguments.

Mirrors test_deepseek.py structure for consistency.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import json
import os

import pytest

from lib import model_registry
from lib.providers import openai as openai_adapter
from lib.providers import UsageBreakdown


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gpt55_spec() -> model_registry.ModelSpec:
    return model_registry.get("gpt55")


@pytest.fixture
def gpt54_spec() -> model_registry.ModelSpec:
    return model_registry.get("gpt54")


@pytest.fixture
def gpt54_mini_spec() -> model_registry.ModelSpec:
    return model_registry.get("gpt54_mini")


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-unit-tests")


SIMPLE_MESSAGES = [{"role": "user", "content": "Hello"}]


OPENAI_TEXT_RESPONSE = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello there!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 50},
        "completion_tokens": 200,
        "completion_tokens_details": {"reasoning_tokens": 0},
    },
}


OPENAI_TOOL_RESPONSE = {
    "id": "chatcmpl-def456",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "search",
                            "arguments": '{"query": "weather"}',
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {
        "prompt_tokens": 300,
        "prompt_tokens_details": {"cached_tokens": 100},
        "completion_tokens": 50,
        "completion_tokens_details": {"reasoning_tokens": 0},
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# Class 1 — build_request basics
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildRequestBasics:
    def test_url_is_openai_endpoint(self, gpt55_spec):
        url, _, _ = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert url == "https://api.openai.com/v1/chat/completions"

    def test_auth_header_uses_bearer_token(self, gpt55_spec):
        _, headers, _ = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert headers["Authorization"] == "Bearer sk-test-key-for-unit-tests"

    def test_content_type_is_json(self, gpt55_spec):
        _, headers, _ = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert headers["Content-Type"] == "application/json"

    def test_payload_model_matches_spec(self, gpt55_spec):
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert payload["model"] == "gpt-5.5"

    def test_payload_model_gpt54(self, gpt54_spec):
        _, _, payload = openai_adapter.build_request(
            gpt54_spec, SIMPLE_MESSAGES, None, None, 2048
        )
        assert payload["model"] == "gpt-5.4"

    def test_payload_model_gpt54_mini(self, gpt54_mini_spec):
        _, _, payload = openai_adapter.build_request(
            gpt54_mini_spec, SIMPLE_MESSAGES, None, None, 2048
        )
        assert payload["model"] == "gpt-5.4-mini"

    def test_max_tokens_threaded(self, gpt55_spec):
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 4096
        )
        assert payload["max_tokens"] == 4096

    def test_stream_is_false(self, gpt55_spec):
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert payload["stream"] is False

    def test_no_thinking_key_for_gpt55(self, gpt55_spec):
        """GPT-5 family has no thinking parameter — never included in payload."""
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert "thinking" not in payload

    def test_no_thinking_key_for_gpt54(self, gpt54_spec):
        _, _, payload = openai_adapter.build_request(
            gpt54_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert "thinking" not in payload

    def test_no_tools_key_when_none(self, gpt55_spec):
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert "tools" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# Class 2 — System message handling
# ═══════════════════════════════════════════════════════════════════════════


class TestSystemMessages:
    def test_system_string_prepended(self, gpt55_spec):
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, "You are helpful.", None, 1024
        )
        assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
        assert payload["messages"][1] == SIMPLE_MESSAGES[0]

    def test_no_system_message_when_none(self, gpt55_spec):
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
        )
        assert payload["messages"] == SIMPLE_MESSAGES

    def test_anthropic_cache_control_system_format(self, gpt55_spec):
        """Anthropic's list-of-blocks system format is converted to a single
        system string for OpenAI."""
        system = [
            {"type": "text", "text": "You are a coding assistant.", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Be concise."},
        ]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, system, None, 1024
        )
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "You are a coding assistant. Be concise."

    def test_empty_system_blocks_skipped(self, gpt55_spec):
        system = [{"type": "text", "text": ""}]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, system, None, 1024
        )
        # Empty text -> no system message prepended
        assert payload["messages"] == SIMPLE_MESSAGES


# ═══════════════════════════════════════════════════════════════════════════
# Class 3 — Tool conversion
# ═══════════════════════════════════════════════════════════════════════════


class TestToolConversion:
    def test_anthropic_tool_converted_to_openai_format(self, gpt55_spec):
        tools = [
            {
                "name": "search",
                "description": "Search the web",
                "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
            }
        ]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, tools, 1024
        )
        assert len(payload["tools"]) == 1
        tool = payload["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "search"
        assert tool["function"]["description"] == "Search the web"
        assert tool["function"]["parameters"] == tools[0]["input_schema"]

    def test_openai_format_passthrough(self, gpt55_spec):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "parameters": {"type": "object"},
                },
            }
        ]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, tools, 1024
        )
        assert payload["tools"] == tools

    def test_tool_without_description(self, gpt55_spec):
        tools = [{"name": "noop", "input_schema": {"type": "object"}}]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, tools, 1024
        )
        fn = payload["tools"][0]["function"]
        assert fn["name"] == "noop"
        assert "description" not in fn

    def test_tool_with_parameters_key(self, gpt55_spec):
        """Tools already using 'parameters' instead of 'input_schema'."""
        tools = [{"name": "calc", "parameters": {"type": "object"}}]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, tools, 1024
        )
        assert payload["tools"][0]["function"]["parameters"] == {"type": "object"}

    def test_multiple_tools_converted(self, gpt55_spec):
        tools = [
            {"name": "a", "input_schema": {"type": "object"}},
            {"name": "b", "input_schema": {"type": "object"}},
            {"name": "c", "input_schema": {"type": "object"}},
        ]
        _, _, payload = openai_adapter.build_request(
            gpt55_spec, SIMPLE_MESSAGES, None, tools, 1024
        )
        assert len(payload["tools"]) == 3
        names = [t["function"]["name"] for t in payload["tools"]]
        assert names == ["a", "b", "c"]


# ═══════════════════════════════════════════════════════════════════════════
# Class 4 — parse_usage
# ═══════════════════════════════════════════════════════════════════════════


class TestParseUsage:
    def test_basic_usage_extraction(self):
        usage = openai_adapter.parse_usage(OPENAI_TEXT_RESPONSE)
        assert isinstance(usage, UsageBreakdown)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 200
        assert usage.cached_input_tokens == 50
        assert usage.reasoning_tokens == 0
        assert usage.cache_write_tokens == 0

    def test_cached_tokens_from_prompt_details(self):
        data = {
            "usage": {
                "prompt_tokens": 5000,
                "prompt_tokens_details": {"cached_tokens": 4000},
                "completion_tokens": 1000,
            }
        }
        usage = openai_adapter.parse_usage(data)
        assert usage.input_tokens == 5000
        assert usage.cached_input_tokens == 4000

    def test_reasoning_tokens_from_completion_details(self):
        data = {
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 300,
                "completion_tokens_details": {"reasoning_tokens": 100},
            }
        }
        usage = openai_adapter.parse_usage(data)
        assert usage.reasoning_tokens == 100

    def test_missing_usage_block(self):
        usage = openai_adapter.parse_usage({})
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cached_input_tokens == 0
        assert usage.reasoning_tokens == 0
        assert usage.cache_write_tokens == 0

    def test_null_usage_block(self):
        usage = openai_adapter.parse_usage({"usage": None})
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_missing_prompt_details(self):
        data = {
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 200,
            }
        }
        usage = openai_adapter.parse_usage(data)
        assert usage.cached_input_tokens == 0

    def test_null_prompt_details(self):
        data = {
            "usage": {
                "prompt_tokens": 500,
                "prompt_tokens_details": None,
                "completion_tokens": 200,
            }
        }
        usage = openai_adapter.parse_usage(data)
        assert usage.cached_input_tokens == 0

    def test_missing_completion_details(self):
        data = {
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 200,
            }
        }
        usage = openai_adapter.parse_usage(data)
        assert usage.reasoning_tokens == 0

    def test_null_completion_details(self):
        data = {
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 200,
                "completion_tokens_details": None,
            }
        }
        usage = openai_adapter.parse_usage(data)
        assert usage.reasoning_tokens == 0

    def test_cache_write_tokens_always_zero(self):
        """OpenAI doesn't report cache writes — always 0."""
        usage = openai_adapter.parse_usage(OPENAI_TEXT_RESPONSE)
        assert usage.cache_write_tokens == 0


# ═══════════════════════════════════════════════════════════════════════════
# Class 5 — parse_response text
# ═══════════════════════════════════════════════════════════════════════════


class TestParseResponseText:
    def test_text_extraction(self):
        parsed = openai_adapter.parse_response(OPENAI_TEXT_RESPONSE)
        assert parsed["text"] == "Hello there!"

    def test_empty_choices(self):
        parsed = openai_adapter.parse_response({"choices": []})
        assert parsed["text"] == ""
        assert parsed["tool_uses"] == []
        assert parsed["stop_reason"] == ""

    def test_no_choices_key(self):
        parsed = openai_adapter.parse_response({})
        assert parsed["text"] == ""

    def test_null_content_returns_empty(self):
        data = {
            "choices": [
                {"message": {"content": None}, "finish_reason": "stop"}
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["text"] == ""

    def test_whitespace_stripped(self):
        data = {
            "choices": [
                {"message": {"content": "  hello  "}, "finish_reason": "stop"}
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["text"] == "hello"


# ═══════════════════════════════════════════════════════════════════════════
# Class 6 — parse_response tool calls
# ═══════════════════════════════════════════════════════════════════════════


class TestParseResponseToolCalls:
    def test_tool_calls_converted_to_anthropic_format(self):
        parsed = openai_adapter.parse_response(OPENAI_TOOL_RESPONSE)
        assert len(parsed["tool_uses"]) == 1
        tu = parsed["tool_uses"][0]
        assert tu["type"] == "tool_use"
        assert tu["id"] == "call_abc123"
        assert tu["name"] == "search"
        assert tu["input"] == {"query": "weather"}

    def test_multiple_tool_calls(self):
        data = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "a", "arguments": "{}"},
                            },
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": "b", "arguments": '{"x":1}'},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert len(parsed["tool_uses"]) == 2
        assert parsed["tool_uses"][0]["name"] == "a"
        assert parsed["tool_uses"][1]["name"] == "b"
        assert parsed["tool_uses"][1]["input"] == {"x": 1}

    def test_no_tool_calls_key(self):
        data = {
            "choices": [
                {"message": {"content": "just text"}, "finish_reason": "stop"}
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["tool_uses"] == []

    def test_null_tool_calls(self):
        data = {
            "choices": [
                {"message": {"content": "text", "tool_calls": None}, "finish_reason": "stop"}
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["tool_uses"] == []

    def test_malformed_json_arguments(self):
        data = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "function": {"name": "broken", "arguments": "not valid json"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["tool_uses"][0]["input"] == {}

    def test_dict_arguments_passthrough(self):
        data = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_dict",
                                "function": {"name": "fn", "arguments": {"already": "parsed"}},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["tool_uses"][0]["input"] == {"already": "parsed"}


# ═══════════════════════════════════════════════════════════════════════════
# Class 7 — Finish reason mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestFinishReasonMapping:
    def test_stop_maps_to_end_turn(self):
        parsed = openai_adapter.parse_response(OPENAI_TEXT_RESPONSE)
        assert parsed["stop_reason"] == "end_turn"

    def test_tool_calls_maps_to_tool_use(self):
        parsed = openai_adapter.parse_response(OPENAI_TOOL_RESPONSE)
        assert parsed["stop_reason"] == "tool_use"

    def test_length_maps_to_max_tokens(self):
        data = {
            "choices": [{"message": {"content": "..."}, "finish_reason": "length"}]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["stop_reason"] == "max_tokens"

    def test_content_filter_maps_to_content_filter(self):
        data = {
            "choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["stop_reason"] == "content_filter"

    def test_unknown_reason_passed_through(self):
        data = {
            "choices": [{"message": {"content": ""}, "finish_reason": "custom_reason"}]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["stop_reason"] == "custom_reason"

    def test_none_reason_returns_empty(self):
        data = {
            "choices": [{"message": {"content": ""}, "finish_reason": None}]
        }
        parsed = openai_adapter.parse_response(data)
        assert parsed["stop_reason"] == ""

    def test_missing_reason_returns_empty(self):
        data = {"choices": [{"message": {"content": ""}}]}
        parsed = openai_adapter.parse_response(data)
        assert parsed["stop_reason"] == ""


# ═══════════════════════════════════════════════════════════════════════════
# Class 8 — API key validation
# ═══════════════════════════════════════════════════════════════════════════


class TestApiKeyValidation:
    def test_missing_api_key_raises(self, monkeypatch, gpt55_spec):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
            openai_adapter.build_request(
                gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
            )

    def test_empty_api_key_raises(self, monkeypatch, gpt55_spec):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY not set"):
            openai_adapter.build_request(
                gpt55_spec, SIMPLE_MESSAGES, None, None, 1024
            )
