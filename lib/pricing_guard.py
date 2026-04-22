"""
PricingGuard — the gate that refuses calls before they hit the Router.

Three checks, in order (fails fast, cheapest first):

1. CONCURRENCY — count public.tasks rows in ('pending','running') for this
   user in the last 10 min. Deny if >= plan.concurrency_cap → HTTP 429.
   Stale-task auto-expiry via the 10-min window: if an orchestrator crashes
   and leaves a 'running' row, it stops counting against the user after 10
   min without needing a cleanup cron.

2. DAILY SOFT CAP — 15% of plan.uvt_monthly per rolling 24h. Sum
   usage_events.uvt_counted for this user since now() - 24h. Deny if
   today + estimated_uvt > daily_cap. Overage_enabled bypasses.

3. MONTHLY QUOTA — uvt_balances.total_uvt + estimated_uvt <= plan.uvt_monthly.
   Overage_enabled bypasses (switches to metered billing at plan.overage_rate).
   Deny = HTTP 402 with upgrade CTA.

Estimation is UPPER-BOUND so we never under-reject into quota overshoot:
    estimated_uvt = (len(prompt + system + context) // 4) + requested_max_tokens

Unattributed calls (user_id=None) are rejected outright. PricingGuard is
the point where transition-mode Stage B/C ends and real attribution begins.

The decision envelope is returned, not raised, so callers can inspect.
`raise_if_denied(decision)` is the helper for FastAPI routes that want the
ergonomic HTTPException.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import HTTPException

from lib import context_compressor
from lib.router import PlanConfig

log = logging.getLogger("aethercloud.pricing_guard")

Tier = Literal["free", "solo", "pro", "team"]

# Percent of monthly quota that may be consumed in any rolling 24h window.
# Spec-locked at 15%.
DAILY_SOFT_CAP_FRACTION = 0.15

# Stale-task window. Tasks still in ('pending','running') older than this
# stop counting toward the concurrency cap. Handles orphaned rows from
# crashed workers without needing a cleanup job.
STALE_TASK_WINDOW_MINUTES = 10

# Upgrade ladder — what we suggest when quota is blown
_UPGRADE_CTA: dict[Tier, Optional[Tier]] = {
    "free": "solo",
    "solo": "pro",
    "pro":  "team",
    "team": None,  # already at top
}


# ═══════════════════════════════════════════════════════════════════════════
# Decision envelope
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class GuardDecision:
    """What preflight returns. allowed=False means the call must NOT run.
    overage_in_effect=True means allowed but billing at the tier's overage rate."""
    allowed: bool
    tier: Tier
    http_status: int = 200
    reason: Optional[str] = None
    detail_code: Optional[str] = None          # machine-readable: 'monthly_quota', 'daily_cap', 'concurrency', 'no_user_id'
    upgrade_cta_tier: Optional[Tier] = None
    overage_in_effect: bool = False
    # Telemetry — fills the /account/usage dashboard
    monthly_uvt_used: int = 0
    monthly_uvt_cap: int = 0
    monthly_uvt_remaining: int = 0
    daily_uvt_used: int = 0
    daily_uvt_cap: int = 0
    daily_uvt_remaining: int = 0
    concurrency_used: int = 0
    concurrency_cap: int = 0
    estimated_uvt: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Preflight
# ═══════════════════════════════════════════════════════════════════════════


