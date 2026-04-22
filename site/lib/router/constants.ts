import type { Tier, TaskKind } from "./types";

export const TIERS: readonly Tier[] = ["free", "solo", "pro", "team"] as const;

export const TASK_KINDS: readonly TaskKind[] = [
  "chat",
  "code_gen",
  "code_review",
  "research",
  "summarize",
  "classify",
  "agent_plan",
  "agent_execute",
] as const;

export interface PlanCaps {
  uvt_monthly: number;
  opus_pct_cap: number;
  concurrency_cap: number;
  output_cap: number;
  sub_agent_cap: number;
  context_budget_tokens: number;
}

// Locked against live public.plans. Boot-time assertion in
// startupAssertions.ts reads the DB and fails boot on mismatch.
export const PLAN_CAPS: Readonly<Record<Tier, PlanCaps>> = Object.freeze({
  free: {
    uvt_monthly: 15000,
    opus_pct_cap: 0.0,
    concurrency_cap: 1,
    output_cap: 8000,
    sub_agent_cap: 5,
    context_budget_tokens: 8000,
  },
  solo: {
    uvt_monthly: 400000,
    opus_pct_cap: 0.0,
    concurrency_cap: 1,
    output_cap: 16000,
    sub_agent_cap: 8,
    context_budget_tokens: 24000,
  },
  pro: {
    uvt_monthly: 1500000,
    opus_pct_cap: 0.1,
    concurrency_cap: 3,
    output_cap: 32000,
    sub_agent_cap: 15,
    context_budget_tokens: 80000,
  },
  team: {
    uvt_monthly: 3000000,
    opus_pct_cap: 0.25,
    concurrency_cap: 10,
    output_cap: 64000,
    sub_agent_cap: 25,
    context_budget_tokens: 160000,
  },
});

// research tier-mapping note:
// Free → haiku cheapest path. Solo/Pro/Team → sonnet (no perplexity-sonar
// bridge in PR1; see deferrals in diagrams/docs_router_architecture.md).
export const DEFAULT_MODEL_BY_TIER_AND_TASK: Readonly<
  Record<Tier, Record<TaskKind, string>>
> = Object.freeze({
  free: {
    chat: "claude-haiku-4",
    code_gen: "claude-haiku-4",
    code_review: "claude-haiku-4",
    research: "claude-haiku-4",
    summarize: "claude-haiku-4",
    classify: "claude-haiku-4",
    agent_plan: "claude-haiku-4",
    agent_execute: "claude-haiku-4",
  },
  solo: {
    chat: "claude-sonnet-4",
    code_gen: "claude-sonnet-4",
    code_review: "claude-sonnet-4",
    research: "claude-sonnet-4",
    summarize: "claude-haiku-4",
    classify: "claude-haiku-4",
    agent_plan: "claude-sonnet-4",
    agent_execute: "claude-sonnet-4",
  },
  pro: {
    chat: "claude-sonnet-4",
    code_gen: "claude-sonnet-4",
    code_review: "claude-opus-4",
    research: "claude-sonnet-4",
    summarize: "claude-haiku-4",
    classify: "claude-haiku-4",
    agent_plan: "claude-opus-4",
    agent_execute: "claude-sonnet-4",
  },
  team: {
    chat: "claude-sonnet-4",
    code_gen: "claude-sonnet-4",
    code_review: "claude-opus-4",
    research: "claude-sonnet-4",
    summarize: "claude-haiku-4",
    classify: "claude-haiku-4",
    agent_plan: "claude-opus-4",
    agent_execute: "claude-sonnet-4",
  },
});

// Dual-formula shadow mode (decision C).
// "simple"   — all gates use computeUvtSimple. PR1.
// "weighted" — all gates use computeUvtWeighted. PR2 after usage_events backfill.
export const UVT_FORMULA_ENFORCEMENT: "simple" | "weighted" = "simple";
