import { describe, it, expect } from "vitest";
import {
  PLAN_CAPS,
  DEFAULT_MODEL_BY_TIER_AND_TASK,
  TIERS,
  TASK_KINDS,
} from "@/lib/router/constants";

describe("PLAN_CAPS — locked against live public.plans", () => {
  const expected = {
    free: { uvt_monthly: 15000, opus_pct_cap: 0.0, concurrency_cap: 1, output_cap: 8000, sub_agent_cap: 5, context_budget_tokens: 8000 },
    solo: { uvt_monthly: 400000, opus_pct_cap: 0.0, concurrency_cap: 1, output_cap: 16000, sub_agent_cap: 8, context_budget_tokens: 24000 },
    pro: { uvt_monthly: 1500000, opus_pct_cap: 0.1, concurrency_cap: 3, output_cap: 32000, sub_agent_cap: 15, context_budget_tokens: 80000 },
    team: { uvt_monthly: 3000000, opus_pct_cap: 0.25, concurrency_cap: 10, output_cap: 64000, sub_agent_cap: 25, context_budget_tokens: 160000 },
  } as const;

  for (const tier of ["free", "solo", "pro", "team"] as const) {
    it(`${tier} matches locked ground truth`, () => {
      expect(PLAN_CAPS[tier]).toEqual(expected[tier]);
    });
  }

  it("has exactly 4 tiers", () => {
    expect(Object.keys(PLAN_CAPS).sort()).toEqual(["free", "pro", "solo", "team"]);
  });
});

describe("DEFAULT_MODEL_BY_TIER_AND_TASK", () => {
  it("free tier routes every task to claude-haiku-4", () => {
    for (const task of TASK_KINDS) {
      expect(DEFAULT_MODEL_BY_TIER_AND_TASK.free[task]).toBe("claude-haiku-4");
    }
  });

  it("solo research → claude-sonnet-4 (no perplexity-sonar bridge in PR1)", () => {
    expect(DEFAULT_MODEL_BY_TIER_AND_TASK.solo.research).toBe("claude-sonnet-4");
  });

  it("pro agent_plan → claude-opus-4 (subject to opus budget gate)", () => {
    expect(DEFAULT_MODEL_BY_TIER_AND_TASK.pro.agent_plan).toBe("claude-opus-4");
  });

  it("pro code_review → claude-opus-4", () => {
    expect(DEFAULT_MODEL_BY_TIER_AND_TASK.pro.code_review).toBe("claude-opus-4");
  });

  it("team mirrors pro's model selections for every task", () => {
    for (const task of TASK_KINDS) {
      expect(DEFAULT_MODEL_BY_TIER_AND_TASK.team[task]).toBe(
        DEFAULT_MODEL_BY_TIER_AND_TASK.pro[task],
      );
    }
  });

  it("solo code_review → claude-sonnet-4 (NOT opus — solo has opus_pct_cap=0)", () => {
    expect(DEFAULT_MODEL_BY_TIER_AND_TASK.solo.code_review).toBe("claude-sonnet-4");
  });

  it("covers every tier × task combination", () => {
    for (const tier of TIERS) {
      for (const task of TASK_KINDS) {
        expect(DEFAULT_MODEL_BY_TIER_AND_TASK[tier][task]).toBeTruthy();
      }
    }
  });
});
