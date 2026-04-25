"""
Tests for lib/providers/anthropic.py — the Anthropic adapter extracted
from lib/token_accountant.py in Phase 0 (issue #82).

Covers:
- _build_payload byte-identical snapshot tests (5 fixtures)
- parse_usage extracts the right fields from Anthropic's usage block
- parse_response extracts text, tool_uses, and stop_reason
- build_request wires URL, headers, and payload together
- API key read from env

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.providers import UsageBreakdown
from lib.providers import anthropic as adapter
from lib import model_registry


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")


def _load_snapshot(name: str) -> dict:
    path = SNAPSHOT_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════
# Snapshot tests — _build_payload must produce byte-identical output
# to the pre-refactor version for all 5 representative inputs.
# ═══════════════════════════════════════════════════════════════════════════

_MSGS = [{"role": "user", "content": "hi"}]
_SYSTEM = "You are an AetherCloud orchestrator."
_TOOLS = [
    {"name": "search", "input_schema": {"type": "object"}},
    {"name": "read_file", "input_schema": {"type": "object"}},
]


def _normalize(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, indent=2)


def test_build_payload_byte_identical_system_only():
    haiku = model_registry.get("haiku")
    result = adapter._build_payload(haiku, _MSGS, _SYSTEM, None, 2048)
    expected = _load_snapshot("payload_system_only.json")
    assert _normalize(result) == _normalize(expected)


def test_build_payload_byte_identical_system_and_tools():
    sonnet = model_registry.get("sonnet")
    result = adapter._build_payload(sonnet, _MSGS, _SYSTEM, _TOOLS, 4096)
    expected = _load_snapshot("payload_system_and_tools.json")
    assert _normalize(result) == _normalize(expected)


def test_build_payload_byte_identical_tools_only():
    sonnet = model_registry.get("sonnet")
    result = adapter._build_payload(sonnet, _MSGS, None, _TOOLS, 2048)
    expected = _load_snapshot("payload_tools_only.json")
    assert _normalize(result) == _normalize(expected)


def test_build_payload_byte_identical_no_system_no_tools():
    haiku = model_registry.get("haiku")
    result = adapter._build_payload(haiku, _MSGS, None, None, 1024)
    expected = _load_snapshot("payload_no_system_no_tools.json")
    assert _normalize(result) == _normalize(expected)


def test_build_payload_byte_identical_mcp_enabled():
    haiku = model_registry.get("haiku")
    result = adapter._build_payload(haiku, _MSGS, _SYSTEM, _TOOLS, 2048)
    result["mcp_servers"] = [{"type": "url", "url": "https://mcp.example.com"}]
    expected = _load_snapshot("payload_mcp_enabled.json")
    assert _normalize(result) == _normalize(expected)


# ═══════════════════════════════════════════════════════════════════════════
# parse_usage — standardized extraction from Anthropic response shape
# ═══════════════════════════════════════════════════════════════════════════


def test_parse_usage_extracts_all_fields():
    data = {
        "usage": {
            "input_tokens": 1247,
            "output_tokens": 500,
            "cache_read_input_tokens": 800,
        }
    }
    usage = adapter.parse_usage(data)
    assert usage == UsageBreakdown(
        input_tokens=1247,
        output_tokens=500,
        cached_input_tokens=800,
        reasoning_tokens=0,
        cache_write_tokens=0,
    )


def test_parse_usage_handles_missing_usage_block():
    usage = adapter.parse_usage({})
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cached_input_tokens == 0


def test_parse_usage_handles_none_usage():
    usage = adapter.parse_usage({"usage": None})
    assert usage.input_tokens == 0


# ═══════════════════════════════════════════════════════════════════════════
# parse_response — text, tool_uses, stop_reason
# ═══════════════════════════════════════════════════════════════════════════


def test_parse_response_extracts_text():
    data = {
        "content": [{"type": "text", "text": "  hello world  "}],
        "stop_reason": "end_turn",
    }
    parsed = adapter.parse_response(data)
    assert parsed["text"] == "hello world"
    assert parsed["stop_reason"] == "end_turn"
    assert parsed["tool_uses"] == []


def test_parse_response_extracts_tool_uses():
    tool_block = {"type": "tool_use", "id": "t1", "name": "search", "input": {}}
    data = {
        "content": [
            {"type": "text", "text": "searching..."},
            tool_block,
        ],
        "stop_reason": "tool_use",
    }
    parsed = adapter.parse_response(data)
    assert len(parsed["tool_uses"]) == 1
    assert parsed["tool_uses"][0]["name"] == "search"
    assert parsed["text"] == "searching..."


def test_parse_response_handles_empty_content():
    parsed = adapter.parse_response({"content": [], "stop_reason": ""})
    assert parsed["text"] == ""
    assert parsed["tool_uses"] == []
    assert parsed["stop_reason"] == ""


# ═══════════════════════════════════════════════════════════════════════════
# build_request — wires URL, headers, payload
# ═══════════════════════════════════════════════════════════════════════════


def test_build_request_returns_anthropic_url():
    spec = model_registry.get("haiku")
    url, headers, payload = adapter.build_request(
        spec, _MSGS, _SYSTEM, None, 2048,
    )
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-ant-test-fake"
    assert "prompt-caching-2024-07-31" in headers["anthropic-beta"]
    assert payload["model"] == "claude-haiku-4-5-20251001"


def test_build_request_mcp_header_when_mcp_servers():
    spec = model_registry.get("haiku")
    url, headers, payload = adapter.build_request(
        spec, _MSGS, None, None, 2048,
        mcp_servers=[{"type": "url", "url": "https://mcp.example.com"}],
    )
    assert "mcp-client-2025-04-04" in headers["anthropic-beta"]
    assert payload["mcp_servers"] == [{"type": "url", "url": "https://mcp.example.com"}]


def test_build_request_no_mcp_header_without_mcp_servers():
    spec = model_registry.get("haiku")
    _, headers, _ = adapter.build_request(spec, _MSGS, None, None, 2048)
    assert "mcp-client-2025-04-04" not in headers["anthropic-beta"]


def test_build_request_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = model_registry.get("haiku")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        adapter.build_request(spec, _MSGS, None, None, 2048)


# ═══════════════════════════════════════════════════════════════════════════
# Tool mutation safety — original list must not be modified
# ═══════════════════════════════════════════════════════════════════════════


def test_build_payload_does_not_mutate_caller_tools():
    sonnet = model_registry.get("sonnet")
    tools = [
        {"name": "a", "input_schema": {"type": "object"}},
        {"name": "b", "input_schema": {"type": "object"}},
    ]
    adapter._build_payload(sonnet, _MSGS, None, tools, 2048)
    assert "cache_control" not in tools[0]
    assert "cache_control" not in tools[1]
