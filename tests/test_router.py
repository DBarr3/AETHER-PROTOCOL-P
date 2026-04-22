"""
Tests for lib/router.py — the orchestration decision layer.

We mock:
- qopc_bridge.classify → to emit canned signals
- token_accountant.call → to avoid hitting Anthropic
- supabase client → to return canned plans + balances rows

The contract under test:
- Decision rules: light→haiku, medium→sonnet, heavy→opus (when allowed)
- Tier gating: free/solo always downgrade heavy to sonnet (opus_pct_cap=0)
- Opus sub-budget: exhausted → silent downgrade + downgrade_reason set
- Confidence gate: heavy + conf<0.6 triggers second-pass classify
- Plan config caching: one lookup per tier
- output_cap applied as max_tokens
- qopc_load threaded to TokenAccountant for ledger rollup

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib import router
from lib.qopc_bridge import QopcSignal


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


# Mirrors the four rows seeded by 20260421_uvt_accounting.sql
_PLAN_ROWS = {
    "free": {
        "tier": "free", "display_name": "Free",
        "price_usd_cents": 0, "uvt_monthly": 15_000,
        "sub_agent_cap": 5, "output_cap": 8_000,
        "opus_pct_cap": 0.0, "concurrency_cap": 1,
        "overage_rate_usd_cents_per_million": None,
        "context_budget_tokens": 8_000,
        "stripe_price_id": None,
    },
    "solo": {
        "tier": "solo", "display_name": "Starter",
        "price_usd_cents": 1999, "uvt_monthly": 400_000,
        "sub_agent_cap": 8, "output_cap": 16_000,
        "opus_pct_cap": 0.0, "concurrency_cap": 1,
        "overage_rate_usd_cents_per_million": 4900,
        "context_budget_tokens": 24_000,
        "stripe_price_id": "price_1TOhH33TqWOqdd87qbWtG5ZG",
    },
    "pro": {
        "tier": "pro", "display_name": "Pro",
        "price_usd_cents": 4999, "uvt_monthly": 1_500_000,
        "sub_agent_cap": 15, "output_cap": 32_000,
        "opus_pct_cap": 0.10, "concurrency_cap": 3,
        "overage_rate_usd_cents_per_million": 3500,
        "context_budget_tokens": 80_000,
        "stripe_price_id": "price_1TOhH23TqWOqdd87AxosMSfb",
    },
    "team": {
        "tier": "team", "display_name": "Team",
        "price_usd_cents": 8999, "uvt_monthly": 3_000_000,
        "sub_agent_cap": 25, "output_cap": 64_000,
        "opus_pct_cap": 0.25, "concurrency_cap": 10,
        "overage_rate_usd_cents_per_million": 3200,
        "context_budget_tokens": 160_000,
        "stripe_price_id": "price_1TOhH23TqWOqdd87M3w25HEE",
    },
}


def _supabase_mock(opus_uvt_used: int = 0) -> MagicMock:
    """Build a supabase mock that returns plan rows and uvt_balances as
    the real API would. Chainable .table().select().eq().order().limit().execute()."""

    def _execute_for(query_table: str, filters: dict):
        if query_table == "plans":
            tier = filters.get("tier")
            row = _PLAN_ROWS.get(tier)
            return MagicMock(data=[row] if row else [])
        if query_table == "uvt_balances":
            return MagicMock(data=[{
                "opus_uvt": opus_uvt_used,
                "period_started_at": "2026-04-01T00:00:00Z",
            }])
        return MagicMock(data=[])

    sb = MagicMock()
    current_state = {"table": None, "filters": {}}

    def table(name):
        current_state["table"] = name
        current_state["filters"] = {}
        return sb

    def eq(column, value):
        current_state["filters"][column] = value
        return sb

    sb.table = MagicMock(side_effect=table)
    sb.select = MagicMock(return_value=sb)
    sb.eq = MagicMock(side_effect=eq)
    sb.order = MagicMock(return_value=sb)
    sb.limit = MagicMock(return_value=sb)
    sb.execute = MagicMock(
        side_effect=lambda: _execute_for(current_state["table"], current_state["filters"])
    )
    return sb


@dataclass
class _FakeResponse:
    text: str = "orchestrator response"
    raw: dict = field(default_factory=dict)
    model: str = "claude-sonnet-4-6"
    input_tokens: int = 200
    output_tokens: int = 100
    cached_input_tokens: int = 0
    uvt_consumed: int = 300
    cost_usd_cents: float = 1.0
    stop_reason: str = "end_turn"
    tool_uses: list = field(default_factory=list)


@pytest.fixture
def patches():
    """Patch classify + token_accountant.call. Yields (classify_mock, call_mock)."""
    with (
        patch.object(router.qopc_bridge, "classify", new_callable=AsyncMock) as classify_m,
        patch.object(router.token_accountant, "call", new_callable=AsyncMock) as call_m,
    ):
        classify_m.return_value = QopcSignal(load="medium", confidence=0.85, reason="ok")
        call_m.return_value = _FakeResponse()
        yield classify_m, call_m


# ═══════════════════════════════════════════════════════════════════════════
# Decision rules
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_light_picks_haiku(patches):
    classify_m, call_m = patches
    classify_m.return_value = QopcSignal(load="light", confidence=0.95, reason="lookup")
    r = router.Router(_supabase_mock())
    result = await r.route(user_id=None, tier="pro", prompt="What's 2+2?")
    assert result.orchestrator_model == "haiku"
    assert result.qopc_load == "light"
    assert call_m.call_args.kwargs["model"] == "haiku"


@pytest.mark.asyncio
async def test_medium_picks_sonnet(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="medium", confidence=0.85, reason="moderate")
    r = router.Router(_supabase_mock())
    result = await r.route(user_id=None, tier="pro", prompt="Write a function")
    assert result.orchestrator_model == "sonnet"


@pytest.mark.asyncio
async def test_heavy_on_pro_picks_opus(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.9, reason="architecture")
    r = router.Router(_supabase_mock(opus_uvt_used=0))
    result = await r.route(user_id="u-1", tier="pro", prompt="Design my system")
    assert result.orchestrator_model == "opus"
    assert result.downgrade_reason is None


@pytest.mark.asyncio
async def test_heavy_on_team_picks_opus(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="big task")
    r = router.Router(_supabase_mock(opus_uvt_used=0))
    result = await r.route(user_id="u-1", tier="team", prompt="Audit my codebase")
    assert result.orchestrator_model == "opus"


# ═══════════════════════════════════════════════════════════════════════════
# Tier gating
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heavy_on_free_downgrades_to_sonnet(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="big")
    r = router.Router(_supabase_mock())
    result = await r.route(user_id="u-1", tier="free", prompt="Design system")
    assert result.orchestrator_model == "sonnet"
    assert result.downgrade_reason == "tier does not include Opus"


@pytest.mark.asyncio
async def test_heavy_on_solo_downgrades_to_sonnet(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="big")
    r = router.Router(_supabase_mock())
    result = await r.route(user_id="u-1", tier="solo", prompt="Design system")
    assert result.orchestrator_model == "sonnet"
    assert "does not include Opus" in result.downgrade_reason


# ═══════════════════════════════════════════════════════════════════════════
# Opus sub-budget exhaustion
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_opus_exhausted_pro_downgrades(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="big")
    # Pro budget = 1.5M * 0.10 = 150k. Simulate 150k already used.
    r = router.Router(_supabase_mock(opus_uvt_used=150_000))
    result = await r.route(user_id="u-1", tier="pro", prompt="Complex thing")
    assert result.orchestrator_model == "sonnet"
    assert "exhausted" in result.downgrade_reason.lower()


@pytest.mark.asyncio
async def test_opus_exhausted_team_downgrades(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="big")
    # Team budget = 3M * 0.25 = 750k. Simulate 800k already used (overshot).
    r = router.Router(_supabase_mock(opus_uvt_used=800_000))
    result = await r.route(user_id="u-1", tier="team", prompt="Complex thing")
    assert result.orchestrator_model == "sonnet"
    assert "exhausted" in result.downgrade_reason.lower()


@pytest.mark.asyncio
async def test_opus_partial_budget_still_allows(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="big")
    # Pro with 100k used of 150k — still has 50k headroom
    r = router.Router(_supabase_mock(opus_uvt_used=100_000))
    result = await r.route(user_id="u-1", tier="pro", prompt="Big task")
    assert result.orchestrator_model == "opus"


# ═══════════════════════════════════════════════════════════════════════════
# Confidence gate — second-pass classify
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_low_confidence_heavy_triggers_reclassify(patches):
    classify_m, _ = patches
    # First classify: heavy with low confidence
    # Second classify: medium (disagrees) — router uses second
    classify_m.side_effect = [
        QopcSignal(load="heavy", confidence=0.4, reason="unsure"),
        QopcSignal(load="medium", confidence=0.8, reason="actually just medium"),
    ]
    r = router.Router(_supabase_mock())
    result = await r.route(user_id="u-1", tier="pro", prompt="Ambiguous request")
    assert classify_m.call_count == 2
    assert result.orchestrator_model == "sonnet"
    assert result.reclassified is True


@pytest.mark.asyncio
async def test_low_confidence_heavy_reclassify_agrees_stays_opus(patches):
    classify_m, _ = patches
    # First: heavy/low-conf. Second: heavy/high-conf → agrees → opus stays
    classify_m.side_effect = [
        QopcSignal(load="heavy", confidence=0.45, reason="maybe big"),
        QopcSignal(load="heavy", confidence=0.9, reason="yes big"),
    ]
    r = router.Router(_supabase_mock())
    result = await r.route(user_id="u-1", tier="pro", prompt="Big task")
    assert result.orchestrator_model == "opus"
    assert result.reclassified is True


@pytest.mark.asyncio
async def test_high_confidence_heavy_skips_reclassify(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.95, reason="obvious")
    r = router.Router(_supabase_mock())
    result = await r.route(user_id="u-1", tier="pro", prompt="Big task")
    assert classify_m.call_count == 1
    assert result.reclassified is False
    assert result.orchestrator_model == "opus"


@pytest.mark.asyncio
async def test_low_confidence_non_heavy_does_not_reclassify(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="medium", confidence=0.3, reason="unsure")
    r = router.Router(_supabase_mock())
    result = await r.route(user_id="u-1", tier="pro", prompt="Something")
    assert classify_m.call_count == 1  # no second pass for non-heavy
    assert result.orchestrator_model == "sonnet"


# ═══════════════════════════════════════════════════════════════════════════
# Contract with downstream calls
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_qopc_load_threaded_to_token_accountant(patches):
    classify_m, call_m = patches
    classify_m.return_value = QopcSignal(load="medium", confidence=0.9, reason="ok")
    r = router.Router(_supabase_mock())
    await r.route(user_id="u-1", tier="pro", prompt="Anything")
    assert call_m.call_args.kwargs["qopc_load"] == "medium"


@pytest.mark.asyncio
async def test_output_cap_applied_as_max_tokens(patches):
    classify_m, call_m = patches
    r = router.Router(_supabase_mock())
    await r.route(user_id="u-1", tier="pro", prompt="Anything")
    # Pro output_cap = 32_000
    assert call_m.call_args.kwargs["max_tokens"] == 32_000


@pytest.mark.asyncio
async def test_free_output_cap_is_eight_thousand(patches):
    _, call_m = patches
    r = router.Router(_supabase_mock())
    await r.route(user_id="u-1", tier="free", prompt="Anything")
    assert call_m.call_args.kwargs["max_tokens"] == 8_000


@pytest.mark.asyncio
async def test_user_id_threaded_through(patches):
    classify_m, call_m = patches
    r = router.Router(_supabase_mock())
    await r.route(user_id="user-abc", tier="pro", prompt="Anything")
    assert call_m.call_args.kwargs["user_id"] == "user-abc"
    assert classify_m.call_args.kwargs["user_id"] == "user-abc"


@pytest.mark.asyncio
async def test_system_prompt_passed_through(patches):
    _, call_m = patches
    r = router.Router(_supabase_mock())
    await r.route(user_id="u-1", tier="pro", prompt="Hi", system="You are X.")
    assert call_m.call_args.kwargs["system"] == "You are X."


@pytest.mark.asyncio
async def test_mcp_servers_passed_through(patches):
    _, call_m = patches
    r = router.Router(_supabase_mock())
    await r.route(
        user_id="u-1",
        tier="pro",
        prompt="Hi",
        mcp_servers=[{"type": "url", "url": "https://mcp.example.com"}],
    )
    assert call_m.call_args.kwargs["mcp_servers"] == [
        {"type": "url", "url": "https://mcp.example.com"}
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Plan config caching + lookup
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_plan_config_cached_per_tier(patches):
    sb = _supabase_mock()
    r = router.Router(sb)
    await r.route(user_id="u-1", tier="pro", prompt="one")
    await r.route(user_id="u-1", tier="pro", prompt="two")
    await r.route(user_id="u-1", tier="pro", prompt="three")
    # Count how many times the `plans` table was queried
    plans_table_calls = [c for c in sb.table.call_args_list if c.args[0] == "plans"]
    assert len(plans_table_calls) == 1  # cached after first


@pytest.mark.asyncio
async def test_unknown_tier_raises(patches):
    r = router.Router(_supabase_mock())
    with pytest.raises(ValueError, match="no plan config"):
        await r.route(user_id="u-1", tier="enterprise", prompt="x")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_invalidate_plans_cache_refetches(patches):
    sb = _supabase_mock()
    r = router.Router(sb)
    await r.route(user_id="u-1", tier="pro", prompt="one")
    r.invalidate_plans_cache()
    await r.route(user_id="u-1", tier="pro", prompt="two")
    plans_table_calls = [c for c in sb.table.call_args_list if c.args[0] == "plans"]
    assert len(plans_table_calls) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Response envelope
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_response_carries_all_breakdown_fields(patches):
    classify_m, call_m = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.92, reason="architecture")
    call_m.return_value = _FakeResponse(text="Designed.", uvt_consumed=5000)
    r = router.Router(_supabase_mock(opus_uvt_used=0))
    result = await r.route(user_id="u-1", tier="team", prompt="Design")
    assert result.text == "Designed."
    assert result.orchestrator_model == "opus"
    assert result.qopc_load == "heavy"
    assert result.confidence == pytest.approx(0.92)
    assert result.reason == "architecture"
    assert result.total_uvt == 5000
    assert result.classifier_uvt > 0
    assert result.downgrade_reason is None
    assert result.reclassified is False


# ═══════════════════════════════════════════════════════════════════════════
# Opus unattributed calls get the full budget (transition mode)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unattributed_heavy_on_pro_still_opus(patches):
    classify_m, _ = patches
    classify_m.return_value = QopcSignal(load="heavy", confidence=0.9, reason="big")
    r = router.Router(_supabase_mock())
    # user_id=None: can't look up opus_uvt — router returns the full budget
    # so unattributed calls aren't artificially blocked during transition.
    result = await r.route(user_id=None, tier="pro", prompt="Big thing")
    assert result.orchestrator_model == "opus"


# ═══════════════════════════════════════════════════════════════════════════
# Context compression is invoked
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_context_compressed_before_classify(patches):
    classify_m, _ = patches
    # Free tier context_budget = 8k tokens ≈ 32k chars. Feed 100k chars.
    huge = "x" * 100_000
    r = router.Router(_supabase_mock())
    await r.route(user_id="u-1", tier="free", prompt="hi", hydrated_context=huge)
    sent_ctx = classify_m.call_args.kwargs["hydrated_context"]
    assert sent_ctx is not None
    assert len(sent_ctx) < len(huge)
