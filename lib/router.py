"""
═════════════════════════════════════════════════════════════════════════════
ModelRouter — MODEL SELECTION ONLY. NOT A POLICY ENFORCER.

  ⚠  DO NOT build features that assume this layer enforces plan limits,
      quotas, concurrency caps, or budget gates. It does NOT.

  ⚠  The historical silent-downgrade branches (heavy→sonnet,
     opus-exhausted→sonnet, budget-lookup-fail→sonnet) HAVE BEEN REPLACED
     with typed tripwire exceptions (PlanExcludesOpusError,
     OpusBudgetExhaustedError). They raise loudly — no path returns a
     weaker model silently for budget/tier reasons.

  ⚠  In production those exception paths should never fire because
     PolicyGate (TS edge, /api/internal/router/pick) throws 402 / 413 / 429
     BEFORE this code runs. Stage E (lib/pricing_guard.py) is the belt-
     and-suspenders enforcer during PR 1 v5 shadow mode; PR 2 flips
     PolicyGate from shadow to primary for canary users, and PR 3 cuts
     Stage E out entirely.

  ⚠  See diagrams/docs_router_architecture.md § "Division of Responsibility"
     for the hard line. RouterResponse.downgrade_reason was removed in PR 1
     v5 cleanup; callers that used to read it now receive a typed exception
     (PlanExcludesOpusError or OpusBudgetExhaustedError) that surfaces as
     an honest HTTP 402 — no silent downgrade path exists anymore.

ModelRouter's actual job:
    1. Compress hydrated context to plan.context_budget_tokens
    2. Classify load via QOPC bridge (light / medium / heavy)
    3. Pick a model APPROPRIATE FOR THE WORK (not for the user's eligibility)
    4. Confidence gate — low-confidence heavy → reclassify
    5. Call model via TokenAccountant (sole Anthropic path)
    6. Return RouterResponse with breakdown

Tripwire: every Router.route() call increments the module-level counter
`policy_bypass_detected` and emits one ROUTER_POLICY_BYPASS log line per
process. After PR 1 v5 lands, the route entry point will receive a
`policy_decision_id` from PolicyGate; the tripwire then only fires on
calls that lack that ID — which should be zero in production. Any non-zero
count post-PR-1 means something is bypassing the gate. SRE: alert on
ROUTER_POLICY_BYPASS log lines once PR 1 v5 is fully cut over.

Aether Systems LLC — Patent Pending
═════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from lib import context_compressor, qopc_bridge, token_accountant
from lib.model_registry import ModelKey

log = logging.getLogger("aethercloud.router")

# ─── SCARECROW: PolicyGate-bypass tripwire counter ──────────────────────
# Increments on every Router.route() invocation. Today fires on every call
# (PR 1 v5 / TypeScript PolicyGate hasn't shipped yet). Post-PR-1, this only
# increments when the upstream gate didn't run — which should be zero in
# prod. SRE: page on a non-zero rate after PR 1 v5 cuts over.
# See diagrams/docs_router_architecture.md § "Dead-code safety net".
policy_bypass_detected: int = 0
# Per-gate bypass counter — incremented when the typed-exception tripwires
# fire (PlanExcludesOpusError, OpusBudgetExhaustedError). Production should
# see these at 0; any non-zero value means a request reached Stage D with
# a condition that PolicyGate would have refused. Emits alongside the
# module counter for SRE alert correlation.
policy_bypass_by_gate: dict[str, int] = {
    "plan_excludes_opus": 0,
    "opus_budget_exhausted": 0,
}
_warned_once: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Tripwire exceptions — replace the PR 1 v4 silent-downgrade branches.
# In production PolicyGate blocks both upstream; if either raises, SRE pages.
# ═══════════════════════════════════════════════════════════════════════════


class PlanExcludesOpusError(Exception):
    """User's tier has opus_pct_cap=0 but heavy load was classified.
    PolicyGate should have caught this as FreeTierModelBlockedError (PR 2+)
    or mapped 'heavy' to Sonnet at the routing-table level. If this raises,
    something bypassed PolicyGate."""


class OpusBudgetExhaustedError(Exception):
    """User's opus sub-budget hit 0 MTD but heavy load was classified.
    PolicyGate should have caught this as OpusBudgetExceededError. If this
    raises, something bypassed PolicyGate."""

Tier = Literal["free", "solo", "pro", "team"]

# Confidence threshold below which a 'heavy' classification triggers a
# second-pass re-classify before committing to Opus. Documented in spec.
LOW_CONFIDENCE_RECLASSIFY_THRESHOLD = 0.6


# ═══════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class PlanConfig:
    """Mirror of one public.plans row. Loaded once per tier and cached."""
    tier: Tier
    display_name: str
    price_usd_cents: int
    uvt_monthly: int
    sub_agent_cap: int
    output_cap: int
    opus_pct_cap: float
    concurrency_cap: int
    overage_rate_usd_cents_per_million: Optional[int]
    context_budget_tokens: int
    stripe_price_id: Optional[str]


@dataclass
class RouterResponse:
    """What the /agent/run endpoint returns. Every field feeds the UX
    breakdown panel or the billing ledger — nothing here is decorative.

    Note: `downgrade_reason` was removed in PR 1 v5 cleanup. Budget/tier
    denials now raise typed exceptions (PlanExcludesOpusError,
    OpusBudgetExhaustedError) that surface to the caller as honest 402s
    via lib/uvt_routes.py. Silent downgrade is a philosophy violation."""
    text: str
    orchestrator_model: ModelKey
    qopc_load: str
    confidence: float
    reason: str                              # classifier's reason string
    total_uvt: int                           # UVT consumed by orchestrator call
    classifier_uvt: int                      # UVT consumed by classifier call(s)
    reclassified: bool = False               # second-pass was invoked


# ═══════════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════════


class Router:
    """Routes a single user request through classify → orchestrate.

    Holds the Supabase client + a small in-memory plans cache. Not
    thread-safe in the strictest sense, but the plans cache is write-once
    per tier so race conditions only cause duplicate lookups, never wrong
    config.
    """

    def __init__(self, supabase_client: Any):
        self._supabase = supabase_client
        self._plans_cache: dict[str, PlanConfig] = {}

    # ── Public API ──────────────────────────────────────────────────────

    async def route(
        self,
        *,
        user_id: Optional[str],
        tier: Tier,
        prompt: str,
        task_id: Optional[str] = None,
        hydrated_context: Optional[str] = None,
        system: Optional[str] = None,
        mcp_servers: Optional[list[dict]] = None,
    ) -> RouterResponse:
        """Route a single request.

        user_id may be None during the Stage B/C transition — ledger writes
        are skipped but the call still happens. PricingGuard in Stage E will
        require a real user_id.
        """
        # ── SCARECROW: PolicyGate-bypass tripwire ──────────────────────
        # Bumps the module counter on every call. Today this fires on every
        # invocation because PR 1 v5 (the TypeScript PolicyGate at
        # /api/internal/router/pick) hasn't shipped yet — the gate is
        # currently Stage E (Python pricing_guard.preflight). Post-PR-1,
        # the route entry will receive a policy_decision_id from PolicyGate
        # and skip this branch when present; remaining hits become the SRE
        # alert signal. See diagrams/docs_router_architecture.md §
        # "Dead-code safety net".
        global policy_bypass_detected, _warned_once
        policy_bypass_detected += 1
        if not _warned_once:
            log.warning(
                "ROUTER_POLICY_BYPASS: ModelRouter.route() invoked without "
                "an upstream PolicyGate decision_id. This is EXPECTED until "
                "PR 1 v5 ships. After cutover, any occurrence of this log "
                "indicates something bypassed PolicyGate — page SRE. "
                "See diagrams/docs_router_architecture.md."
            )
            _warned_once = True

        plan_cfg = self._get_plan_config(tier)

        # 1. Compress context to tier budget so re-injected history doesn't
        #    blow past context_budget_tokens (the documented UVT leak vector).
        compressed_ctx = context_compressor.compress(
            hydrated_context or "",
            plan_cfg.context_budget_tokens,
        )
        if not isinstance(compressed_ctx, str):
            # Defensive: compressor returns str when given str; if we ever
            # pass a list in future, flatten.
            compressed_ctx = ""

        # 2. Classify (Haiku, ~120 tokens, cached system prompt)
        signal = await qopc_bridge.classify(
            prompt,
            hydrated_context=compressed_ctx or None,
            user_id=user_id,
            task_id=task_id,
            supabase_client=self._supabase,
        )
        classifier_uvt = _classifier_token_estimate(prompt, compressed_ctx)
        reclassified = False

        # 3. Pick orchestrator model (raises PlanExcludesOpusError /
        #    OpusBudgetExhaustedError on heavy-but-denied cases)
        opus_remaining = self._opus_budget_remaining(user_id, plan_cfg)
        orchestrator_model = self._pick_orchestrator(
            signal, plan_cfg, opus_remaining,
        )

        # 4. Confidence gate: heavy + low confidence → second-pass classify
        if (
            orchestrator_model == "opus"
            and signal.confidence < LOW_CONFIDENCE_RECLASSIFY_THRESHOLD
        ):
            log.info(
                "Router: heavy/%.2f confidence — running second-pass classify",
                signal.confidence,
            )
            signal2 = await qopc_bridge.classify(
                prompt,
                hydrated_context=compressed_ctx or None,
                user_id=user_id,
                task_id=task_id,
                supabase_client=self._supabase,
            )
            classifier_uvt += _classifier_token_estimate(prompt, compressed_ctx)
            reclassified = True
            if signal2.load != "heavy":
                # Second pass disagrees — use the second signal's load as
                # ground truth (work-appropriate adjustment, not a budget
                # downgrade).
                signal = signal2
                orchestrator_model = self._pick_orchestrator(
                    signal2, plan_cfg, opus_remaining,
                )

        # 5. Orchestrator call (through TokenAccountant → UVT accounted + cached)
        max_tokens = plan_cfg.output_cap
        resp = await token_accountant.call(
            model=orchestrator_model,
            messages=[{"role": "user", "content": prompt}],
            system=system,
            mcp_servers=mcp_servers,
            user_id=user_id,
            task_id=task_id,
            qopc_load=signal.load,
            max_tokens=max_tokens,
            supabase_client=self._supabase,
        )

        return RouterResponse(
            text=resp.text,
            orchestrator_model=orchestrator_model,
            qopc_load=signal.load,
            confidence=signal.confidence,
            reason=signal.reason,
            total_uvt=resp.uvt_consumed,
            classifier_uvt=classifier_uvt,
            reclassified=reclassified,
        )

    # ── Decision rules ──────────────────────────────────────────────────

    @staticmethod
    def _pick_orchestrator(
        signal: qopc_bridge.QopcSignal,
        plan_cfg: PlanConfig,
        opus_remaining: int,
    ) -> ModelKey:
        """Map qopc_load × tier × opus-budget → orchestrator model.

        On heavy-but-denied cases, raises a typed tripwire exception.
        Production PolicyGate (TS edge) blocks these cases upstream with
        FreeTierModelBlockedError / OpusBudgetExceededError → HTTP 402. If
        either tripwire raises in prod, SRE pages — it means PolicyGate
        was bypassed.
        """
        if signal.load == "light":
            return "haiku"
        if signal.load == "medium":
            return "sonnet"

        # heavy
        if plan_cfg.opus_pct_cap <= 0:
            policy_bypass_by_gate["plan_excludes_opus"] += 1
            raise PlanExcludesOpusError(
                f"tier={plan_cfg.tier!r} has opus_pct_cap=0 — PolicyGate "
                "should have mapped this task away from Opus upstream"
            )
        if opus_remaining <= 0:
            policy_bypass_by_gate["opus_budget_exhausted"] += 1
            raise OpusBudgetExhaustedError(
                f"tier={plan_cfg.tier!r} opus sub-budget is 0 MTD — "
                "PolicyGate should have refused this call upstream"
            )
        return "opus"

    # ── Plan config lookup ──────────────────────────────────────────────

    def _get_plan_config(self, tier: Tier) -> PlanConfig:
        """Load and cache one public.plans row."""
        if tier in self._plans_cache:
            return self._plans_cache[tier]

        resp = (
            self._supabase.table("plans")
            .select(
                "tier, display_name, price_usd_cents, uvt_monthly, "
                "sub_agent_cap, output_cap, opus_pct_cap, concurrency_cap, "
                "overage_rate_usd_cents_per_million, context_budget_tokens, "
                "stripe_price_id"
            )
            .eq("tier", tier)
            .limit(1)
            .execute()
        )
        if asyncio.iscoroutine(resp):  # async client support
            resp = asyncio.get_event_loop().run_until_complete(resp)

        rows = getattr(resp, "data", None) or []
        if not rows:
            raise ValueError(f"Router: no plan config for tier={tier!r}")
        row = rows[0]
        cfg = PlanConfig(
            tier=row["tier"],
            display_name=row["display_name"],
            price_usd_cents=int(row["price_usd_cents"]),
            uvt_monthly=int(row["uvt_monthly"]),
            sub_agent_cap=int(row["sub_agent_cap"]),
            output_cap=int(row["output_cap"]),
            opus_pct_cap=float(row["opus_pct_cap"]),
            concurrency_cap=int(row["concurrency_cap"]),
            overage_rate_usd_cents_per_million=(
                int(row["overage_rate_usd_cents_per_million"])
                if row.get("overage_rate_usd_cents_per_million") is not None
                else None
            ),
            context_budget_tokens=int(row["context_budget_tokens"]),
            stripe_price_id=row.get("stripe_price_id"),
        )
        self._plans_cache[tier] = cfg
        return cfg

    def invalidate_plans_cache(self) -> None:
        """Drop the in-memory plans cache. Call after an admin updates the
        plans table so the next route() picks up new config."""
        self._plans_cache.clear()

    # ── Opus sub-budget ─────────────────────────────────────────────────

    def _opus_budget_remaining(
        self,
        user_id: Optional[str],
        plan_cfg: PlanConfig,
    ) -> int:
        """How much Opus quota this user has left in the current period.

        opus_remaining = (plan_cfg.uvt_monthly * plan_cfg.opus_pct_cap) - opus_uvt_used

        When user_id is None (unattributed calls during transition), we return
        a large value so the router doesn't artificially block unattributed
        Opus calls. PricingGuard in Stage E will refuse unattributed routing
        entirely.
        """
        total_allowed = int(plan_cfg.uvt_monthly * plan_cfg.opus_pct_cap)
        if total_allowed <= 0:
            return 0
        if user_id is None:
            return total_allowed

        try:
            resp = (
                self._supabase.table("uvt_balances")
                .select("opus_uvt, period_started_at")
                .eq("user_id", user_id)
                .order("period_started_at", desc=True)
                .limit(1)
                .execute()
            )
            if asyncio.iscoroutine(resp):
                resp = asyncio.get_event_loop().run_until_complete(resp)
            rows = getattr(resp, "data", None) or []
            opus_used = int(rows[0]["opus_uvt"]) if rows else 0
        except Exception as exc:
            # Supabase hiccup: fail-closed on Opus (cheaper error than
            # billing surprise). Returns 0; _pick_orchestrator then raises
            # OpusBudgetExhaustedError if load is heavy, which surfaces as
            # an honest 402 via uvt_routes.py — no silent downgrade path.
            # Production PolicyGate blocks this case upstream before we get
            # here; if the DB hiccup reaches Stage D, something bypassed
            # the gate. See diagrams/docs_router_architecture.md.
            log.warning("Router: opus_uvt lookup failed (%s) — assuming exhausted", exc)
            return 0

        return max(0, total_allowed - opus_used)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _classifier_token_estimate(prompt: str, compressed_ctx: str) -> int:
    """Rough UVT estimate for classifier calls — the real number comes back
    from TokenAccountant's response envelope, but we don't have that for
    the classifier's accounting since it flows through TokenAccountant's
    own path. This is used only for the RouterResponse.classifier_uvt
    telemetry field, not for billing (that happens inside TokenAccountant)."""
    # Input: system prompt (stable ~200 tokens cached) + user message
    user_chars = len(prompt) + len(compressed_ctx) + 60  # framing overhead
    input_tokens = max(1, user_chars // context_compressor.CHARS_PER_TOKEN)
    # Output: classifier emits ~30-50 tokens of JSON
    output_tokens = 40
    return input_tokens + output_tokens
