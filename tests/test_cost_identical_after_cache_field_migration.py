"""
COGS-drift hard gate — proves that the cache_discount → cache-rate-triplet
migration in Phase 1 produces IDENTICAL cost_usd_cents output for every
Anthropic model across 5 representative token mixes.

If this test ever fails, someone changed pricing constants in model_registry
without updating the expectation table. That's a billing bug.

15 parametrized tests: 3 Anthropic models × 5 token-mix scenarios.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import pytest

from lib import model_registry


# ═══════════════════════════════════════════════════════════════════════════
# Expected costs — hand-calculated from Phase 0 pricing formula:
#     miss_cost   = (input - cached) / 1M × input_rate
#     hit_cost    = cached           / 1M × cache_read_rate
#     output_cost = output           / 1M × output_rate
#
# These values MUST match the old formula:
#     miss_cost   = (input - cached) / 1M × input_rate
#     hit_cost    = cached           / 1M × input_rate × (1 - cache_discount)
#     output_cost = output           / 1M × output_rate
#
# where cache_discount was 0.90 for all Anthropic models (90% cheaper).
# Now: cache_read_cents_per_million = input_rate × 0.10 (≡ input × (1-0.90))
# ═══════════════════════════════════════════════════════════════════════════

# (model_key, input_tokens, output_tokens, cached_input_tokens, expected_cents)
SCENARIOS = [
    # Scenario 1: 1M input, 1M output, no cache
    ("haiku",  1_000_000, 1_000_000, 0,       480.0),
    ("sonnet", 1_000_000, 1_000_000, 0,       1800.0),
    ("opus",   1_000_000, 1_000_000, 0,       9000.0),

    # Scenario 2: 1M input, 0 output, 900k cached (90% hit rate)
    # haiku:  miss = 100k × 80/1M = 8.0, hit = 900k × 8/1M = 7.2, total = 15.2
    # sonnet: miss = 100k × 300/1M = 30.0, hit = 900k × 30/1M = 27.0, total = 57.0
    # opus:   miss = 100k × 1500/1M = 150.0, hit = 900k × 150/1M = 135.0, total = 285.0
    ("haiku",  1_000_000, 0, 900_000,         15.2),
    ("sonnet", 1_000_000, 0, 900_000,         57.0),
    ("opus",   1_000_000, 0, 900_000,         285.0),

    # Scenario 3: Tiny call — 100 input + 50 output, no cache
    # haiku:  100 × 80/1M + 50 × 400/1M = 0.008 + 0.02 = 0.028
    # sonnet: 100 × 300/1M + 50 × 1500/1M = 0.03 + 0.075 = 0.105
    # opus:   100 × 1500/1M + 50 × 7500/1M = 0.15 + 0.375 = 0.525
    ("haiku",  100, 50, 0,                    0.028),
    ("sonnet", 100, 50, 0,                    0.105),
    ("opus",   100, 50, 0,                    0.525),

    # Scenario 4: All cached — 500k input all cached, 200k output
    # haiku:  miss = 0, hit = 500k × 8/1M = 4.0, output = 200k × 400/1M = 80.0, total = 84.0
    # sonnet: miss = 0, hit = 500k × 30/1M = 15.0, output = 200k × 1500/1M = 300.0, total = 315.0
    # opus:   miss = 0, hit = 500k × 150/1M = 75.0, output = 200k × 7500/1M = 1500.0, total = 1575.0
    ("haiku",  500_000, 200_000, 500_000,     84.0),
    ("sonnet", 500_000, 200_000, 500_000,     315.0),
    ("opus",   500_000, 200_000, 500_000,     1575.0),

    # Scenario 5: Zero call
    ("haiku",  0, 0, 0,                       0.0),
    ("sonnet", 0, 0, 0,                       0.0),
    ("opus",   0, 0, 0,                       0.0),
]


@pytest.mark.parametrize(
    "model_key, input_tokens, output_tokens, cached_input_tokens, expected_cents",
    SCENARIOS,
    ids=[
        f"{m}-{s}"
        for s, triples in enumerate(
            ["no_cache", "90pct_cache", "tiny_call", "all_cached", "zero_call"], 1
        )
        for m in ("haiku", "sonnet", "opus")
    ],
)
def test_cogs_identical_after_migration(
    model_key: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    expected_cents: float,
) -> None:
    """The cache-rate-triplet migration MUST produce identical cost output
    to the old cache_discount formula for all Anthropic models."""
    actual = model_registry.cost_usd_cents(
        model_key, input_tokens, output_tokens, cached_input_tokens  # type: ignore[arg-type]
    )
    assert actual == pytest.approx(expected_cents, abs=1e-6), (
        f"COGS drift detected for {model_key}: "
        f"expected {expected_cents}¢, got {actual}¢. "
        f"This is a billing bug — check cache_read_cents_per_million."
    )


# ═══════════════════════════════════════════════════════════════════════════
# Structural invariants — cache-rate triplet values are internally consistent
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("model_key", ["haiku", "sonnet", "opus"])
def test_cache_read_is_ten_percent_of_input(model_key: str) -> None:
    """For all Anthropic models, cache_read must equal input_rate × 0.10
    (the 90% discount that was previously hard-coded as cache_discount=0.90)."""
    spec = model_registry.get(model_key)  # type: ignore[arg-type]
    expected = spec.input_cents_per_million * 0.10
    assert spec.cache_read_cents_per_million == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("model_key", ["haiku", "sonnet", "opus"])
def test_cache_write_is_125_percent_of_input(model_key: str) -> None:
    """For all Anthropic models, cache_write must equal input_rate × 1.25."""
    spec = model_registry.get(model_key)  # type: ignore[arg-type]
    assert spec.cache_write_cents_per_million is not None
    expected = spec.input_cents_per_million * 1.25
    assert spec.cache_write_cents_per_million == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("model_key", ["haiku", "sonnet", "opus"])
def test_cache_read_cheaper_than_miss(model_key: str) -> None:
    """Cache hit must always be cheaper than a cache miss (uncached input)."""
    spec = model_registry.get(model_key)  # type: ignore[arg-type]
    assert spec.cache_read_cents_per_million < spec.input_cents_per_million
