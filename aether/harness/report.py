"""
Margin report generator — consumes the per-call fact log the simulator
writes and emits two artifacts:

1. `reports/margin-<ts>.csv` — raw fact table, one row per call
   (including denied calls — denials are data).

2. `reports/margin-<ts>.md` — the summary the founder actually reads.
   Contains: per-tier margin table, warning flags, routing breakdown.

Warning flags (surfaced when triggered):
    🔴 Negative margin on any paid tier → pricing wrong
    🟡 >40% of users hit quota           → caps too tight (churn risk)
    🟡 <5% of users hit quota            → caps too loose (money on table)

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from aether.harness.in_memory_supabase import PLANS_SEED


# ═══════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CallRecord:
    """One row in margin-<ts>.csv. Every column is required so downstream
    aggregations can trust the schema."""
    user_id: str
    email: str
    day: int
    tier: str
    persona: str
    load: str                           # light / medium / heavy
    orchestrator_model: str             # haiku / sonnet / opus / '' if denied
    classifier_load: str                # what classifier returned
    confidence: float
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    uvt_charged: int                    # reported by /agent/run response
    underlying_cost_usd: float          # sum of token × ModelRegistry rates
    allowed: bool
    http_status: int
    reclassified: bool
    detail_code: str                    # only set on denied calls


# ═══════════════════════════════════════════════════════════════════════════
# Writers
# ═══════════════════════════════════════════════════════════════════════════


_CSV_COLUMNS = [
    "user_id", "email", "day", "tier", "persona", "load",
    "orchestrator_model", "classifier_load", "confidence",
    "input_tokens", "output_tokens", "cached_input_tokens",
    "uvt_charged", "underlying_cost_usd",
    "allowed", "http_status", "reclassified", "detail_code",
]


def write_csv(records: Iterable[CallRecord], path: str | os.PathLike) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        for r in records:
            w.writerow({k: getattr(r, k) for k in _CSV_COLUMNS})


# ═══════════════════════════════════════════════════════════════════════════
# Markdown summary
# ═══════════════════════════════════════════════════════════════════════════


def build_markdown(
    *,
    records: list[CallRecord],
    tier_filter: Optional[str],
    users_per_tier: dict[str, int],
    days: int,
    seed: int,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append(f"# AetherCloud UVT Margin Report — {ts}")
    lines.append("")
    lines.append(
        f"**Run:** tier-filter=`{tier_filter or 'all'}` · "
        f"users={sum(users_per_tier.values())} · days={days} · seed={seed} · "
        f"calls={len(records)} (incl. denied)"
    )
    lines.append("")

    lines.append("## Per-tier margin")
    lines.append("")
    lines.append(
        "| Tier | Users | Calls/mo avg | UVT burned | COGS $ | Sub $ | Overage $ | "
        "Revenue $ | Margin $ | Margin % |"
    )
    lines.append(
        "|------|------:|-------------:|-----------:|------:|------:|----------:|"
        "---------:|---------:|---------:|"
    )

    tier_summaries: dict[str, _TierSummary] = {}
    for tier in ("free", "solo", "pro", "team"):
        n_users = users_per_tier.get(tier, 0)
        if n_users == 0:
            continue
        s = _summarize_tier(records, tier, n_users, days)
        tier_summaries[tier] = s
        lines.append(
            f"| {s.tier} | {s.n_users} | {s.avg_calls_per_user:.0f} | "
            f"{_fmt_uvt(s.total_uvt)} | ${s.cogs_usd:.2f} | ${s.sub_usd:.2f} | "
            f"{s.overage_cell} | ${s.revenue_usd:.2f} | ${s.margin_usd:.2f} | "
            f"{s.margin_pct_cell} |"
        )
    lines.append("")

    # Warnings
    warnings = _warnings(tier_summaries, records, users_per_tier)
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Routing breakdown per tier
    lines.append("## Routing breakdown")
    lines.append("")
    for tier, n_users in users_per_tier.items():
        if n_users == 0:
            continue
        lines.append(f"### {tier.capitalize()} tier")
        lines.append("")
        lines.extend(_routing_breakdown(records, tier))
        lines.append("")

    return "\n".join(lines) + "\n"


# ═══════════════════════════════════════════════════════════════════════════
# Per-tier summary math
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class _TierSummary:
    tier: str
    n_users: int
    total_calls: int
    allowed_calls: int
    denied_calls: int
    total_uvt: int
    cogs_usd: float            # sum of underlying_cost_usd
    sub_usd: float             # n_users × plan.price_usd_cents
    overage_uvt: int
    overage_usd: float
    revenue_usd: float
    margin_usd: float
    margin_pct: Optional[float]   # None when revenue is 0 (free tier)
    avg_calls_per_user: float
    users_hitting_quota: int

    @property
    def overage_cell(self) -> str:
        if self.overage_usd == 0 and self.tier == "free":
            return "—"
        return f"${self.overage_usd:.2f}"

    @property
    def margin_pct_cell(self) -> str:
        if self.margin_pct is None:
            return "−∞" if self.margin_usd < 0 else "—"
        return f"{self.margin_pct:.0f}%"


def _summarize_tier(
    records: list[CallRecord], tier: str, n_users: int, days: int,
) -> _TierSummary:
    tier_rows = [r for r in records if r.tier == tier]
    allowed = [r for r in tier_rows if r.allowed]
    denied = [r for r in tier_rows if not r.allowed]

    plan = PLANS_SEED[tier]
    monthly_cap = plan["uvt_monthly"]
    overage_rate_cents = plan.get("overage_rate_usd_cents_per_million") or 0

    total_uvt = sum(r.uvt_charged for r in allowed)
    cogs_usd = round(sum(r.underlying_cost_usd for r in allowed), 4)

    # Per-user overage UVT = max(0, user's total UVT — monthly_cap)
    # summed across users.
    overage_uvt = 0
    users_hit_quota = 0
    by_user: dict[str, int] = {}
    for r in allowed:
        by_user[r.user_id] = by_user.get(r.user_id, 0) + r.uvt_charged
    for uvt in by_user.values():
        if uvt > monthly_cap:
            overage_uvt += uvt - monthly_cap
            users_hit_quota += 1

    overage_usd = (overage_uvt / 1_000_000) * (overage_rate_cents / 100)

    sub_usd = n_users * (plan["price_usd_cents"] / 100)
    revenue_usd = round(sub_usd + overage_usd, 4)
    margin_usd = round(revenue_usd - cogs_usd, 4)

    margin_pct: Optional[float] = None
    if revenue_usd > 0:
        margin_pct = (margin_usd / revenue_usd) * 100

    avg_calls_per_user = (len(tier_rows) / n_users) if n_users else 0

    return _TierSummary(
        tier=tier,
        n_users=n_users,
        total_calls=len(tier_rows),
        allowed_calls=len(allowed),
        denied_calls=len(denied),
        total_uvt=total_uvt,
        cogs_usd=cogs_usd,
        sub_usd=round(sub_usd, 2),
        overage_uvt=overage_uvt,
        overage_usd=round(overage_usd, 4),
        revenue_usd=revenue_usd,
        margin_usd=margin_usd,
        margin_pct=margin_pct,
        avg_calls_per_user=avg_calls_per_user,
        users_hitting_quota=users_hit_quota,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Warnings
# ═══════════════════════════════════════════════════════════════════════════


def _warnings(
    tiers: dict[str, _TierSummary],
    records: list[CallRecord],
    users_per_tier: dict[str, int],
) -> list[str]:
    out: list[str] = []
    for tier, s in tiers.items():
        if tier == "free":
            continue  # free is expected to be negative
        if s.margin_usd < 0:
            out.append(
                f"🔴 **Negative margin on {tier}**: "
                f"${s.margin_usd:.2f} (revenue ${s.revenue_usd:.2f}, COGS ${s.cogs_usd:.2f}). "
                f"Pricing or Opus sub-budget is wrong."
            )
        pct_hitting = (s.users_hitting_quota / s.n_users * 100) if s.n_users else 0
        if pct_hitting > 40:
            out.append(
                f"🟡 **{tier}: {pct_hitting:.0f}% of users hit quota**. "
                f"Caps may be too tight → churn risk."
            )
        elif pct_hitting < 5 and s.n_users >= 10:
            out.append(
                f"🟡 **{tier}: only {pct_hitting:.0f}% of users hit quota**. "
                f"Caps may be too loose → money on the table."
            )
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Routing breakdown
# ═══════════════════════════════════════════════════════════════════════════


def _routing_breakdown(records: list[CallRecord], tier: str) -> list[str]:
    tier_rows = [r for r in records if r.tier == tier]
    total = len(tier_rows)
    if total == 0:
        return ["_(no calls)_"]

    by_model: dict[str, list[CallRecord]] = {"haiku": [], "sonnet": [], "opus": []}
    denied: list[CallRecord] = []
    for r in tier_rows:
        if not r.allowed:
            denied.append(r); continue
        if r.orchestrator_model in by_model:
            by_model[r.orchestrator_model].append(r)

    lines: list[str] = []
    lines.append("```")
    lines.append(f"Routing mix ({tier} tier):")
    for model in ("haiku", "sonnet", "opus"):
        calls = by_model[model]
        if calls:
            pct = len(calls) / total * 100
            avg_cost = sum(r.underlying_cost_usd for r in calls) / len(calls)
            lines.append(f"  {model.capitalize():<8} {pct:5.1f}%  (${avg_cost:.4f} avg cost/call)")

    if denied:
        denied_pct = len(denied) / total * 100
        reasons: dict[str, int] = {}
        for r in denied:
            reasons[r.detail_code or "unknown"] = reasons.get(r.detail_code or "unknown", 0) + 1
        reason_str = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
        lines.append(f"  Denied   {denied_pct:5.1f}%  ({reason_str})")

    lines.append("```")
    return lines


def _fmt_uvt(v: int) -> str:
    if v >= 1_000_000: return f"{v/1_000_000:.2f}M"
    if v >= 1_000: return f"{v/1_000:.1f}K"
    return str(v)
