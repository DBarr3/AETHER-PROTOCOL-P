import { describe, it, expect } from "vitest";
import { computeUvtSimple, computeUvtWeighted } from "@/lib/uvt/compute";

// ─────────────────────────────────────────────────────────────────
// §2.10 Dual-Formula Shadow-Mode PoC — flip-direction value theft.
//
// PR 1 enforces simple formula:  simple = (input - cached) + output
// PR 2 will flip to weighted:    weighted = Σ(w_i * component_i) * model_multiplier
//
// For Opus + output-heavy workloads, WEIGHTED >> SIMPLE. During the
// PR 1 window a Pro/Team user can predict cost as simple (tiny) but
// the true resource cost logged as predicted_uvt_cost (weighted) is
// 5× (opus multiplier) × 4 (w_out) = 20× higher. With the client-
// supplied uvtBalance bypass, simple gate is a no-op regardless, but
// this PoC documents the value gap for the flip day.
//
// Worked example:
//   input=1k, output=1k, model=opus
//   simple   = 1000 + 1000 = 2000
//   weighted = ceil((1000*1 + 1000*4) * 5) = 25_000
//
// On flip day (PR 2 constant change), every in-flight request whose
// attackers previously sized to simple*1.0 suddenly owes weighted*1.0
// → retroactive insolvency. Also the inverse: requests that ran free
// during shadow-mode owe nothing retroactively.
//
// Severity: HIGH (combined with §2.4 bypass). Fix: enforce both
// formulas during the shadow window (whichever is HIGHER gates).
// ─────────────────────────────────────────────────────────────────

describe("PoC 2.10 — simple << weighted on Opus", () => {
  it("documents the flip-direction gap for an Opus workload", () => {
    const usage = {
      input_tokens: 1000,
      output_tokens: 1000,
      thinking_tokens: 0,
      cached_input_tokens: 0,
      sub_agent_count: 0,
      tool_calls: 0,
      model_id: "claude-opus-4",
    };
    const s = computeUvtSimple(usage);
    const w = computeUvtWeighted(usage).uvt_cost;
    expect(s).toBe(2000);
    expect(w).toBe(25000);
    // Ratio ≈ 12.5×. Attackers paying in simple during shadow → debt on flip.
    expect(w / s).toBeGreaterThan(10);
  });

  it("thinking-heavy requests show the largest gap", () => {
    const usage = {
      input_tokens: 100,
      output_tokens: 100,
      thinking_tokens: 10_000,
      cached_input_tokens: 0,
      sub_agent_count: 0,
      tool_calls: 0,
      model_id: "claude-opus-4",
    };
    const s = computeUvtSimple(usage);              // 200
    const w = computeUvtWeighted(usage).uvt_cost;   // (100+400+50000)*5 ≈ 252_500
    expect(s).toBe(200);
    expect(w).toBeGreaterThan(200_000);
  });
});
