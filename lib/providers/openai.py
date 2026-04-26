"""
OpenAI GPT-5 provider adapter — Phase 1+2 Amendment.

Handles:
    - OpenAI /v1/chat/completions URL + auth.
    - Tool format conversion: Anthropic tool schema -> OpenAI function-calling.
    - Usage parsing: prompt_tokens, prompt_tokens_details.cached_tokens,
      completion_tokens, completion_tokens_details.reasoning_tokens.
    - Response parsing: message.content (text), message.tool_calls,
      finish_reason mapping.

Mirrors the DeepSeek adapter structure. Both providers expose an
OpenAI-compatible API surface; the only differences are:
    - Auth header (Bearer token from OPENAI_API_KEY)
    - Usage field paths (prompt_tokens_details.cached_tokens vs
      prompt_cache_hit_tokens)
    - No cache_write_tokens reporting

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import os
from typing import Any, Optional

from lib import model_registry
from lib.providers import UsageBreakdown


# --- Constants ---------------------------------------------------------------
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


# --- API key -----------------------------------------------------------------

def _api_key() -> str:
    """Read OPENAI_API_KEY at call time — same rotation pattern as Anthropic."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. TokenAccountant cannot call OpenAI without it. "
            "Set in /etc/aethercloud/.env on VPS2."
        )
    return key


# --- Tool format conversion --------------------------------------------------

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


# --- Request building --------------------------------------------------------

def build_request(
    spec: model_registry.ModelSpec,
    messages: list[dict],
    system: Optional[str],
    tools: Optional[list[dict]],
    max_tokens: int,
    *,
    mcp_servers: Optional[list[dict]] = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the OpenAI /v1/chat/completions request.

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

    # GPT-5 family does not surface reasoning_tokens and has no
    # request-side thinking enable flag. spec.reports_reasoning_tokens=False
    # drives downstream usage parsing only.

    if tools:
        payload["tools"] = _normalize_tools(tools)

    return OPENAI_URL, headers, payload


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


# --- Usage parsing -----------------------------------------------------------

def parse_usage(data: dict[str, Any]) -> UsageBreakdown:
    """Extract standardized usage from an OpenAI response.

    OpenAI usage shape:
        {
          "usage": {
            "prompt_tokens": 1200,
            "prompt_tokens_details": {
              "cached_tokens": 800
            },
            "completion_tokens": 500,
            "completion_tokens_details": {
              "reasoning_tokens": 0
            }
          }
        }

    Mapping:
        prompt_tokens                            -> input_tokens
        prompt_tokens_details.cached_tokens      -> cached_input_tokens
        completion_tokens                        -> output_tokens
        completion_tokens_details.reasoning_tokens -> reasoning_tokens
    """
    usage = data.get("usage", {}) or {}
    prompt_details = usage.get("prompt_tokens_details", {}) or {}
    completion_details = usage.get("completion_tokens_details", {}) or {}
    return UsageBreakdown(
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
        cached_input_tokens=int(prompt_details.get("cached_tokens", 0)),
        reasoning_tokens=int(completion_details.get("reasoning_tokens", 0)),
        cache_write_tokens=0,  # OpenAI doesn't report cache writes separately
    )


# --- Response parsing --------------------------------------------------------

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
    """Extract text, tool_uses, and stop_reason from an OpenAI response.

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

    # Tool calls -> Anthropic tool_use format
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
    """Parse tool call arguments — OpenAI sends them as a JSON string."""
    if isinstance(args, dict):
        return args
    try:
        import json
        return json.loads(args)
    except (json.JSONDecodeError, TypeError):
        return {}
