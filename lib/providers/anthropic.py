"""
Anthropic provider adapter — extracted verbatim from lib/token_accountant.py
during Phase 0 of the DeepSeek V4 integration (issue #82).

Handles:
    - Anthropic /v1/messages URL, headers (x-api-key, anthropic-version,
      anthropic-beta), and prompt-caching (cache_control: ephemeral).
    - Usage parsing: input_tokens, output_tokens, cache_read_input_tokens.
    - Response parsing: text blocks, tool_use blocks, stop_reason.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import copy
import os
from typing import Any, Optional

from lib import model_registry
from lib.providers import UsageBreakdown

# ─── Constants (moved verbatim from token_accountant.py) ──────────────────
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_CACHE_BETA = "prompt-caching-2024-07-31"
_ANTHROPIC_MCP_BETA = "mcp-client-2025-04-04"


# ─── API key ──────────────────────────────────────────────────────────────

def _api_key() -> str:
    """Read ANTHROPIC_API_KEY at call time so hot-rotation via
    /etc/aethercloud/.env + systemctl restart picks up new values."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. TokenAccountant cannot call Anthropic without it. "
            "Set in /etc/aethercloud/.env on VPS2."
        )
    return key


# ─── Request building ─────────────────────────────────────────────────────

def build_request(
    spec: model_registry.ModelSpec,
    messages: list[dict],
    system: Optional[str],
    tools: Optional[list[dict]],
    max_tokens: int,
    *,
    mcp_servers: Optional[list[dict]] = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the Anthropic /v1/messages request.

    Returns (url, headers, payload) ready for httpx.post().
    """
    payload = _build_payload(spec, messages, system, tools, max_tokens)
    headers = _build_headers(api_key=_api_key(), has_mcp=bool(mcp_servers))
    if mcp_servers:
        payload["mcp_servers"] = mcp_servers
    return _ANTHROPIC_URL, headers, payload


def _build_payload(
    spec: model_registry.ModelSpec,
    messages: list[dict],
    system: Optional[str],
    tools: Optional[list[dict]],
    max_tokens: int,
) -> dict[str, Any]:
    """Constructs the /v1/messages body with prompt caching applied to stable
    prompts (system, tool schemas). User messages are never cached."""
    payload: dict[str, Any] = {
        "model": spec.model_id,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    if system and spec.supports_prompt_caching:
        payload["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    elif system:
        payload["system"] = system

    if tools:
        if spec.supports_prompt_caching:
            cached_tools = [copy.deepcopy(t) for t in tools]
            if cached_tools:
                cached_tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = cached_tools
        else:
            payload["tools"] = tools

    return payload


def _build_headers(*, api_key: str, has_mcp: bool) -> dict[str, str]:
    betas: list[str] = [_ANTHROPIC_CACHE_BETA]
    if has_mcp:
        betas.append(_ANTHROPIC_MCP_BETA)
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "anthropic-beta": ",".join(betas),
        "content-type": "application/json",
    }


# ─── Usage parsing ────────────────────────────────────────────────────────

def parse_usage(data: dict[str, Any]) -> UsageBreakdown:
    """Extract standardized usage from an Anthropic response."""
    usage = data.get("usage", {}) or {}
    return UsageBreakdown(
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cached_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
        reasoning_tokens=0,
        cache_write_tokens=0,
    )


# ─── Response parsing ─────────────────────────────────────────────────────

def parse_response(data: dict[str, Any]) -> dict[str, Any]:
    """Extract text, tool_uses, and stop_reason from an Anthropic response."""
    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()
    tool_uses = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
    return {
        "text": text,
        "tool_uses": tool_uses,
        "stop_reason": data.get("stop_reason", ""),
    }
