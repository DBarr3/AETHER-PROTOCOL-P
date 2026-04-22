"""
Tests for lib/pricing_guard.py — the quota/concurrency/daily-cap gate.

We mock the Supabase client to return canned balances + task counts. Every
decision rule has its own test, plus the overage overrides and the
raise_if_denied helper.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from lib import pricing_guard
from lib.router import PlanConfig


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


def _plan(tier: str, **overrides) -> PlanConfig:
    """Build a PlanConfig for tests. Defaults match the seeded plans table."""
    rows = {
        "free": dict(
            tier="free", display_name="Free",
            price_usd_cents=0, uvt_monthly=15_000,
            sub_agent_cap=5, output_cap=8_000,
            opus_pct_cap=0.0, concurrency_cap=1,
            overage_rate_usd_cents_per_million=None,
            context_budget_tokens=8_000, stripe_price_id=None,
        ),
        "solo": dict(
            tier="solo", display_name="Starter",
            price_usd_cents=1999, uvt_monthly=400_000,
            sub_agent_cap=8, output_cap=16_000,
            opus_pct_cap=0.0, concurrency_cap=1,
            overage_rate_usd_cents_per_million=4900,
            context_budget_tokens=24_000, stripe_price_id="price_solo",
        ),
        "pro": dict(
            tier="pro", display_name="Pro",
            price_usd_cents=4999, uvt_monthly=1_500_000,
            sub_agent_cap=15, output_cap=32_000,
            opus_pct_cap=0.10, concurrency_cap=3,
            overage_rate_usd_cents_per_million=3500,
            context_budget_tokens=80_000, stripe_price_id="price_pro",
        ),
        "team": dict(
            tier="team", display_name="Team",
            price_usd_cents=8999, uvt_monthly=3_000_000,
            sub_agent_cap=25, output_cap=64_000,
            opus_pct_cap=0.25, concurrency_cap=10,
            overage_rate_usd_cents_per_million=3200,
            context_budget_tokens=160_000, stripe_price_id="price_team",
        ),
    }
    row = rows[tier] | overrides
    return PlanConfig(**row)


def _supabase_mock(
    *,
    monthly_used: int = 0,
    daily_used: int = 0,
    active_tasks: int = 0,
    overage_enabled: bool = False,
    overage_cap_cents: Optional[int] = None,
) -> MagicMock:
    """Fake supabase client that returns canned data per-table."""
    state = {"table": None}

    def table(name):
        state["table"] = name
        return sb

    def execute():
        name = state["table"]
        if name == "tasks":
            m = MagicMock()
            m.count = active_tasks
            m.data = [{"id": f"t-{i}"} for i in range(active_tasks)]
            return m
        if name == "users":
            return MagicMock(data=[{
                "overage_enabled": overage_enabled,
                "overage_cap_usd_cents": overage_cap_cents,
            }])
        if name == "uvt_balances":
            if monthly_used == 0:
                return MagicMock(data=[])  # no balance row yet
            return MagicMock(data=[{
                "total_uvt": monthly_used,
                "period_started_at": "2026-04-01T00:00:00Z",
            }])
        if name == "usage_events":
            # Return enough rows to sum to daily_used
            if daily_used <= 0:
                return MagicMock(data=[])
            return MagicMock(data=[{"uvt_counted": daily_used}])
        return MagicMock(data=[])

    sb = MagicMock()
    sb.table = MagicMock(side_effect=table)
    sb.select = MagicMock(return_value=sb)
    sb.eq = MagicMock(return_value=sb)
    sb.in_ = MagicMock(return_value=sb)
    sb.gte = MagicMock(return_value=sb)
    sb.order = MagicMock(return_value=sb)
    sb.limit = MagicMock(return_value=sb)
    sb.execute = MagicMock(side_effect=execute)
    return sb


# ═══════════════════════════════════════════════════════════════════════════
# Attribution gate — user_id required
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_no_user_id_denied_401():
    decision = await pricing_guard.preflight(
        user_id=None,
        tier="free",
        estimated_uvt=1000,
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(),
    )
    assert decision.allowed is False
    assert decision.http_status == 401
    assert decision.detail_code == "no_user_id"


@pytest.mark.asyncio
async def test_empty_user_id_denied():
    decision = await pricing_guard.preflight(
        user_id="",
        tier="free",
        estimated_uvt=1000,
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(),
    )
    assert decision.allowed is False
    assert decision.detail_code == "no_user_id"


# ═══════════════════════════════════════════════════════════════════════════
# Monthly quota gate
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_free_fresh_user_allowed():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="free",
        estimated_uvt=1000,
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(),
    )
    assert decision.allowed is True
    assert decision.monthly_uvt_remaining == 15_000


@pytest.mark.asyncio
async def test_free_under_quota_allowed():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="free",
        estimated_uvt=500,
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(monthly_used=14_000, daily_used=0),
    )
    assert decision.allowed is True
    assert decision.monthly_uvt_used == 14_000


@pytest.mark.asyncio
async def test_free_would_exceed_monthly_denied_402():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="free",
        estimated_uvt=2000,  # 14k + 2k = 16k > 15k cap
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(monthly_used=14_000),
    )
    assert decision.allowed is False
    assert decision.http_status == 402
    assert decision.detail_code == "monthly_quota"
    assert decision.upgrade_cta_tier == "solo"


@pytest.mark.asyncio
async def test_solo_upgrade_cta_is_pro():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="solo",
        estimated_uvt=10_000,
        plan_cfg=_plan("solo"),
        supabase_client=_supabase_mock(monthly_used=399_999),
    )
    assert decision.allowed is False
    assert decision.upgrade_cta_tier == "pro"


@pytest.mark.asyncio
async def test_pro_upgrade_cta_is_team():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=10_000,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(monthly_used=1_500_000),
    )
    assert decision.allowed is False
    assert decision.upgrade_cta_tier == "team"


@pytest.mark.asyncio
async def test_team_has_no_upgrade_cta():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="team",
        estimated_uvt=10_000,
        plan_cfg=_plan("team"),
        supabase_client=_supabase_mock(monthly_used=3_000_000),
    )
    assert decision.allowed is False
    assert decision.upgrade_cta_tier is None


# ═══════════════════════════════════════════════════════════════════════════
# Overage bypass
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_overage_enabled_bypasses_monthly_quota():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="solo",
        estimated_uvt=10_000,
        plan_cfg=_plan("solo"),
        supabase_client=_supabase_mock(monthly_used=399_999, overage_enabled=True),
    )
    assert decision.allowed is True
    assert decision.overage_in_effect is True


@pytest.mark.asyncio
async def test_overage_disabled_blocks_at_quota():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="solo",
        estimated_uvt=10_000,
        plan_cfg=_plan("solo"),
        supabase_client=_supabase_mock(monthly_used=399_999, overage_enabled=False),
    )
    assert decision.allowed is False
    assert decision.overage_in_effect is False


# ═══════════════════════════════════════════════════════════════════════════
# Daily soft cap (15% of monthly)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_daily_cap_is_15_percent_of_monthly():
    # Pro monthly = 1.5M, daily cap = 225k
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=1000,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(),
    )
    assert decision.daily_uvt_cap == 225_000


@pytest.mark.asyncio
async def test_daily_cap_blocks_even_with_monthly_headroom():
    # Pro: used 220k today, 10k estimate → 230k > 225k daily cap.
    # Monthly is fine (plenty of headroom).
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=10_000,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(monthly_used=220_000, daily_used=220_000),
    )
    assert decision.allowed is False
    assert decision.detail_code == "daily_cap"
    assert "daily" in decision.reason.lower()


@pytest.mark.asyncio
async def test_daily_cap_bypassed_when_overage_enabled():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=10_000,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(
            monthly_used=220_000, daily_used=220_000, overage_enabled=True,
        ),
    )
    assert decision.allowed is True


# ═══════════════════════════════════════════════════════════════════════════
# Concurrency cap
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_free_concurrency_one_blocks_second_concurrent():
    # Free cap = 1. One task already running → deny the next.
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="free",
        estimated_uvt=100,
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(active_tasks=1),
    )
    assert decision.allowed is False
    assert decision.http_status == 429
    assert decision.detail_code == "concurrency"


@pytest.mark.asyncio
async def test_pro_concurrency_three_blocks_fourth():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=100,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(active_tasks=3),
    )
    assert decision.allowed is False
    assert decision.concurrency_used == 3
    assert decision.concurrency_cap == 3


@pytest.mark.asyncio
async def test_team_concurrency_ten_blocks_eleventh():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="team",
        estimated_uvt=100,
        plan_cfg=_plan("team"),
        supabase_client=_supabase_mock(active_tasks=10),
    )
    assert decision.allowed is False
    assert decision.http_status == 429


@pytest.mark.asyncio
async def test_concurrency_under_cap_allowed():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=100,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(active_tasks=2),  # cap is 3
    )
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_concurrency_check_runs_before_quota():
    # Even if they're way over quota, concurrency denies FIRST (cheaper to
    # check). We see 429 not 402.
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="free",
        estimated_uvt=999_999,
        plan_cfg=_plan("free"),
        supabase_client=_supabase_mock(active_tasks=1, monthly_used=15_000),
    )
    assert decision.http_status == 429
    assert decision.detail_code == "concurrency"


# ═══════════════════════════════════════════════════════════════════════════
# Estimator
# ═══════════════════════════════════════════════════════════════════════════


def test_estimate_uvt_input_plus_typical_output():
    # 400 chars prompt + 400 chars system + 200 chars context = 1000 chars
    #   input  = 1000/4 = 250 tokens
    # max_tokens = 500 (below typical 1500 ceiling)
    #   output = min(500, 1500) = 500
    #   total  = 250 + 500 = 750
    est = pricing_guard.estimate_uvt(
        prompt="a" * 400,
        system="b" * 400,
        hydrated_context="c" * 200,
        requested_max_tokens=500,
    )
    assert est == 750


def test_estimate_uvt_output_caps_at_typical():
    # max_tokens way above typical — estimate uses typical ceiling not max
    est = pricing_guard.estimate_uvt(
        prompt="a" * 40,
        requested_max_tokens=8000,  # free tier output_cap
    )
    # 40/4=10 input + typical_output=1500 = 1510
    assert est == 10 + pricing_guard.TYPICAL_OUTPUT_TOKENS


def test_estimate_uvt_low_max_tokens_honored():
    est = pricing_guard.estimate_uvt(
        prompt="a" * 40,
        requested_max_tokens=100,  # below typical, use the smaller
    )
    # 40/4=10 + min(100, 1500)=100 = 110
    assert est == 110


def test_estimate_uvt_no_system_no_context():
    est = pricing_guard.estimate_uvt(
        prompt="a" * 40,
        requested_max_tokens=100,
    )
    # 40/4=10 + 100 = 110
    assert est == 110


def test_estimate_uvt_always_at_least_one_output_token():
    est = pricing_guard.estimate_uvt(
        prompt="",  # 0 chars
        requested_max_tokens=0,  # explicit zero (pathological)
    )
    # Minimum 1 token input + 1 token output
    assert est >= 2


# ═══════════════════════════════════════════════════════════════════════════
# raise_if_denied helper
# ═══════════════════════════════════════════════════════════════════════════


def test_raise_if_denied_passes_through_allow():
    decision = pricing_guard.GuardDecision(
        allowed=True,
        tier="free",
        http_status=200,
    )
    # Should not raise; should return the decision.
    result = pricing_guard.raise_if_denied(decision)
    assert result is decision


def test_raise_if_denied_raises_on_deny():
    decision = pricing_guard.GuardDecision(
        allowed=False,
        tier="free",
        http_status=402,
        reason="quota exceeded",
        detail_code="monthly_quota",
        upgrade_cta_tier="solo",
        monthly_uvt_used=15_000,
        monthly_uvt_cap=15_000,
    )
    with pytest.raises(HTTPException) as exc_info:
        pricing_guard.raise_if_denied(decision)
    assert exc_info.value.status_code == 402
    body = exc_info.value.detail
    assert body["error"] == "monthly_quota"
    assert body["upgrade_to"] == "solo"
    assert body["monthly_uvt_cap"] == 15_000


def test_raise_if_denied_429_includes_concurrency_fields():
    decision = pricing_guard.GuardDecision(
        allowed=False,
        tier="pro",
        http_status=429,
        detail_code="concurrency",
        concurrency_used=3,
        concurrency_cap=3,
    )
    with pytest.raises(HTTPException) as exc_info:
        pricing_guard.raise_if_denied(decision)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["concurrency_used"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# Telemetry fields populated on allow
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_allow_response_carries_usage_dashboard_fields():
    decision = await pricing_guard.preflight(
        user_id="u-1",
        tier="pro",
        estimated_uvt=5_000,
        plan_cfg=_plan("pro"),
        supabase_client=_supabase_mock(
            monthly_used=200_000, daily_used=50_000, active_tasks=1,
        ),
    )
    assert decision.allowed is True
    assert decision.monthly_uvt_used == 200_000
    assert decision.monthly_uvt_cap == 1_500_000
    assert decision.monthly_uvt_remaining == 1_300_000
    assert decision.daily_uvt_used == 50_000
    assert decision.daily_uvt_cap == 225_000
    assert decision.daily_uvt_remaining == 175_000
    assert decision.concurrency_used == 1
    assert decision.concurrency_cap == 3
    assert decision.estimated_uvt == 5_000