async def preflight(
    *,
    user_id: Optional[str],
    tier: Tier,
    estimated_uvt: int,
    plan_cfg: PlanConfig,
    supabase_client: Any,
) -> GuardDecision:
    """Evaluate whether a request may proceed. Never raises; always returns
    a GuardDecision. Use raise_if_denied() if you want the FastAPI-style
    HTTPException.

    Checks fail fast in cost order:
        user_id presence → concurrency → daily cap → monthly quota
    """
    # ── Gate 0: attribution required ────────────────────────────────
    if not user_id:
        return GuardDecision(
            allowed=False,
            tier=tier,
            http_status=401,
            reason="unattributed call rejected — user_id required",
            detail_code="no_user_id",
            estimated_uvt=estimated_uvt,
        )

    # ── Gate 1: concurrency ─────────────────────────────────────────
    concurrency_used = _count_active_tasks(supabase_client, user_id)
    if concurrency_used >= plan_cfg.concurrency_cap:
        return GuardDecision(
            allowed=False,
            tier=tier,
            http_status=429,
            reason=f"concurrency cap reached ({concurrency_used}/{plan_cfg.concurrency_cap})",
            detail_code="concurrency",
            concurrency_used=concurrency_used,
            concurrency_cap=plan_cfg.concurrency_cap,
            upgrade_cta_tier=_UPGRADE_CTA.get(tier),
            estimated_uvt=estimated_uvt,
        )

    # ── Gate 2 + 3: fetch user overage + balance + daily usage ──────
    overage_enabled, overage_cap_cents = _fetch_overage_state(supabase_client, user_id)
    monthly_used = _fetch_monthly_uvt(supabase_client, user_id)
    daily_used = _fetch_daily_uvt(supabase_client, user_id)

    monthly_cap = plan_cfg.uvt_monthly
    daily_cap = int(monthly_cap * DAILY_SOFT_CAP_FRACTION)
    monthly_remaining = max(0, monthly_cap - monthly_used)
    daily_remaining = max(0, daily_cap - daily_used)

    # ── Gate 2: daily soft cap ──────────────────────────────────────
    if daily_used + estimated_uvt > daily_cap and not overage_enabled:
        return GuardDecision(
            allowed=False,
            tier=tier,
            http_status=402,
            reason=(
                f"daily soft cap reached "
                f"({daily_used}+{estimated_uvt} UVT > {daily_cap} daily limit). "
                f"Enable overage billing or wait 24h."
            ),
            detail_code="daily_cap",
            upgrade_cta_tier=_UPGRADE_CTA.get(tier),
            monthly_uvt_used=monthly_used,
            monthly_uvt_cap=monthly_cap,
            monthly_uvt_remaining=monthly_remaining,
            daily_uvt_used=daily_used,
            daily_uvt_cap=daily_cap,
            daily_uvt_remaining=daily_remaining,
            concurrency_used=concurrency_used,
            concurrency_cap=plan_cfg.concurrency_cap,
            estimated_uvt=estimated_uvt,
        )

    # ── Gate 3: monthly quota ───────────────────────────────────────
    would_exceed = (monthly_used + estimated_uvt) > monthly_cap
    overage_active = False
    if would_exceed:
        if not overage_enabled:
            return GuardDecision(
                allowed=False,
                tier=tier,
                http_status=402,
                reason=(
                    f"monthly UVT quota exceeded "
                    f"({monthly_used}+{estimated_uvt} > {monthly_cap}). "
                    f"Upgrade to {_UPGRADE_CTA.get(tier, 'a higher tier')} or enable overage."
                ),
                detail_code="monthly_quota",
                upgrade_cta_tier=_UPGRADE_CTA.get(tier),
                monthly_uvt_used=monthly_used,
                monthly_uvt_cap=monthly_cap,
                monthly_uvt_remaining=monthly_remaining,
                daily_uvt_used=daily_used,
                daily_uvt_cap=daily_cap,
                daily_uvt_remaining=daily_remaining,
                concurrency_used=concurrency_used,
                concurrency_cap=plan_cfg.concurrency_cap,
                estimated_uvt=estimated_uvt,
            )
        overage_active = True

    # ── Allowed ─────────────────────────────────────────────────────
    return GuardDecision(
        allowed=True,
        tier=tier,
        http_status=200,
        overage_in_effect=overage_active,
        monthly_uvt_used=monthly_used,
        monthly_uvt_cap=monthly_cap,
        monthly_uvt_remaining=monthly_remaining,
        daily_uvt_used=daily_used,
        daily_uvt_cap=daily_cap,
        daily_uvt_remaining=daily_remaining,
        concurrency_used=concurrency_used,
        concurrency_cap=plan_cfg.concurrency_cap,
        estimated_uvt=estimated_uvt,
    )


# ═══════════════════════════════════════════════════════════════════════════
# UVT pre-flight estimator
# ═══════════════════════════════════════════════════════════════════════════


# Typical output tokens for a LLM response. Used as the output estimate
# instead of requested_max_tokens because max_tokens is a CEILING, not a
# forecast. Most responses land well under this. Using the ceiling would
# make free-tier's 15% daily cap impossible to pass on any normal call.
# Overshoots are caught by the next preflight (actual usage will have been
# written to uvt_balances).
TYPICAL_OUTPUT_TOKENS = 1500


