"""
ModelRegistry — the single source of truth for model pricing + capability.

Used by:
- TokenAccountant: cost calculation + Anthropic client configuration
- Router: escalation decisions (which model serves qopc_load=light|medium|heavy)
- PricingGuard: per-user Opus sub-budget arithmetic

Invariants:
- model_id is the literal Anthropic API identifier. If Anthropic ships a new
  snapshot, update it here and nowhere else.
- Prices in USD cents (not dollars) to avoid float arithmetic on money.
- cache_discount is the multiplier applied to input_rate on cache HIT. Anthropic
  documents 0.90 (90% cheaper) on ephemeral-cache hits as of Oct 2025.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModelKey = Literal["haiku", "sonnet", "opus", "gpt5", "gemma"]


@dataclass(frozen=True)
class ModelSpec:
    key: ModelKey
    provider: Literal["anthropic", "openai", "google"]
    model_id: str
    input_cents_per_million: float   # USD cents per 1M input tokens
    output_cents_per_million: float  # USD cents per 1M output tokens
    cache_discount: float            # fraction off input on cache hit (0.90 = 90% cheaper)
    context_window_tokens: int
    supports_prompt_caching: bool
    enabled: bool                    # feature flag — router skips disabled models


# ═══════════════════════════════════════════════════════════════════════════
# Active models — Claude 4.x family (matches console.anthropic.com pricing)
# ═══════════════════════════════════════════════════════════════════════════

MODELS: dict[ModelKey, ModelSpec] = {
    "haiku": ModelSpec(
        key="haiku",
        provider="anthropic",
        model_id="claude-haiku-4-5-20251001",
        input_cents_per_million=80.0,      # $0.80/M input
        output_cents_per_million=400.0,    # $4.00/M output
        cache_discount=0.90,
        context_window_tokens=200_000,
        supports_prompt_caching=True,
        enabled=True,
    ),
    "sonnet": ModelSpec(
        key="sonnet",
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        input_cents_per_million=300.0,     # $3.00/M input
        output_cents_per_million=1500.0,   # $15.00/M output
        cache_discount=0.90,
        context_window_tokens=200_000,
        supports_prompt_caching=True,
        enabled=True,
    ),
    "opus": ModelSpec(
        key="opus",
        provider="anthropic",
        model_id="claude-opus-4-7",
        input_cents_per_million=1500.0,    # $15.00/M input
        output_cents_per_million=7500.0,   # $75.00/M output
        cache_discount=0.90,
        context_window_tokens=200_000,
        supports_prompt_caching=True,
        enabled=True,
    ),

    # ── Feature-flag slots ──────────────────────────────────────────
    # Wired but disabled. Enable by flipping `enabled=True` AND setting
    # the provider's API key + pricing. Router uses price parity to decide
    # cost-equivalent routing targets.
    "gpt5": ModelSpec(
        key="gpt5",
        provider="openai",
        model_id="gpt-5",
        input_cents_per_million=0.0,
        output_cents_per_million=0.0,
        cache_discount=0.0,
        context_window_tokens=0,
        supports_prompt_caching=False,
        enabled=False,
    ),
    "gemma": ModelSpec(
        key="gemma",
        provider="google",
        model_id="gemma-4",
        input_cents_per_million=0.0,
        output_cents_per_million=0.0,
        cache_discount=0.0,
        context_window_tokens=0,
        supports_prompt_caching=False,
        enabled=False,
    ),
}


def get(key: ModelKey) -> ModelSpec:
    """Lookup model spec. Raises KeyError on unknown key so callers fail loud."""
    return MODELS[key]


def is_enabled(key: ModelKey) -> bool:
    """True if the model is currently active in the router."""
    spec = MODELS.get(key)
    return bool(spec and spec.enabled)


def anthropic_keys() -> list[ModelKey]:
    """All currently-enabled Anthropic-provider keys, for wiring up live call sites."""
    return [k for k, spec in MODELS.items() if spec.enabled and spec.provider == "anthropic"]


# ═══════════════════════════════════════════════════════════════════════════
# Cost arithmetic — single source, used by TokenAccountant.
#
# UVT (User Visible Tokens) is what we bill against, and is model-agnostic:
#     UVT = (input - cached_input) + output
#
# cost_usd_cents is the internal COGS ledger, model-aware:
#     cost = (input - cached) * input_rate
#          + cached          * input_rate * (1 - cache_discount)
#          + output          * output_rate
# ═══════════════════════════════════════════════════════════════════════════


def uvt(input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> int:
    """User-Visible Tokens — what decrements from the user's monthly quota.
    Cached input is free to the user AND cheap to us, so it doesn't count.
    """
    uncached_input = max(0, input_tokens - cached_input_tokens)
    return uncached_input + output_tokens


def cost_usd_cents(
    key: ModelKey,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Fractional USD cents the call cost us at Anthropic list price.

    Fractional because a single low-output call can be <1¢; aggregated, it's
    not. Stored as numeric(12,6) in usage_events so we don't lose cents
    across a month of 10k calls.
    """
    spec = MODELS[key]
    uncached_input = max(0, input_tokens - cached_input_tokens)
    per_m = 1_000_000.0
    input_cost = (uncached_input / per_m) * spec.input_cents_per_million
    cached_cost = (cached_input_tokens / per_m) * spec.input_cents_per_million * (1.0 - spec.cache_discount)
    output_cost = (output_tokens / per_m) * spec.output_cents_per_million
    return input_cost + cached_cost + output_cost
