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
    for key in ("gpt55", "gpt54", "gpt54_mini", "gemma"):
        spec = model_registry.get(key)
        assert spec.enabled is False


def test_is_enabled_matches_spec():
    assert model_registry.is_enabled("haiku") is True
    assert model_registry.is_enabled("gpt55") is False


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


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1+2 — DeepSeek V4 entries + cache-rate triplet + env gate
# ═══════════════════════════════════════════════════════════════════════════


def test_dsv4_entries_exist():
    for key in ("dsv4_flash", "dsv4_pro"):
        spec = model_registry.get(key)
        assert spec.provider == "deepseek"
        assert spec.jurisdiction == "cn"
        assert spec.reports_reasoning_tokens is True
        assert spec.supports_prompt_caching is True


def test_dsv4_disabled_by_default():
    for key in ("dsv4_flash", "dsv4_pro"):
        assert model_registry.get(key).enabled is False


def test_dsv4_is_enabled_requires_env_var(monkeypatch):
    """Even with spec.enabled=True, is_enabled() must also check
    AETHER_DEEPSEEK_ENABLED env var for deepseek provider."""
    # Enable the spec but don't set the env var
    spec = model_registry.get("dsv4_flash")
    monkeypatch.setitem(
        model_registry.MODELS,
        "dsv4_flash",
        model_registry.ModelSpec(**{**spec.__dict__, "enabled": True}),
    )
    monkeypatch.delenv("AETHER_DEEPSEEK_ENABLED", raising=False)
    assert model_registry.is_enabled("dsv4_flash") is False

    # Now set the env var
    monkeypatch.setenv("AETHER_DEEPSEEK_ENABLED", "true")
    assert model_registry.is_enabled("dsv4_flash") is True


def test_dsv4_is_enabled_case_insensitive(monkeypatch):
    spec = model_registry.get("dsv4_flash")
    monkeypatch.setitem(
        model_registry.MODELS,
        "dsv4_flash",
        model_registry.ModelSpec(**{**spec.__dict__, "enabled": True}),
    )
    monkeypatch.setenv("AETHER_DEEPSEEK_ENABLED", "TRUE")
    assert model_registry.is_enabled("dsv4_flash") is True


def test_dsv4_flash_context_window():
    assert model_registry.get("dsv4_flash").context_window_tokens == 1_000_000


def test_dsv4_pro_context_window():
    assert model_registry.get("dsv4_pro").context_window_tokens == 1_000_000


def test_cache_rate_triplet_anthropic_models():
    """Phase 1: cache_read, cache_write are explicit per-model fields."""
    for key in ("haiku", "sonnet", "opus"):
        spec = model_registry.get(key)
        # cache_read = input_rate * 0.10
        assert spec.cache_read_cents_per_million == pytest.approx(
            spec.input_cents_per_million * 0.10
        )
        # cache_write = input_rate * 1.25
        assert spec.cache_write_cents_per_million is not None
        assert spec.cache_write_cents_per_million == pytest.approx(
            spec.input_cents_per_million * 1.25
        )


def test_dsv4_no_cache_write_surcharge():
    """DeepSeek uses automatic prefix caching — no separate write fee."""
    for key in ("dsv4_flash", "dsv4_pro"):
        assert model_registry.get(key).cache_write_cents_per_million is None


def test_jurisdiction_anthropic_us():
    for key in ("haiku", "sonnet", "opus"):
        assert model_registry.get(key).jurisdiction == "us"


