"""
DeepSeek V4 provider adapter — Phase 2 of the DeepSeek V4 integration.

Handles:
    - DeepSeek /v1/chat/completions (OpenAI-compatible) URL + auth.
    - Thinking/reasoning parameter for V4-Pro models.
    - Tool format conversion: Anthropic tool schema → OpenAI function-calling.
    - Usage parsing: prompt_tokens, prompt_cache_hit_tokens,
      completion_tokens, completion_tokens_details.reasoning_tokens.
    - Response parsing: message.content (text), message.tool_calls,
      finish_reason mapping.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import os
from typing import Any, Optional

from lib import model_registry
from lib.providers import UsageBreakdown


# ─── Constants ───────────────────────────────────────────────────────────
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


# ─── API key ─────────────────────────────────────────────────────────────

def _api_key() -> str:
    """Read DEEPSEEK_API_KEY at call time — same rotation pattern as Anthropic."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not set. TokenAccountant cannot call DeepSeek without it. "
            "Set in /etc/aethercloud/.env on VPS2."
        )
    return key


# ─── Tool format conversion ─────────────────────────────────────────────

def _normalize_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-format tool schemas to OpenAI function-calling format.

    Anthropic format:
        {"name": "search", "description": "...", "input_schema": {...}}

    OpenAI format:
        {"type": "function", "function": {"name": "search", "description": "...", "parameters": {...}}}

    If the tool already has a "type": "function" key, it's passed through as-is.
    """
    converted: list[dict] = []
    for tool in tools:
        if tool.get("type") == "function":
            # Already in OpenAI format
            converted.append(tool)
            continue
        fn_def: dict[str, Any] = {"name": tool["name"]}
        if "description" in tool:
            fn_def["description"] = tool["description"]
        # Anthropic uses input_schema; OpenAI uses parameters
        if "input_schema" in tool:
            fn_def["parameters"] = tool["input_schema"]
        elif "parameters" in tool:
            fn_def["parameters"] = tool["parameters"]
        converted.append({"type": "function", "function": fn_def})
    return converted


# ─── Request building ────────────────────────────────────────────────────

def build_request(
    spec: model_registry.ModelSpec,
    messages: list[dict],
    system: Optional[str],
    tools: Optional[list[dict]],
    max_tokens: int,
    *,
    mcp_servers: Optional[list[dict]] = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the DeepSeek /v1/chat/completions request.

    Returns (url, headers, payload) ready for httpx.post().
    """
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": spec.model_id,
        "max_tokens": max_tokens,
        "messages": _build_messages(messages, system),
        "stream": False,
    }

    # DeepSeek V4-Pro reports reasoning_tokens automatically based on model_id;
    # no request-side enable flag (unlike Anthropic's "thinking" parameter).
    # spec.reports_reasoning_tokens drives downstream usage parsing only.

    if tools:
        payload["tools"] = _normalize_tools(tools)

    return DEEPSEEK_URL, headers, payload


def _build_messages(
    messages: list[dict],
    system: Optional[str],
) -> list[dict]:
    """Prepend system message if provided — OpenAI format uses a
    {"role": "system", "content": "..."} message at index 0."""
    result: list[dict] = []
    if system:
        # Handle Anthropic's cache_control system format (list of blocks)
        if isinstance(system, list):
            # Extract text from Anthropic's [{type: text, text: ..., cache_control: ...}]
            text = " ".join(
                block.get("text", "") for block in system if isinstance(block, dict)
            ).strip()
            if text:
                result.append({"role": "system", "content": text})
        else:
            result.append({"role": "system", "content": system})
    result.extend(messages)
    return result


# ─── Usage parsing ───────────────────────────────────────────────────────

def parse_usage(data: dict[str, Any]) -> UsageBreakdown:
    """Extract standardized usage from a DeepSeek response.

    DeepSeek usage shape:
        {
          "usage": {
            "prompt_tokens": 1200,
            "prompt_cache_hit_tokens": 800,
            "completion_tokens": 500,          # includes reasoning
            "completion_tokens_details": {
              "reasoning_tokens": 200
            }
          }
        }

    Mapping:
        prompt_tokens           → input_tokens
        prompt_cache_hit_tokens → cached_input_tokens
        completion_tokens       → output_tokens (billed in full, includes reasoning)
        completion_tokens_details.reasoning_tokens → reasoning_tokens (surfaced, not extra-billed)
    """
    usage = data.get("usage", {}) or {}
    details = usage.get("completion_tokens_details", {}) or {}
    return UsageBreakdown(
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        cached_input_tokens=int(usage.get("prompt_cache_hit_tokens", 0)),
        reasoning_tokens=int(details.get("reasoning_tokens", 0)),
        cache_write_tokens=0,  # DeepSeek doesn't report cache writes separately
    )


# ─── Response parsing ────────────────────────────────────────────────────

_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filter",
}


def _map_finish_reason(reason: str | None) -> str:
    """Map OpenAI finish_reason to Anthropic-style stop_reason for uniform
    handling in the router/tool loop."""
    if not reason:
        return ""
    return _FINISH_REASON_MAP.get(reason, reason)


def parse_response(data: dict[str, Any]) -> dict[str, Any]:
    """Extract text, tool_uses, and stop_reason from a DeepSeek response.

    Converts OpenAI tool_calls format to Anthropic tool_use format so
    the router's tool loop works unchanged.
    """
    choices = data.get("choices", [])
    if not choices:
        return {"text": "", "tool_uses": [], "stop_reason": ""}

    choice = choices[0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "")

    # Text content
    text = (message.get("content") or "").strip()

    # Tool calls → Anthropic tool_use format
    tool_uses: list[dict] = []
    for tc in message.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        tool_use: dict[str, Any] = {
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "input": _parse_arguments(fn.get("arguments", "{}")),
        }
        tool_uses.append(tool_use)

    return {
        "text": text,
        "tool_uses": tool_uses,
        "stop_reason": _map_finish_reason(finish_reason),
    }


def _parse_arguments(args: str | dict) -> dict:
    """Parse tool call arguments — DeepSeek sends them as a JSON string."""
    if isinstance(args, dict):
        return args
    try:
        import json
        return json.loads(args)
    except (json.JSONDecodeError, TypeError):
        return {}
