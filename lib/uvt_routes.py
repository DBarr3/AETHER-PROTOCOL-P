"""
UVT API surface — stitches lib/ modules to the HTTP layer.

Three endpoints:
- POST /agent/run        — the single billable entrypoint (preflight → router)
- GET  /account/usage    — dashboard data (monthly/daily/concurrency/overage)
- POST /account/overage  — enable/disable metered-billing bypass

Injected at startup by api_server (same pattern as project_routes):
- supabase_client : sync supabase-py Client
- router          : lib.router.Router instance

Auth reuses api_server.svc.session_mgr. The session layer yields a username;
we resolve that to public.users.id (UUID) on each call. Resolution is cheap
and lets us handle users who sign up after a session already exists (edge
case) without session invalidation churn.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from lib import feature_flags, pricing_guard, router as router_module
from lib.router import PlanConfig, Router

log = logging.getLogger("aethercloud.uvt_routes")

# ── Injected by api_server at startup ─────────────────────────────────────
supabase_client: Optional[Any] = None
router_instance: Optional[Router] = None

uvt_router = APIRouter(tags=["uvt"])
_security = HTTPBearer(auto_error=False)


# ═══════════════════════════════════════════════════════════════════════════
# Request / response models
# ═══════════════════════════════════════════════════════════════════════════


class AgentRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50_000)
    system: Optional[str] = Field(None, max_length=20_000)
    hydrated_context: Optional[str] = Field(None, max_length=500_000)
    mcp_servers: Optional[list[dict]] = None
    task_id: Optional[str] = None


class AgentRunResponse(BaseModel):
    text: str
    orchestrator_model: str
    qopc_load: str
    confidence: float
    reason: str
    total_uvt: int
    classifier_uvt: int
    reclassified: bool = False
    overage_in_effect: bool = False
    task_id: Optional[str] = None


class AccountUsageResponse(BaseModel):
    tier: str
    monthly_uvt_used: int
    monthly_uvt_cap: int
    monthly_uvt_remaining: int
    daily_uvt_used: int
    daily_uvt_cap: int
    daily_uvt_remaining: int
    concurrency_used: int
    concurrency_cap: int
    overage_enabled: bool
    overage_cap_usd_cents: Optional[int] = None
    # UVT-Meter v3 dashboard fields
    days_until_reset: Optional[int] = None         # null if period boundary unknown
    overage_in_effect: bool = False                # true when enabled AND over monthly quota
    overage_usd_cents_used: int = 0                # Stripe metered billing tally, Stage H writes to this


class OverageUpdateRequest(BaseModel):
    enabled: bool
    cap_usd_cents: Optional[int] = Field(None, ge=0, le=1_000_000_000)


class OverageUpdateResponse(BaseModel):
    overage_enabled: bool
    overage_cap_usd_cents: Optional[int] = None


# ═══════════════════════════════════════════════════════════════════════════
# Auth + user-context resolution
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_token_to_username(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> str:
    """FastAPI dependency: validate bearer against api_server.svc.session_mgr."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = credentials.credentials
    try:
        from api_server import svc
    except Exception as exc:  # pragma: no cover — only fires if the server isn't fully booted
        log.error("uvt_routes: api_server.svc not importable (%s)", exc)
        raise HTTPException(status_code=503, detail="Session manager unavailable") from exc
    if not svc.session_mgr or not svc.session_mgr.is_valid(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    username = svc.session_mgr.get_username(token)
    if not username:
        raise HTTPException(status_code=401, detail="Cannot resolve user from token")
    return username


def _resolve_user_context(username: str) -> tuple[str, str]:
    """Look up public.users by email (= username in current auth) and return
    (user_id, tier). Raises 404 if the user has a session but no billing row
    (shouldn't happen; defensive)."""
    if supabase_client is None:
        raise HTTPException(status_code=503, detail="Billing backend not configured")
    try:
        resp = (
            supabase_client.table("users")
            .select("id, tier")
            .eq("email", username)
            .limit(1)
            .execute()
        )
        if asyncio.iscoroutine(resp):
            resp = asyncio.get_event_loop().run_until_complete(resp)
    except Exception as exc:
        log.error("uvt_routes: users lookup failed for %s: %s", username, exc)
        raise HTTPException(status_code=502, detail="Billing backend error") from exc
    rows = getattr(resp, "data", None) or []
    if not rows:
        raise HTTPException(status_code=404, detail="No billing record — sign up first")
    row = rows[0]
    return str(row["id"]), str(row["tier"])


def _get_plan_config(tier: str) -> PlanConfig:
    if router_instance is None:
        raise HTTPException(status_code=503, detail="Router not configured")
    return router_instance._get_plan_config(tier)  # noqa: SLF001 — same package


def _require_uvt_enabled(user_id: str) -> None:
    """Stage J kill-switch gate. When AETHER_UVT_ENABLED (+ rollout + overrides)
    resolve to False for this user, the UVT endpoints pretend they don't
    exist. 404 is the right status here — 'feature not available' not
    'you're unauthorized'. The desktop shell checks /healthz/flags before
    rendering the meter, so a 404 here is only hit by direct / stale clients."""
    if not feature_flags.is_uvt_enabled(user_id):
        raise HTTPException(status_code=404, detail={
            "error": "uvt_not_enabled",
            "message": "UVT billing is not enabled for this account yet.",
        })


# ═══════════════════════════════════════════════════════════════════════════
# POST /agent/run
# ═══════════════════════════════════════════════════════════════════════════


@uvt_router.post("/agent/run", response_model=AgentRunResponse)
async def agent_run(
    req: AgentRunRequest,
    username: str = Depends(_resolve_token_to_username),
) -> AgentRunResponse:
    """The billable entrypoint. Preflight → Router → return.

    Contract:
    - 200 on success with the full RouterResponse envelope.
    - 401 if no/invalid session.
    - 402 on quota/daily-cap exhaustion (with upgrade_to hint).
    - 429 on concurrency cap.
    - 502 if Supabase is wedged.
    """
    user_id, tier = _resolve_user_context(username)
    _require_uvt_enabled(user_id)
    plan_cfg = _get_plan_config(tier)

    # Upper-bound estimate BEFORE the call — never under-reject into overshoot.
    estimated = pricing_guard.estimate_uvt(
        prompt=req.prompt,
        system=req.system,
        hydrated_context=req.hydrated_context,
        requested_max_tokens=plan_cfg.output_cap,
    )

    decision = await pricing_guard.preflight(
        user_id=user_id,
        tier=tier,  # type: ignore[arg-type]
        estimated_uvt=estimated,
        plan_cfg=plan_cfg,
        supabase_client=supabase_client,
    )
    pricing_guard.raise_if_denied(decision)

    if router_instance is None:
        raise HTTPException(status_code=503, detail="Router not configured")

    try:
        result = await router_instance.route(
            user_id=user_id,
            tier=tier,  # type: ignore[arg-type]
            prompt=req.prompt,
            task_id=req.task_id,
            hydrated_context=req.hydrated_context,
            system=req.system,
            mcp_servers=req.mcp_servers,
        )
    except router_module.PlanExcludesOpusError as e:
        # Tripwire — PolicyGate should have refused upstream. Surface as 402.
        raise HTTPException(status_code=402, detail={
            "error": "router_gate",
            "gate_type": "plan_excludes_opus",
            "user_message_code": "upgrade_for_opus",
            "message": str(e),
        })
    except router_module.OpusBudgetExhaustedError as e:
        raise HTTPException(status_code=402, detail={
            "error": "router_gate",
            "gate_type": "opus_budget_exhausted",
            "user_message_code": "opus_budget_exceeded",
            "message": str(e),
        })

    return AgentRunResponse(
        text=result.text,
        orchestrator_model=result.orchestrator_model,
        qopc_load=result.qopc_load,
        confidence=result.confidence,
        reason=result.reason,
        total_uvt=result.total_uvt,
        classifier_uvt=result.classifier_uvt,
        reclassified=result.reclassified,
        overage_in_effect=decision.overage_in_effect,
        task_id=req.task_id,
    )


# ═══════════════════════════════════════════════════════════════════════════
# GET /account/usage
# ═══════════════════════════════════════════════════════════════════════════


@uvt_router.get("/account/usage", response_model=AccountUsageResponse)
async def account_usage(
    username: str = Depends(_resolve_token_to_username),
) -> AccountUsageResponse:
    """Snapshot the user's usage dashboard data.

    Runs preflight with estimated_uvt=0 — same math, same Supabase reads,
    but the decision is always allow (barring edge cases). We return the
    telemetry fields populated on the decision envelope.
    """
    user_id, tier = _resolve_user_context(username)
    _require_uvt_enabled(user_id)
    plan_cfg = _get_plan_config(tier)

    decision = await pricing_guard.preflight(
        user_id=user_id,
        tier=tier,  # type: ignore[arg-type]
        estimated_uvt=0,
        plan_cfg=plan_cfg,
        supabase_client=supabase_client,
    )

    # Pull overage state fresh — _fetch_overage_state is internal, so
    # re-query to keep this module decoupled. One extra Supabase hit per
    # /account/usage call is fine at dashboard-polling cadence.
    overage_enabled, overage_cap_cents = _read_overage_state(user_id)

    days_until_reset = _read_days_until_reset(user_id)
    overage_in_effect = bool(overage_enabled) and (
        decision.monthly_uvt_used >= decision.monthly_uvt_cap
    )
    # Stage H will populate this from Stripe metered-billing events; until
    # then the UI shows $0.00 when overage is active but no invoice has posted.
    overage_usd_cents_used = _read_overage_usd_cents_used(user_id)

    return AccountUsageResponse(
        tier=tier,
        monthly_uvt_used=decision.monthly_uvt_used,
        monthly_uvt_cap=decision.monthly_uvt_cap,
        monthly_uvt_remaining=decision.monthly_uvt_remaining,
        daily_uvt_used=decision.daily_uvt_used,
        daily_uvt_cap=decision.daily_uvt_cap,
        daily_uvt_remaining=decision.daily_uvt_remaining,
        concurrency_used=decision.concurrency_used,
        concurrency_cap=decision.concurrency_cap,
        overage_enabled=overage_enabled,
        overage_cap_usd_cents=overage_cap_cents,
        days_until_reset=days_until_reset,
        overage_in_effect=overage_in_effect,
        overage_usd_cents_used=overage_usd_cents_used,
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /account/overage
# ═══════════════════════════════════════════════════════════════════════════


@uvt_router.post("/account/overage", response_model=OverageUpdateResponse)
async def update_overage(
    req: OverageUpdateRequest,
    username: str = Depends(_resolve_token_to_username),
) -> OverageUpdateResponse:
    """Toggle overage billing and optionally set a monthly USD cap.

    Overage billing requires a valid Stripe payment method — we do NOT
    verify that here (Stripe webhook sets subscription_status='active' on
    checkout; absence means no payment method was ever collected). Guard
    against enabling overage for users who can't actually be billed.
    """
    user_id, _tier = _resolve_user_context(username)
    _require_uvt_enabled(user_id)

    if req.enabled:
        status = _read_subscription_status(user_id)
        if status not in ("active", "trialing"):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "payment_required",
                    "message": "Overage billing requires an active paid subscription. Upgrade first.",
                },
            )

    if supabase_client is None:
        raise HTTPException(status_code=503, detail="Billing backend not configured")

    update: dict = {"overage_enabled": req.enabled}
    if req.cap_usd_cents is not None:
        update["overage_cap_usd_cents"] = req.cap_usd_cents

    try:
        resp = (
            supabase_client.table("users")
            .update(update)
            .eq("id", user_id)
            .execute()
        )
        if asyncio.iscoroutine(resp):
            resp = asyncio.get_event_loop().run_until_complete(resp)
    except Exception as exc:
        log.error("uvt_routes: overage update failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=502, detail="Billing backend error") from exc

    # Invalidate the router's plans cache so any downstream budget math
    # picks up the new overage toggle immediately (defensive — overage
    # lives on users not plans, but cheap to invalidate).
    if router_instance is not None:
        router_instance.invalidate_plans_cache()

    return OverageUpdateResponse(
        overage_enabled=req.enabled,
        overage_cap_usd_cents=req.cap_usd_cents,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Small Supabase helpers (kept local — not reused outside this module)
# ═══════════════════════════════════════════════════════════════════════════


def _read_overage_state(user_id: str) -> tuple[bool, Optional[int]]:
    try:
        resp = (
            supabase_client.table("users")
            .select("overage_enabled, overage_cap_usd_cents")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if asyncio.iscoroutine(resp):
            resp = asyncio.get_event_loop().run_until_complete(resp)
        rows = getattr(resp, "data", None) or []
        if not rows:
            return False, None
        row = rows[0]
        return bool(row.get("overage_enabled", False)), row.get("overage_cap_usd_cents")
    except Exception as exc:
        log.warning("uvt_routes: overage-state read failed (%s) — assuming disabled", exc)
        return False, None


def _read_days_until_reset(user_id: str) -> Optional[int]:
    """Days until the user's current monthly UVT period rolls over.

    Read `users.current_period_started_at`, add 30 days, diff from now.
    Returns None if unreadable so the UI shows `—` rather than a wrong number.
    """
    try:
        resp = (
            supabase_client.table("users")
            .select("current_period_started_at")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if asyncio.iscoroutine(resp):
            resp = asyncio.get_event_loop().run_until_complete(resp)
        rows = getattr(resp, "data", None) or []
        if not rows:
            return None
        raw = rows[0].get("current_period_started_at")
        if not raw:
            return None
        from datetime import datetime, timezone, timedelta
        # Postgres returns ISO strings with +00:00 or Z suffix. Python 3.11+
        # handles Z natively via fromisoformat, but older versions don't —
        # normalize to +00:00.
        iso = str(raw).replace("Z", "+00:00")
        started = datetime.fromisoformat(iso)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        next_reset = started + timedelta(days=30)
        now = datetime.now(timezone.utc)
        delta = next_reset - now
        return max(0, delta.days)
    except Exception as exc:
        log.warning("uvt_routes: days_until_reset read failed (%s)", exc)
        return None


def _read_overage_usd_cents_used(user_id: str) -> int:
    """Accumulated overage cost in cents for the current period.

    Stage G stub: returns 0 until Stage H wires Stripe metered billing and
    persists invoice line-items per user. The UI already handles 0 as
    `$0.00` cleanly, so shipping this as a stub doesn't break the panel.
    """
    return 0


def _read_subscription_status(user_id: str) -> str:
    try:
        resp = (
            supabase_client.table("users")
            .select("subscription_status")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if asyncio.iscoroutine(resp):
            resp = asyncio.get_event_loop().run_until_complete(resp)
        rows = getattr(resp, "data", None) or []
        if not rows:
            return "inactive"
        return str(rows[0].get("subscription_status", "inactive"))
    except Exception as exc:
        log.warning("uvt_routes: subscription-status read failed (%s)", exc)
        return "inactive"
