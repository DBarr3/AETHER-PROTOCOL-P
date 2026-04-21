"""
Tests for lib/context_compressor.py — the UVT leak plug.

Pure function tests, no mocks, no network. Focus on:
- Token estimation (char-based heuristic) matches expected ranges
- Under-budget inputs pass through unchanged
- Over-budget strings tail-trim (newest content preserved)
- Over-budget turn lists drop oldest-first
- keep_first=True retains turns[0] when trimming
- Edge cases (empty input, zero budget, single-turn over-budget)

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from lib import context_compressor as cc


# ═══════════════════════════════════════════════════════════════════════════
# estimate_tokens
# ═══════════════════════════════════════════════════════════════════════════


def test_estimate_empty_string():
    assert cc.estimate_tokens("") == 0


def test_estimate_short_string():
    # 40 chars / 4 = 10 tokens
    assert cc.estimate_tokens("a" * 40) == 10


def test_estimate_turns_with_content_strings():
    turns = [
        {"role": "user", "content": "a" * 40},     # ~10 tokens
        {"role": "assistant", "content": "b" * 80}, # ~20 tokens
    ]
    assert cc.estimate_tokens(turns) == 30


def test_estimate_turns_with_content_blocks():
    # Anthropic allows content as a list of typed blocks. Estimator should
    # walk them and not just stringify the whole dict.
    turns = [
        {"role": "user", "content": [
            {"type": "text", "text": "a" * 40},
            {"type": "text", "text": "b" * 80},
        ]},
    ]
    assert cc.estimate_tokens(turns) == 30


def test_estimate_non_string_non_list_returns_zero():
    assert cc.estimate_tokens(None) == 0  # type: ignore[arg-type]
    assert cc.estimate_tokens(42) == 0    # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# compress — string input
# ═══════════════════════════════════════════════════════════════════════════


def test_under_budget_string_passes_through():
    text = "short context"
    result = cc.compress(text, budget_tokens=1000)
    assert result == text


def test_over_budget_string_trims_from_front():
    # 40,000 chars / 4 = 10,000 tokens; budget 100 tokens → ~380 chars (95% margin)
    text = "0123456789" * 4000  # 40k chars
    result = cc.compress(text, budget_tokens=100)
    assert isinstance(result, str)
    # Most recent content preserved (end of string kept)
    assert result.endswith("0123456789")
    # Length roughly within budget
    assert cc.estimate_tokens(result) <= 100


def test_zero_budget_string_returns_empty_string():
    assert cc.compress("anything", budget_tokens=0) == ""


def test_negative_budget_string_returns_empty_string():
    assert cc.compress("anything", budget_tokens=-10) == ""


def test_empty_string_passes_through():
    assert cc.compress("", budget_tokens=1000) == ""


# ═══════════════════════════════════════════════════════════════════════════
# compress — list-of-turns input
# ═══════════════════════════════════════════════════════════════════════════


def test_under_budget_turns_pass_through():
    turns = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = cc.compress(turns, budget_tokens=1000)
    assert result == turns


def test_over_budget_turns_drop_oldest_first():
    # Each turn ~100 tokens; budget fits ~2 turns
    turns = [
        {"role": "user",      "content": "OLDEST: " + "a" * 400},
        {"role": "assistant", "content": "MIDDLE: " + "b" * 400},
        {"role": "user",      "content": "NEWEST: " + "c" * 400},
    ]
    result = cc.compress(turns, budget_tokens=210)
    assert isinstance(result, list)
    # Oldest gone, newer kept
    contents = [t["content"] for t in result]
    assert not any("OLDEST" in c for c in contents)
    assert any("NEWEST" in c for c in contents)


def test_keep_first_retains_persona_turn():
    # Classic pattern: turns[0] = persona system bootstrap. keep_first=True
    # must never drop it even when trimming the rest.
    turns = [
        {"role": "system",    "content": "PERSONA: " + "p" * 400},
        {"role": "user",      "content": "OLD: " + "a" * 400},
        {"role": "assistant", "content": "OLDER: " + "b" * 400},
        {"role": "user",      "content": "NEW: " + "c" * 400},
    ]
    result = cc.compress(turns, budget_tokens=220, keep_first=True)
    assert isinstance(result, list)
    contents = [t["content"] for t in result]
    # Persona present, newest present, middle(s) dropped
    assert any("PERSONA" in c for c in contents)
    assert any("NEW" in c for c in contents)


def test_empty_list_passes_through():
    assert cc.compress([], budget_tokens=1000) == []


def test_zero_budget_list_returns_empty_list():
    assert cc.compress([{"role": "user", "content": "x"}], budget_tokens=0) == []


def test_single_turn_too_big_with_keep_first_truncates_content():
    # keep_first=True on a single turn that alone exceeds budget. Rather
    # than returning [] (which would break the API call downstream), the
    # compressor truncates the turn's content string.
    huge = {"role": "user", "content": "x" * 8000}  # ~2000 tokens
    result = cc.compress([huge], budget_tokens=100, keep_first=True)
    assert len(result) == 1
    assert cc.estimate_tokens(result) <= 100
    # Same role preserved
    assert result[0]["role"] == "user"


def test_single_turn_too_big_without_keep_first_drops_it():
    # With keep_first=False, a lone over-budget turn is dropped entirely
    # (body becomes empty).
    huge = {"role": "user", "content": "x" * 8000}
    result = cc.compress([huge], budget_tokens=100, keep_first=False)
    assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# Budget boundary — matches real plans.context_budget_tokens values
# ═══════════════════════════════════════════════════════════════════════════


def test_free_tier_budget_constrains_context():
    # free tier = 8k tokens. 100k tokens in → trimmed to ~8k.
    text = "abc " * 100_000  # ~100k tokens
    result = cc.compress(text, budget_tokens=8_000)
    assert cc.estimate_tokens(result) <= 8_000


def test_team_tier_budget_passes_80k_tokens():
    # team tier = 160k tokens. 80k-token input stays intact.
    text = "abc " * 80_000  # ~80k tokens
    result = cc.compress(text, budget_tokens=160_000)
    assert result == text  # under budget → pass-through


def test_tier_budgets_sorted():
    # Sanity check on the documented tier budget ordering.
    free, starter, pro, team = 8_000, 24_000, 80_000, 160_000
    assert free < starter < pro < team
