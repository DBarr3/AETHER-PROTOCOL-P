import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { pick } from "@/lib/router/deterministic";
import {
  OpusBudgetExceededError,
  OutputTokensExceedCapError,
  ConcurrencyCapExceededError,
  InsufficientUvtBalanceError,
  RouterGateError,
} from "@/lib/router/errors";
import type { RoutingContext } from "@/lib/router/types";
import {
  setAuditWriter,
  resetAuditWriter,
  type RoutingDecisionRow,
} from "@/lib/router/auditLog";

function ctx(overrides: Partial<RoutingContext> = {}): RoutingContext {
  return {
    userId: "00000000-0000-0000-0000-000000000001",
    tier: "pro",
    taskKind: "chat",
    estimatedInputTokens: 100,
    estimatedOutputTokens: 100,
    opusPctMtd: 0.0,
    activeConcurrentTasks: 0,
    uvtBalance: 1_000_000,
    requestId: "req_1",
    traceId: "trace_1",
    ...overrides,
  };
}

describe("pick() — happy paths", () => {
  const captured: RoutingDecisionRow[] = [];
  beforeEach(() => {
    captured.length = 0;
    setAuditWriter(async (row) => {
      captured.push(row);
    });
  });

  it("pro + agent_plan + opusPctMtd=0.05 → claude-opus-4", () => {
    const d = pick(ctx({ tier: "pro", taskKind: "agent_plan", opusPctMtd: 0.05 }));
    expect(d.chosen_model).toBe("claude-opus-4");
    expect(d.reason_code).toBe("default_by_tier_and_task");
  });

  it("solo + code_gen → claude-sonnet-4", () => {
    const d = pick(ctx({ tier: "solo", taskKind: "code_gen" }));
    expect(d.chosen_model).toBe("claude-sonnet-4");
  });

  it.each([
    "chat", "code_gen", "code_review", "research",
    "summarize", "classify", "agent_plan", "agent_execute",
  ] as const)("free + %s → claude-haiku-4", (task) => {
    const d = pick(ctx({ tier: "free", taskKind: task }));
    expect(d.chosen_model).toBe("claude-haiku-4");
  });

  it("solo + code_review → claude-sonnet-4 (NOT opus)", () => {
    const d = pick(ctx({ tier: "solo", taskKind: "code_review" }));
    expect(d.chosen_model).toBe("claude-sonnet-4");
  });

  it("success stamps schema_version=1, weight_version=1, reason_code=default_by_tier_and_task", () => {
    const d = pick(ctx());
    expect(d.decision_schema_version).toBe(1);
    expect(d.uvt_weight_version).toBe(1);
    expect(d.reason_code).toBe("default_by_tier_and_task");
  });

  it("success writes audit row with chosen_model + both predicted costs", async () => {
    pick(ctx({ tier: "pro", taskKind: "code_gen", estimatedInputTokens: 1000, estimatedOutputTokens: 500 }));
    await new Promise((r) => setImmediate(r));
    expect(captured.length).toBe(1);
    expect(captured[0].chosen_model).toBe("claude-sonnet-4");
    expect(captured[0].reason_code).toBe("default_by_tier_and_task");
    expect(captured[0].predicted_uvt_cost).toBeGreaterThan(0);
    expect(captured[0].predicted_uvt_cost_simple).toBeGreaterThan(0);
    expect(captured[0].latency_ms).toBeGreaterThanOrEqual(0);
  });

  it("latency_ms populated on success", () => {
    const d = pick(ctx());
    expect(typeof d.latency_ms).toBe("number");
    expect(d.latency_ms).toBeGreaterThanOrEqual(0);
  });
});

describe("pick() — gates", () => {
  const captured: RoutingDecisionRow[] = [];
  beforeEach(() => {
    captured.length = 0;
    setAuditWriter(async (row) => {
      captured.push(row);
    });
  });

  it("free + agent_plan → no gate trips (tier default is haiku)", () => {
    expect(() => pick(ctx({ tier: "free", taskKind: "agent_plan" }))).not.toThrow();
  });

  it("pro + agent_plan + opusPctMtd=0.10 → OpusBudgetExceededError with opus_pct_cap", () => {
    try {
      pick(ctx({ tier: "pro", taskKind: "agent_plan", opusPctMtd: 0.1 }));
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(OpusBudgetExceededError);
      expect((e as RouterGateError).gateCapKey).toBe("opus_pct_cap");
      expect((e as RouterGateError).httpStatus).toBe(402);
    }
  });

  it("solo + 20000 output tokens → OutputTokensExceedCapError 413 with latency_ms on audit row", async () => {
    try {
      pick(ctx({ tier: "solo", taskKind: "code_gen", estimatedOutputTokens: 20000 }));
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(OutputTokensExceedCapError);
      expect((e as RouterGateError).httpStatus).toBe(413);
    }
    await new Promise((r) => setImmediate(r));
    expect(captured.length).toBe(1);
    expect(captured[0].reason_code).toBe("gate_rejected");
    expect(captured[0].gate_cap_key).toBe("output_cap");
    expect(captured[0].latency_ms).toBeGreaterThanOrEqual(0);
    expect(captured[0].chosen_model).toBeNull();
  });

  it("pro + activeConcurrentTasks=3 → ConcurrencyCapExceededError 429", () => {
    try {
      pick(ctx({ tier: "pro", taskKind: "code_review", activeConcurrentTasks: 3, opusPctMtd: 0 }));
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ConcurrencyCapExceededError);
      expect((e as RouterGateError).httpStatus).toBe(429);
      expect((e as RouterGateError).gateCapKey).toBe("concurrency_cap");
    }
  });

  it("predicted > balance → InsufficientUvtBalanceError 402", () => {
    try {
      pick(ctx({
        tier: "pro",
        taskKind: "chat",
        estimatedInputTokens: 1000,
        estimatedOutputTokens: 1000,
        uvtBalance: 10,
      }));
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(InsufficientUvtBalanceError);
      expect((e as RouterGateError).httpStatus).toBe(402);
      expect((e as RouterGateError).gateCapKey).toBe("uvt_balance");
    }
  });

  it("balance gate uses SIMPLE formula per UVT_FORMULA_ENFORCEMENT=simple", () => {
    // Simple = (1000-0) + 500 = 1500. Weighted for sonnet = ceil(1000*1 + 500*4)*1 = 3000.
    // If enforcement were weighted, balance of 2000 would trip. If simple, it passes.
    expect(() => pick(ctx({
      tier: "pro",
      taskKind: "chat",
      estimatedInputTokens: 1000,
      estimatedOutputTokens: 500,
      uvtBalance: 2000,
    }))).not.toThrow();
  });
});

describe("pick() — audit log resilience", () => {
  it("DB writer throws → pick() still returns normally (fire-and-forget)", async () => {
    setAuditWriter(async () => {
      throw new Error("DB down");
    });
    expect(() => pick(ctx())).not.toThrow();
    await new Promise((r) => setImmediate(r));
  });

  afterAll(() => resetAuditWriter());
});
