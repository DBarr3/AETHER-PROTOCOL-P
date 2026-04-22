"""Invariant: ModelRouter.final_model must never exceed the affordability
ceiling that PolicyGate would have enforced.

Adversarial setup: we feed Stage D a classifier that ALWAYS returns
heavy / 0.9 confidence — the riskiest possible 'I want Opus' signal.
Stage D must still refuse Opus when the tier or MTD budget doesn't allow
it, by raising one of the typed tripwire exceptions.

Production in the PR 1 v5 architecture: PolicyGate blocks these same
conditions at the HTTP edge with a 402, so Stage D should never actually
see them. The tripwire is a defense-in-depth. This test is the invariant
check that the defense is armed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib import router
from lib.qopc_bridge import QopcSignal
from lib.router import (
    OpusBudgetExhaustedError,
    PlanExcludesOpusError,
    Router,
)


_PLAN_ROWS = {
    "free": {
        "tier": "free", "display_name": "Free", "price_usd_cents": 0,
        "uvt_monthly": 15_000, "sub_agent_cap": 5, "output_cap": 8_000,
        "opus_pct_cap": 0.0, "concurrency_cap": 1,
        "overage_rate_usd_cents_per_million": None,
        "context_budget_tokens": 8_000, "stripe_price_id": None,
    },
    "solo": {
        "tier": "solo", "display_name": "Starter", "price_usd_cents": 1999,
        "uvt_monthly": 400_000, "sub_agent_cap": 8, "output_cap": 16_000,
        "opus_pct_cap": 0.0, "concurrency_cap": 1,
        "overage_rate_usd_cents_per_million": 4900,
        "context_budget_tokens": 24_000, "stripe_price_id": "price_sp",
    },
    "pro": {
        "tier": "pro", "display_name": "Pro", "price_usd_cents": 4999,
        "uvt_monthly": 1_500_000, "sub_agent_cap": 15, "output_cap": 32_000,
        "opus_pct_cap": 0.1, "concurrency_cap": 3,
        "overage_rate_usd_cents_per_million": 3500,
        "context_budget_tokens": 80_000, "stripe_price_id": "price_pp",
    },
    "team": {
        "tier": "team", "display_name": "Team", "price_usd_cents": 8999,
        "uvt_monthly": 3_000_000, "sub_agent_cap": 25, "output_cap": 64_000,
        "opus_pct_cap": 0.25, "concurrency_cap": 10,
        "overage_rate_usd_cents_per_million": 3200,
        "context_budget_tokens": 160_000, "stripe_price_id": "price_tp",
    },
}


def _supabase(opus_used: int = 0):
    sb = MagicMock()

    def table(name):
        obj = MagicMock()
        if name == "plans":
            chain = obj.select().eq()
            chain.limit().execute.return_value = MagicMock(data=[_PLAN_ROWS["pro"]])
            # fall-through by tier
            def eq_side(col, val):
                c = MagicMock()
                c.limit().execute.return_value = MagicMock(data=[_PLAN_ROWS[val]])
                return c
            obj.select().eq.side_effect = eq_side
        else:
            obj.select().eq().order().limit().execute.return_value = MagicMock(
                data=[{"opus_uvt": opus_used, "period_started_at": "2026-04-01"}],
            )
        return obj

    sb.table.side_effect = table
    return sb


@pytest.fixture
def adversarial_heavy(monkeypatch):
    """Classifier always returns heavy/0.9 confidence — the worst-case
    'please give me Opus' signal."""
    from lib import qopc_bridge
    classify = AsyncMock(return_value=QopcSignal(load="heavy", confidence=0.9, reason="ADVERSARIAL"))
    monkeypatch.setattr(qopc_bridge, "classify", classify)
    call = AsyncMock(return_value=MagicMock(text="x", uvt_consumed=0))
    from lib import token_accountant
    monkeypatch.setattr(token_accountant, "call", call)
    return classify, call


@pytest.mark.asyncio
async def test_invariant_free_tier_never_upgrades_to_opus(adversarial_heavy):
    r = Router(_supabase())
    with pytest.raises(PlanExcludesOpusError):
        await r.route(user_id="u-1", tier="free", prompt="Design my whole system")


@pytest.mark.asyncio
async def test_invariant_solo_tier_never_upgrades_to_opus(adversarial_heavy):
    r = Router(_supabase())
    with pytest.raises(PlanExcludesOpusError):
        await r.route(user_id="u-1", tier="solo", prompt="Design my whole system")


@pytest.mark.asyncio
async def test_invariant_pro_tier_at_opus_budget_zero_cannot_upgrade(adversarial_heavy):
    # Pro budget = 1.5M * 0.10 = 150k. 150k used → remaining == 0.
    r = Router(_supabase(opus_used=150_000))
    with pytest.raises(OpusBudgetExhaustedError):
        await r.route(user_id="u-1", tier="pro", prompt="Design my whole system")


@pytest.mark.asyncio
async def test_invariant_team_tier_overshot_budget_cannot_upgrade(adversarial_heavy):
    # Team budget = 3M * 0.25 = 750k. Overshoot by 50k.
    r = Router(_supabase(opus_used=800_000))
    with pytest.raises(OpusBudgetExhaustedError):
        await r.route(user_id="u-1", tier="team", prompt="Design my whole system")


@pytest.mark.asyncio
async def test_policy_bypass_counter_increments_on_tripwire(adversarial_heavy):
    """Even defense-in-depth firings should be counted so SRE can alert."""
    before = router.policy_bypass_by_gate["plan_excludes_opus"]
    r = Router(_supabase())
    with pytest.raises(PlanExcludesOpusError):
        await r.route(user_id="u-1", tier="free", prompt="x")
    assert router.policy_bypass_by_gate["plan_excludes_opus"] == before + 1