def test_cost_dsv4_flash_basic():
    # 1M input + 1M output at dsv4_flash rates: 14 + 28 = 42¢
    cost = model_registry.cost_usd_cents("dsv4_flash", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(42.0)


def test_cost_dsv4_pro_basic():
    # 1M input + 1M output at dsv4_pro rates: 174 + 348 = 522¢
    cost = model_registry.cost_usd_cents("dsv4_pro", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(522.0)


def test_dsv4_flash_much_cheaper_than_haiku():
    """DeepSeek Flash should be significantly cheaper than Haiku."""
    flash = model_registry.cost_usd_cents("dsv4_flash", 100_000, 100_000, 0)
    haiku = model_registry.cost_usd_cents("haiku", 100_000, 100_000, 0)
    assert flash < haiku


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1+2 Amendment — GPT-5 family entries + OpenAI env gate
# ═══════════════════════════════════════════════════════════════════════════


def test_gpt5_key_removed():
    """The old 'gpt5' stub key was replaced by gpt55/gpt54/gpt54_mini."""
    with pytest.raises(KeyError):
        model_registry.get("gpt5")  # type: ignore[arg-type]


def test_gpt5_family_entries_exist():
    for key in ("gpt55", "gpt54", "gpt54_mini"):
        spec = model_registry.get(key)
        assert spec.provider == "openai"
        assert spec.jurisdiction == "us"
        assert spec.reports_reasoning_tokens is False
        assert spec.supports_prompt_caching is True


def test_gpt5_family_disabled_by_default():
    for key in ("gpt55", "gpt54", "gpt54_mini"):
        assert model_registry.get(key).enabled is False


def test_gpt55_context_window():
    assert model_registry.get("gpt55").context_window_tokens == 270_000


def test_gpt54_context_window():
    assert model_registry.get("gpt54").context_window_tokens == 270_000


def test_gpt54_mini_context_window():
    assert model_registry.get("gpt54_mini").context_window_tokens == 270_000


def test_gpt5_no_cache_write_surcharge():
    """OpenAI uses server-side caching — no separate write fee."""
    for key in ("gpt55", "gpt54", "gpt54_mini"):
        assert model_registry.get(key).cache_write_cents_per_million is None


def test_gpt5_is_enabled_requires_env_var(monkeypatch):
    """Even with spec.enabled=True, is_enabled() must also check
    AETHER_OPENAI_ENABLED env var for openai provider."""
    spec = model_registry.get("gpt55")
    monkeypatch.setitem(
        model_registry.MODELS,
        "gpt55",
        model_registry.ModelSpec(**{**spec.__dict__, "enabled": True}),
    )
    monkeypatch.delenv("AETHER_OPENAI_ENABLED", raising=False)
    assert model_registry.is_enabled("gpt55") is False

    monkeypatch.setenv("AETHER_OPENAI_ENABLED", "true")
    assert model_registry.is_enabled("gpt55") is True


def test_gpt5_is_enabled_case_insensitive(monkeypatch):
    spec = model_registry.get("gpt54")
    monkeypatch.setitem(
        model_registry.MODELS,
        "gpt54",
        model_registry.ModelSpec(**{**spec.__dict__, "enabled": True}),
    )
    monkeypatch.setenv("AETHER_OPENAI_ENABLED", "TRUE")
    assert model_registry.is_enabled("gpt54") is True


def test_cost_gpt55_basic():
    # 1M input + 1M output at gpt55 rates: 500 + 3000 = 3500¢
    cost = model_registry.cost_usd_cents("gpt55", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(3500.0)


def test_cost_gpt54_basic():
    # 1M input + 1M output at gpt54 rates: 250 + 1500 = 1750¢
    cost = model_registry.cost_usd_cents("gpt54", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(1750.0)


def test_cost_gpt54_mini_basic():
    # 1M input + 1M output at gpt54_mini rates: 75 + 450 = 525¢
    cost = model_registry.cost_usd_cents("gpt54_mini", 1_000_000, 1_000_000, 0)
    assert cost == pytest.approx(525.0)


def test_gpt54_mini_input_cheaper_than_haiku():
    """GPT-5.4 Mini input rate is cheaper than Haiku input rate."""
    assert model_registry.get("gpt54_mini").input_cents_per_million < \
        model_registry.get("haiku").input_cents_per_million


def test_gpt55_input_rate():
    assert model_registry.get("gpt55").input_cents_per_million == 500.0


def test_openai_keys_empty_when_disabled():
    """All OpenAI models are disabled by default → openai_keys() returns []."""
    assert model_registry.openai_keys() == []


def test_openai_keys_returns_enabled(monkeypatch):
    spec = model_registry.get("gpt54_mini")
    monkeypatch.setitem(
        model_registry.MODELS,
        "gpt54_mini",
        model_registry.ModelSpec(**{**spec.__dict__, "enabled": True}),
    )
    keys = model_registry.openai_keys()
    assert "gpt54_mini" in keys


def test_modelkey_models_dict_parity():
    """Guard: every key in MODELS must be a valid ModelKey literal,
    and every ModelKey literal must be in MODELS."""
    import typing
    args = typing.get_args(model_registry.ModelKey)
    model_keys_set = set(args)
    models_dict_keys = set(model_registry.MODELS.keys())
    assert model_keys_set == models_dict_keys, (
        f"ModelKey literals {model_keys_set} != MODELS dict keys {models_dict_keys}"
    )
