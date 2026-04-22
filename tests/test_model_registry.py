"""
Tests for lib/model_registry.py — pricing arithmetic + feature-flag gating.

No external I/O; this module is pure data + math.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import pytest

from lib import model_registry


# ═══════════════════════════════════════════════════════════════════════════
# Basic registry shape
# ═══════════════════════════════════════════════════════════════════════════


def test_anthropic_models_enabled_by_default():
    for key in ("haiku", "sonnet", "opus"):
        spec = model_registry.get(key)
        assert spec.enabled is True
        assert spec.provider == "anthropic"
        assert spec.model_id.startswith("claude-")


def test_feature_flag_models_disabled_by_default():
    for key in ("gpt5", "gemma"):
        spec = model_registry.get(key)
        assert spec.enabled is False


def test_is_enabled_matches_spec():
    assert model_registry.is_enabled("haiku") is True
    assert model_registry.is_enabled("gpt5") is False


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        model_registry.get("nonexistent")  # type: ignore[arg-type]


def test_anthropic_keys_returns_only_enabled_anthropic():
    keys = model_registry.anthropic_keys()
    assert set(keys) == {"haiku", "sonnet", "opus"}


# ═══════════════════════════════════════════════════════════════════════════
# UVT arithmetic — model-agnostic
# ═══════════════════════════════════════════════════════════════════════════


def test_uvt_simple_no_cache():
    # 1000 input + 500 output, no cache → 1500 UVT
    assert model_registry.uvt(1000, 500, 0) == 1500


def test_uvt_with_cache_discounts_cached_input():
    # 1000 input, 800 cached, 200 output → uncached 200 + output 200 = 400
    assert model_registry.uvt(1000, 200, 800) == 400


def test_uvt_cache_exceeds_input_clamped_to_zero():
    # Defensive: if Anthropic ever reports cache_read > input_tokens (shouldn't
    # happen but APIs surprise us), UVT must not go negative.
    assert model_registry.uvt(500, 100, 9999) == 100


def test_uvt_zero_call():
    assert model_registry.uvt(0, 0, 0) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Cost arithmetic — model-aware
# ═══════════════════════════════════════════════════════════════════════════


def test_cost_haiku_million_input_million_output():
    # 1M input + 1M output at Haiku 4.5 rates
    #   input  = 1,000,000 tokens × 80¢/M = 80¢
    #   output = 1,000,000 tokens × 400¢/M = 400¢
    #   total  = 480¢
    cost = model_registry.cost_usd_cents("haiku", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(480.0)


def test_cost_sonnet_million_input_million_output():
    # Sonnet 4.6: $3/M input + $15/M output = 300¢ + 1500¢ = 1800¢
    cost = model_registry.cost_usd_cents("sonnet", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(1800.0)


def test_cost_opus_million_input_million_output():
    # Opus 4.7: $15/M input + $75/M output = 1500¢ + 7500¢ = 9000¢
    cost = model_registry.cost_usd_cents("opus", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(9000.0)


def test_cost_opus_is_5x_sonnet_for_same_token_mix():
    # The "Opus costs 5x Sonnet" rule of thumb that drives router math.
    sonnet = model_registry.cost_usd_cents("sonnet", 100_000, 100_000, 0)
    opus = model_registry.cost_usd_cents("opus", 100_000, 100_000, 0)
    assert opus == pytest.approx(sonnet * 5.0)


def test_cache_hit_reduces_input_cost_by_ninety_percent():
    # 1M input, 900k cached, 0 output on Haiku
    #   uncached = 100k × 80¢/M = 8¢
    #   cached   = 900k × 80¢/M × 0.10 = 7.2¢
    #   total    = 15.2¢  (vs 80¢ with no cache)
    cost_cached = model_registry.cost_usd_cents("haiku", 1_000_000, 0, 900_000)
    cost_uncached = model_registry.cost_usd_cents("haiku", 1_000_000, 0, 0)
    assert cost_cached == pytest.approx(15.2)
    assert cost_uncached == pytest.approx(80.0)
    # Caching at 90% coverage should save roughly 81% of input cost
    assert cost_cached < cost_uncached * 0.20


def test_cost_zero_call_is_zero():
    for key in ("haiku", "sonnet", "opus"):
        assert model_registry.cost_usd_cents(key, 0, 0, 0) == 0.0


def test_cost_fractional_precision_preserved():
    # Tiny call — 100 input + 50 output on Sonnet — must produce non-zero
    # fractional cents, not round down to 0.
    cost = model_registry.cost_usd_cents("sonnet", 100, 50, 0)
    #   input  = 100 × 300 / 1M = 0.03¢
    #   output = 50  × 1500 / 1M = 0.075¢
    #   total  = 0.105¢
    assert cost == pytest.approx(0.105)
    assert cost > 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Invariants the router + pricing guard depend on
# ═══════════════════════════════════════════════════════════════════════════


def test_opus_pricier_than_sonnet_pricier_than_haiku_input():
    haiku = model_registry.get("haiku")
    sonnet = model_registry.get("sonnet")
    opus = model_registry.get("opus")
    assert haiku.input_cents_per_million < sonnet.input_cents_per_million < opus.input_cents_per_million


def test_opus_pricier_than_sonnet_pricier_than_haiku_output():
    haiku = model_registry.get("haiku")
    sonnet = model_registry.get("sonnet")
    opus = model_registry.get("opus")
    assert haiku.output_cents_per_million < sonnet.output_cents_per_million < opus.output_cents_per_million


def test_all_anthropic_models_support_prompt_caching():
    for key in ("haiku", "sonnet", "opus"):
        assert model_registry.get(key).supports_prompt_caching is True


def test_context_window_matches_anthropic_spec():
    # All Claude 4.x models ship with 200k context as of 2025-10.
    for key in ("haiku", "sonnet", "opus"):
        assert model_registry.get(key).context_window_tokens == 200_000
