"""
Router — single-turn orchestration from user prompt to model response.

Pipeline:
    classify → pick orchestrator model → call via TokenAccountant → return

Decision rules (locked in the spec, not heuristics):
- qopc_load='light'  → Haiku   (regardless of tier)
- qopc_load='medium' → Sonnet  (regardless of tier)
- qopc_load='heavy'  → Opus IF plans.opus_pct_cap > 0 AND opus_sub_budget > 0
                       ELSE Sonnet (silent downgrade with reason)

Confidence gate: qopc_load='heavy' AND confidence < 0.6 triggers a SECOND
Haiku classify call. If the second pass disagrees (returns light/medium),
we use that signal instead. This prevents low-confidence heavy flags from
burning Opus budget on ambiguous requests. Classifier is cheap enough
(<300 tokens of Haiku) that the guard is worth it.

Opus sub-budget: per-user, per-period, computed on the fly:
    opus_budget     = plans.uvt_monthly * plans.opus_pct_cap
    opus_remaining  = opus_budget - uvt_balances.opus_uvt
When opus_remaining <= 0, router silently downgrades to Sonnet and sets
RouterResponse.downgrade_reason so the UI banner can show.

Not yet in Stage D (deferred scope):
- Sub-agent dispatch (plan→execute→aggregate) — Stage D.5
- Pre-flight UVT quota check — Stage E (PricingGuard)
- Concurrency cap semaphore — Stage E (Redis/advisory-lock)
- Right-sizing plans that exceed sub_agent_cap — Stage D.5 (single-turn
  doesn't produce sub-agent plans)

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from lib import context_compressor, qopc_bridge, token_accountant
from lib.model_registry import ModelKey

log = logging.getLogger("aethercloud.router")

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
    breakdown panel or the billing ledger — nothing here is decorative."""
    text: str
    orchestrator_model: ModelKey
    qopc_load: str
    confidence: float
    reason: str                              # classifier's reason string
    total_uvt: int                           # UVT consumed by orchestrator call
    classifier_uvt: int                      # UVT consumed by classifier call(s)
    downgrade_reason: Optional[str] = None   # set when Opus was wanted but denied
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

        # 3. Pick orchestrator model
        opus_remaining = self._opus_budget_remaining(user_id, plan_cfg)
        orchestrator_model, downgrade_reason = self._pick_orchestrator(
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
                # Second pass disagrees — downgrade. Use the second signal's
                # load as the ground truth.
                signal = signal2
                orchestrator_model, downgrade_reason = self._pick_orchestrator(
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
            downgrade_reason=downgrade_reason,
            reclassified=reclassified,
        )

    # ── Decision rules ──────────────────────────────────────────────────

    @staticmethod
    def _pick_orchestrator(
        signal: qopc_bridge.QopcSignal,
        plan_cfg: PlanConfig,
        opus_remaining: int,
    ) -> tuple[ModelKey, Optional[str]]:
        """Map qopc_load × tier × opus-budget → orchestrator model.
        Returns (model_key, downgrade_reason). downgrade_reason is non-None
        only when Opus was the 'right' choice but we had to fall back."""
        if signal.load == "light":
            return "haiku", None
        if signal.load == "medium":
            return "sonnet", None
        # heavy
        if plan_cfg.opus_pct_cap <= 0:
            return "sonnet", "tier does not include Opus"
        if opus_remaining <= 0:
            return "sonnet", "Opus sub-budget exhausted for this period"
        return "opus", None

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
            # billing surprise). Router silently downgrades to Sonnet.
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
