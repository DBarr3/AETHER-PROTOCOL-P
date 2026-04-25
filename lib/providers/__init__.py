"""
Provider adapters for TokenAccountant multi-provider dispatch.

Each adapter exposes three functions:
    build_request(spec, messages, system, tools, max_tokens, **kw)
        -> (url, headers, payload)
    parse_usage(response_json) -> UsageBreakdown
    parse_response(response_json) -> dict

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from lib import model_registry


@dataclass(frozen=True)
class UsageBreakdown:
    """Standardized usage extracted from any provider's response."""
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    cache_write_tokens: int


class ProviderAdapter(Protocol):
    def build_request(
        self,
        spec: model_registry.ModelSpec,
        messages: list[dict],
        system: Optional[str],
        tools: Optional[list[dict]],
        max_tokens: int,
        **kwargs: Any,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Returns (url, headers, payload)."""
        ...

    def parse_usage(self, response_json: dict[str, Any]) -> UsageBreakdown:
        """Returns standardized usage from provider response."""
        ...

    def parse_response(self, response_json: dict[str, Any]) -> dict[str, Any]:
        """Returns {text, tool_uses, stop_reason}."""
        ...