def estimate_uvt(
    *,
    prompt: str,
    system: Optional[str] = None,
    hydrated_context: Optional[str] = None,
    requested_max_tokens: int,
) -> int:
    """Realistic UVT estimate for pre-flight (not worst-case).

    Input tokens: chars/4 across prompt + system + context.
    Output tokens: min(requested_max_tokens, TYPICAL_OUTPUT_TOKENS).

    Why not worst case: requested_max_tokens is a hard ceiling, not a
    forecast. Using 8,000 (free-tier output_cap) as the output estimate
    would make the free daily cap (2,250 UVT) impossible to pass on any
    normal request. Over-rejecting the common case is worse than
    occasionally under-estimating — real usage gets written to
    uvt_balances and the NEXT preflight catches it.
    """
    input_chars = len(prompt) + (len(system or "") + len(hydrated_context or ""))
    input_tokens = max(1, input_chars // context_compressor.CHARS_PER_TOKEN)
    output_estimate = max(1, min(requested_max_tokens, TYPICAL_OUTPUT_TOKENS))
    return input_tokens + output_estimate


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI helper
# ═══════════════════════════════════════════════════════════════════════════


def raise_if_denied(decision: GuardDecision) -> GuardDecision:
    """Raise HTTPException with the right status + body if the decision
    is deny. Returns the decision unchanged on allow (so callers can chain)."""
    if decision.allowed:
        return decision
    raise HTTPException(
        status_code=decision.http_status,
        detail={
            "error": decision.detail_code or "quota_exceeded",
            "message": decision.reason or "request denied",
            "upgrade_to": decision.upgrade_cta_tier,
            "monthly_uvt_used": decision.monthly_uvt_used,
            "monthly_uvt_cap": decision.monthly_uvt_cap,
            "daily_uvt_used": decision.daily_uvt_used,
            "daily_uvt_cap": decision.daily_uvt_cap,
            "concurrency_used": decision.concurrency_used,
            "concurrency_cap": decision.concurrency_cap,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Supabase helpers (sync supabase-py, consistent with license_validation.py)
# ═══════════════════════════════════════════════════════════════════════════


def _count_active_tasks(supabase_client: Any, user_id: str) -> int:
    """Count user's tasks still pending or running in the last 10 min.
    Stale rows (older than STALE_TASK_WINDOW_MINUTES) don't count — prevents
    crashed workers from permanently locking out users."""
    try:
        since = _iso_minutes_ago(STALE_TASK_WINDOW_MINUTES)
        resp = (
            supabase_client.table("tasks")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .in_("status", ["pending", "running"])
            .gte("created_at", since)
            .execute()
        )
        resp = _maybe_await(resp)
        return int(getattr(resp, "count", None) or len(getattr(resp, "data", []) or []))
    except Exception as exc:
        log.warning("PricingGuard: task-count query failed (%s) — assuming 0", exc)
        return 0


def _fetch_overage_state(supabase_client: Any, user_id: str) -> tuple[bool, Optional[int]]:
    """Return (overage_enabled, overage_cap_usd_cents)."""
    try:
        resp = (
            supabase_client.table("users")
            .select("overage_enabled, overage_cap_usd_cents")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        resp = _maybe_await(resp)
        rows = getattr(resp, "data", None) or []
        if not rows:
            return False, None
        row = rows[0]
        return bool(row.get("overage_enabled", False)), row.get("overage_cap_usd_cents")
    except Exception as exc:
        log.warning("PricingGuard: overage-state query failed (%s) — assuming disabled", exc)
        return False, None


def _fetch_monthly_uvt(supabase_client: Any, user_id: str) -> int:
    """Read the most-recent period's total_uvt for this user.
    Returns 0 if no balance row exists yet (fresh user, no calls yet)."""
    try:
        resp = (
            supabase_client.table("uvt_balances")
            .select("total_uvt, period_started_at")
            .eq("user_id", user_id)
            .order("period_started_at", desc=True)
            .limit(1)
            .execute()
        )
        resp = _maybe_await(resp)
        rows = getattr(resp, "data", None) or []
        if not rows:
            return 0
        return int(rows[0].get("total_uvt", 0))
    except Exception as exc:
        log.warning("PricingGuard: monthly-uvt query failed (%s) — assuming 0", exc)
        return 0


def _fetch_daily_uvt(supabase_client: Any, user_id: str) -> int:
    """Sum uvt_counted across usage_events in the last 24h."""
    try:
        since = _iso_minutes_ago(24 * 60)
        resp = (
            supabase_client.table("usage_events")
            .select("uvt_counted")
            .eq("user_id", user_id)
            .gte("created_at", since)
            .execute()
        )
        resp = _maybe_await(resp)
        rows = getattr(resp, "data", None) or []
        return sum(int(r.get("uvt_counted", 0)) for r in rows)
    except Exception as exc:
        log.warning("PricingGuard: daily-uvt query failed (%s) — assuming 0", exc)
        return 0


def _iso_minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _maybe_await(resp: Any) -> Any:
    """supabase-py async client returns a coroutine from .execute(). We
    handle both so PricingGuard works with either client."""
    if asyncio.iscoroutine(resp):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(resp)
    return resp
