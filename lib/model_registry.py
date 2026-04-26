"""
ModelRegistry — the single source of truth for model pricing + capability.

Used by:
- TokenAccountant: cost calculation + provider client configuration
- Router: escalation decisions (which model serves qopc_load=light|medium|heavy)
- PricingGuard: per-user Opus sub-budget arithmetic

Invariants:
- model_id is the literal provider API identifier. If the provider ships a new
  snapshot, update it here and nowhere else.
- Prices in USD cents (not dollars) to avoid float arithmetic on money.
- cache_read_cents_per_million is the rate charged on cache HIT. For Anthropic
  this equals input_rate * 0.10 (90% cheaper). For DeepSeek, automatic prefix
  caching at input_rate * 0.10 as well (but no opt-in required).
- cache_write_cents_per_million is the rate charged on cache WRITE. For
  Anthropic this is input_rate * 1.25. None means "billed at miss rate"
  (i.e. no separate write surcharge).

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

ModelKey = Literal[
    "haiku", "sonnet", "opus",
    "gpt55", "gpt54", "gpt54_mini",
    "gemma",
    "dsv4_flash", "dsv4_pro",
]


@dataclass(frozen=True)
class ModelSpec:
    key: ModelKey
    provider: Literal["anthropic", "openai", "google", "deepseek"]
    model_id: str
    input_cents_per_million: float          # USD cents per 1M input tokens
    output_cents_per_million: float         # USD cents per 1M output tokens
    cache_read_cents_per_million: float     # rate on cache HIT
    cache_write_cents_per_million: Optional[float] = None   # rate on cache WRITE; None = billed at miss rate
    cache_storage_cents_per_million_hour: Optional[float] = None  # hourly storage; None = no storage charge
    context_window_tokens: int = 0
    supports_prompt_caching: bool = False
    reports_reasoning_tokens: bool = False  # True if provider emits reasoning_tokens in usage
    jurisdiction: Literal["us", "cn", "self"] = "us"
    enabled: bool = False                   # feature flag — router skips disabled models


# ═══════════════════════════════════════════════════════════════════════════
# Active models — Claude 4.x family (matches console.anthropic.com pricing)
# ═══════════════════════════════════════════════════════════════════════════

MODELS: dict[ModelKey, ModelSpec] = {
    "haiku": ModelSpec(
        key="haiku",
        provider="anthropic",
        model_id="claude-haiku-4-5-20251001",
        input_cents_per_million=80.0,               # $0.80/M input
        output_cents_per_million=400.0,             # $4.00/M output
        cache_read_cents_per_million=8.0,           # 80 * 0.10
        cache_write_cents_per_million=100.0,        # 80 * 1.25
        context_window_tokens=200_000,
        supports_prompt_caching=True,
        jurisdiction="us",
        enabled=True,
    ),
    "sonnet": ModelSpec(
        key="sonnet",
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        input_cents_per_million=300.0,              # $3.00/M input
        output_cents_per_million=1500.0,            # $15.00/M output
        cache_read_cents_per_million=30.0,          # 300 * 0.10
        cache_write_cents_per_million=375.0,        # 300 * 1.25
        context_window_tokens=200_000,
        supports_prompt_caching=True,
        jurisdiction="us",
        enabled=True,
    ),
    "opus": ModelSpec(
        key="opus",
        provider="anthropic",
        model_id="claude-opus-4-7",
        input_cents_per_million=1500.0,             # $15.00/M input
        output_cents_per_million=7500.0,            # $75.00/M output
        cache_read_cents_per_million=150.0,         # 1500 * 0.10
        cache_write_cents_per_million=1875.0,       # 1500 * 1.25
        context_window_tokens=200_000,
        supports_prompt_caching=True,
        jurisdiction="us",
        enabled=True,
    ),

    # ── OpenAI GPT-5 family (Phase 1+2 Amendment) ───────────────────
    # Gated by AETHER_OPENAI_ENABLED env var (see is_enabled()).
    # Reports reasoning_tokens=False because GPT-5.x doesn't surface them.
    # cache_write_cents_per_million=None → billed at miss rate (no surcharge).
    "gpt55": ModelSpec(
        key="gpt55",
        provider="openai",
        model_id="gpt-5.5",
        input_cents_per_million=500.0,             # $5.00/M input
        output_cents_per_million=3000.0,           # $30.00/M output
        cache_read_cents_per_million=50.0,         # 500 * 0.10
        cache_write_cents_per_million=None,
        context_window_tokens=270_000,
        supports_prompt_caching=True,
        reports_reasoning_tokens=False,
        jurisdiction="us",
        enabled=False,
    ),
    "gpt54": ModelSpec(
        key="gpt54",
        provider="openai",
        model_id="gpt-5.4",
        input_cents_per_million=250.0,             # $2.50/M input
        output_cents_per_million=1500.0,           # $15.00/M output
        cache_read_cents_per_million=25.0,         # 250 * 0.10
        cache_write_cents_per_million=None,
        context_window_tokens=270_000,
        supports_prompt_caching=True,
        reports_reasoning_tokens=False,
        jurisdiction="us",
        enabled=False,
    ),
    "gpt54_mini": ModelSpec(
        key="gpt54_mini",
        provider="openai",
        model_id="gpt-5.4-mini",
        input_cents_per_million=75.0,              # $0.75/M input
        output_cents_per_million=450.0,            # $4.50/M output
        cache_read_cents_per_million=7.5,          # 75 * 0.10
        cache_write_cents_per_million=None,
        context_window_tokens=270_000,
        supports_prompt_caching=True,
        reports_reasoning_tokens=False,
        jurisdiction="us",
        enabled=False,
    ),

    # ── Gemma (Google, stub — zero pricing until live) ────────────
    "gemma": ModelSpec(
        key="gemma",
        provider="google",
        model_id="gemma-4",
        input_cents_per_million=0.0,
        output_cents_per_million=0.0,
        cache_read_cents_per_million=0.0,
        cache_write_cents_per_million=None,
        context_window_tokens=0,
        supports_prompt_caching=False,
        reports_reasoning_tokens=False,
        jurisdiction="us",
        enabled=False,
    ),

    # ── DeepSeek V4 (Phase 2 — populated with real V4 pricing) ────────
    # Gated by AETHER_DEEPSEEK_ENABLED env var (see is_enabled()).
    # Legacy aliases deepseek-chat / deepseek-reasoner are deprecating;
    # model_ids use the V4-specific names per pricing doc.
    "dsv4_flash": ModelSpec(
        key="dsv4_flash",
        provider="deepseek",
        model_id="deepseek-v4-flash",
        input_cents_per_million=14.0,              # $0.14/M input (miss)
        output_cents_per_million=28.0,             # $0.28/M output
        cache_read_cents_per_million=2.8,          # $0.028/M cache hit (5x off)
        cache_write_cents_per_million=None,         # billed at miss rate
        context_window_tokens=1_000_000,
        supports_prompt_caching=True,
        reports_reasoning_tokens=True,
        jurisdiction="cn",
        enabled=False,
    ),
    "dsv4_pro": ModelSpec(
        key="dsv4_pro",
        provider="deepseek",
        model_id="deepseek-v4-pro",
        input_cents_per_million=174.0,             # $1.74/M input (miss)
        output_cents_per_million=348.0,            # $3.48/M output
        cache_read_cents_per_million=14.5,         # $0.145/M cache hit (~12x off)
        cache_write_cents_per_million=None,         # billed at miss rate
        context_window_tokens=1_000_000,
        supports_prompt_caching=True,
        reports_reasoning_tokens=True,
        jurisdiction="cn",
        enabled=False,
    ),
}


def get(key: ModelKey) -> ModelSpec:
    """Lookup model spec. Raises KeyError on unknown key so callers fail loud."""
    return MODELS[key]


def is_enabled(key: ModelKey) -> bool:
    """True if the model is currently active in the router.

    DeepSeek models require BOTH spec.enabled=True AND the
    AETHER_DEEPSEEK_ENABLED=true env var. This two-key gate prevents
    accidental activation before ops confirms API key + jurisdiction
    readiness on VPS2.
    """
    spec = MODELS.get(key)
    if not spec or not spec.enabled:
        return False
    if spec.provider == "deepseek":
        return os.environ.get("AETHER_DEEPSEEK_ENABLED", "").lower() == "true"
    if spec.provider == "openai":
        return os.environ.get("AETHER_OPENAI_ENABLED", "").lower() == "true"
    return True


def anthropic_keys() -> list[ModelKey]:
    """All currently-enabled Anthropic-provider keys, for wiring up live call sites."""
    return [k for k, spec in MODELS.items() if spec.enabled and spec.provider == "anthropic"]


def openai_keys() -> list[ModelKey]:
    """All currently-enabled OpenAI-provider keys."""
    return [k for k, spec in MODELS.items() if spec.enabled and spec.provider == "openai"]


# ═══════════════════════════════════════════════════════════════════════════
# Cost arithmetic — single source, used by TokenAccountant.
#
# UVT (User Visible Tokens) is what we bill against, and is model-agnostic:
#     UVT = (input - cached_input) + output
#
# cost_usd_cents is the internal COGS ledger, model-aware:
#     miss_cost   = (input - cached) / 1M * input_rate
#     hit_cost    = cached           / 1M * cache_read_rate
#     output_cost = output           / 1M * output_rate
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
    """Fractional USD cents the call cost us at provider list price.

    Fractional because a single low-output call can be <1 cent; aggregated, it's
    not. Stored as numeric(12,6) in usage_events so we don't lose cents
    across a month of 10k calls.

    Formula:
        miss_cost   = (input - cached) / 1M * input_rate
        hit_cost    = cached           / 1M * cache_read_rate
        output_cost = output           / 1M * output_rate
    """
    spec = MODELS[key]
    uncached_input = max(0, input_tokens - cached_input_tokens)
    per_m = 1_000_000.0
    input_cost = (uncached_input / per_m) * spec.input_cents_per_million
    cached_cost = (cached_input_tokens / per_m) * spec.cache_read_cents_per_million
    output_cost = (output_tokens / per_m) * spec.output_cents_per_million
    return input_cost + cached_cost + output_cost
