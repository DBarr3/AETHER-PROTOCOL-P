"""PoC 2.3 / 2.10 — Doc/code drift: free tier silently receives Sonnet on
medium-classified prompts.

diagrams/docs_router_architecture.md § "Philosophy — honest limits":
    > Free user tries a task → runs on Haiku (explicit tier baseline,
    > not a downgrade).

But lib/router.py:_pick_orchestrator has no tier guard on medium:

    if signal.load == "light":
        return "haiku"
    if signal.load == "medium":
        return "sonnet"          # <-- returns Sonnet for EVERY tier

So a free-tier user whose prompt classifies as "medium" gets Sonnet.
Sonnet costs the service 5× Haiku (COGS: $3/M input + $15/M output vs
$0.80/M + $4/M for Haiku). At the free-tier cap of 15_000 UVT/month,
that's still a 5× margin bleed on COGS — a crafted "medium" prompt on
free tier burns Aether's Anthropic credit at Sonnet rates while the user
pays nothing.

Per red-team-doc §2 preamble: "If doc and code conflict, doc wins,
code is drift (Medium minimum)."

Severity: MEDIUM — margin attack, not a direct UVT-theft, but the
architecture doc explicitly promises Haiku-only on free and the code
violates that promise. Also: the 5 adversarial-classifier-invariant tests
(tests/test_model_router_invariant.py) all test HEAVY classification;
none test MEDIUM. This is the §2.3 "invariant-test blind spot."

Fix (lib/router.py:_pick_orchestrator):
    if signal.load == "light":
        return "haiku"
    if signal.load == "medium":
        # Free tier architectural floor: Haiku on medium too.
        return "haiku" if plan_cfg.tier == "free" else "sonnet"
    # heavy — existing logic
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from lib import qopc_bridge, router, token_accountant  # noqa: E402
from lib.qopc_bridge import QopcSignal  # noqa: E402
from lib.router import Router  # noqa: E402


_FREE_PLAN_ROW = {
    "tier": "free", "display_name": "Free", "price_usd_cents": 0,
    "uvt_monthly": 15_000, "sub_agent_cap": 5, "output_cap": 8_000,
    "opus_pct_cap": 0.0, "concurrency_cap": 1,
    "overage_rate_usd_cents_per_million": None,
    "context_budget_tokens": 8_000, "stripe_price_id": None,
}


def _supabase_free_tier():
    sb = MagicMock()

    def table(name):
        obj = MagicMock()
        if name == "plans":
            obj.select().eq().limit().execute.return_value = MagicMock(
                data=[_FREE_PLAN_ROW]
            )
        else:
            obj.select().eq().order().limit().execute.return_value = MagicMock(
                data=[{"opus_uvt": 0, "period_started_at": "2026-04-01"}]
            )
        return obj

    sb.table.side_effect = table
    return sb


@pytest.mark.asyncio
async def test_free_tier_medium_classification_receives_sonnet(monkeypatch):
    """Architectural violation: free tier + medium → Sonnet instead of Haiku."""
    monkeypatch.setattr(
        qopc_bridge, "classify",
        AsyncMock(return_value=QopcSignal(load="medium", confidence=0.9, reason="x")),
    )
    seen: dict = {}

    async def fake_call(**kw):
        seen["model"] = kw.get("model")
        resp = MagicMock()
        resp.text = ""
        resp.uvt_consumed = 0
        return resp

    monkeypatch.setattr(token_accountant, "call", fake_call)

    r = Router(_supabase_free_tier())
    result = await r.route(user_id="u-free-1", tier="free", prompt="Any medium task")

    # The bug:
    assert result.orchestrator_model == "sonnet", (
        "Expected current (buggy) behavior: free tier routed to Sonnet on "
        f"medium. Got {result.orchestrator_model!r}. If this assertion now "
        "FAILS, the bug has been fixed — great; update the test expectation."
    )
    assert seen["model"] == "sonnet", "TokenAccountant was asked to call Sonnet for a free user"

    # What the architecture doc PROMISED:
    # result.orchestrator_model == "haiku"
    # Sonnet is 5× Haiku COGS on identical UVT → margin bleed.


if __name__ == "__main__":
    import asyncio
    asyncio.run(
        test_free_tier_medium_classification_receives_sonnet(
            # monkeypatch shim — pytest provides it; emulate when run directly
            type("P", (), {"setattr": lambda self, tgt, name, val: setattr(tgt, name, val)})()
        )
    )
    print("Confirmed: free tier receives Sonnet on medium classification.")
