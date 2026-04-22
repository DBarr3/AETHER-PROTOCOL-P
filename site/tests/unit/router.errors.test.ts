import { describe, it, expect } from "vitest";
import {
  RouterGateError,
  FreeTierModelBlockedError,
  OpusBudgetExceededError,
  OutputTokensExceedCapError,
  ConcurrencyCapExceededError,
  InsufficientUvtBalanceError,
} from "@/lib/router/errors";

describe("RouterGateError subclasses — HTTP status + user_message_code + fields", () => {
  it("OpusBudgetExceededError → 402, opus_budget_exceeded, preserves gateCapKey+values", () => {
    const e = new OpusBudgetExceededError({
      message: "opus budget hit",
      gateCapKey: "opus_pct_cap",
      planCapValue: 0.1,
      observedValue: 0.12,
    });
    expect(e).toBeInstanceOf(RouterGateError);
    expect(e.httpStatus).toBe(402);
    expect(e.userMessageCode).toBe("opus_budget_exceeded");
    expect(e.gateType).toBe("opus_budget_exceeded");
    expect(e.gateCapKey).toBe("opus_pct_cap");
    expect(e.planCapValue).toBe(0.1);
    expect(e.observedValue).toBe(0.12);
  });

  it("OutputTokensExceedCapError → 413, output_tokens_exceed_plan", () => {
    const e = new OutputTokensExceedCapError({
      message: "too many output tokens",
      gateCapKey: "output_cap",
      planCapValue: 16000,
      observedValue: 20000,
    });
    expect(e.httpStatus).toBe(413);
    expect(e.userMessageCode).toBe("output_tokens_exceed_plan");
    expect(e.gateType).toBe("output_tokens_exceed_cap");
  });

  it("ConcurrencyCapExceededError → 429, concurrency_exceeded", () => {
    const e = new ConcurrencyCapExceededError({
      message: "too many concurrent",
      gateCapKey: "concurrency_cap",
      planCapValue: 3,
      observedValue: 3,
    });
    expect(e.httpStatus).toBe(429);
    expect(e.userMessageCode).toBe("concurrency_exceeded");
    expect(e.gateType).toBe("concurrency_cap_exceeded");
  });

  it("InsufficientUvtBalanceError → 402, uvt_balance_insufficient", () => {
    const e = new InsufficientUvtBalanceError({
      message: "balance too low",
      gateCapKey: "uvt_balance",
      planCapValue: 100,
      observedValue: 500,
    });
    expect(e.httpStatus).toBe(402);
    expect(e.userMessageCode).toBe("uvt_balance_insufficient");
    expect(e.gateType).toBe("insufficient_uvt_balance");
  });

  it("FreeTierModelBlockedError → 402, upgrade_for_model (PR2 class shape frozen today)", () => {
    const e = new FreeTierModelBlockedError({
      message: "not available on free",
      gateCapKey: "tier_model",
      planCapValue: "free",
      observedValue: "claude-opus-4",
    });
    expect(e.httpStatus).toBe(402);
    expect(e.userMessageCode).toBe("upgrade_for_model");
    expect(e.gateType).toBe("free_tier_model_blocked");
  });

  it("all subclasses are catchable as RouterGateError", () => {
    const errs = [
      new OpusBudgetExceededError({ message: "x", gateCapKey: "a", planCapValue: 0, observedValue: 0 }),
      new OutputTokensExceedCapError({ message: "x", gateCapKey: "a", planCapValue: 0, observedValue: 0 }),
      new ConcurrencyCapExceededError({ message: "x", gateCapKey: "a", planCapValue: 0, observedValue: 0 }),
      new InsufficientUvtBalanceError({ message: "x", gateCapKey: "a", planCapValue: 0, observedValue: 0 }),
      new FreeTierModelBlockedError({ message: "x", gateCapKey: "a", planCapValue: "", observedValue: "" }),
    ];
    for (const e of errs) {
      expect(e instanceof RouterGateError).toBe(true);
    }
  });
});
