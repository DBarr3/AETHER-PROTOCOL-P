import { describe, it, expect } from "vitest";
import {
  computeUvtWeighted,
  computeUvtSimple,
  type UvtUsage,
} from "@/lib/uvt/compute";
import { UVT_WEIGHTS_V1, MODEL_MULTIPLIERS_V1 } from "@/lib/uvt/weights.v1";
import { UnknownModelError } from "@/lib/uvt/errors";

const zero: UvtUsage = {
  input_tokens: 0,
  output_tokens: 0,
  thinking_tokens: 0,
  cached_input_tokens: 0,
  sub_agent_count: 0,
  tool_calls: 0,
  model_id: "claude-sonnet-4",
};

describe("computeUvtSimple — Python-parity formula (input - cached) + output", () => {
  it("returns 0 on zero usage", () => {
    expect(computeUvtSimple(zero)).toBe(0);
  });

  it("returns 1 on exactly 1 output token (floor)", () => {
    const r = computeUvtSimple({ ...zero, output_tokens: 1 });
    expect(r).toBe(1);
  });

  it("counts uncached input + output, ignores cached/thinking/subagent/tool", () => {
    const r = computeUvtSimple({
      ...zero,
      input_tokens: 1000,
      output_tokens: 500,
      cached_input_tokens: 200,
      thinking_tokens: 999,
      sub_agent_count: 10,
      tool_calls: 20,
    });
    expect(r).toBe((1000 - 200) + 500);
  });

  it("never goes negative when cached > input (clamped at 0 uncached)", () => {
    const r = computeUvtSimple({
      ...zero,
      input_tokens: 100,
      cached_input_tokens: 500,
      output_tokens: 50,
    });
    expect(r).toBe(50);
  });

  it("is model-agnostic (same result across all model_ids)", () => {
    const usage = { ...zero, input_tokens: 1000, output_tokens: 300 };
    const models = [
      "claude-haiku-4",
      "claude-sonnet-4",
      "claude-opus-4",
      "gpt-5",
      "gpt-5-mini",
      "perplexity-sonar",
    ];
    const results = models.map((m) => computeUvtSimple({ ...usage, model_id: m }));
    expect(new Set(results).size).toBe(1);
  });
});

describe("computeUvtWeighted — spec §2 weighted formula with model multipliers", () => {
  it("returns 0 on zero usage", () => {
    const r = computeUvtWeighted(zero);
    expect(r.uvt_cost).toBe(0);
    expect(r.uvt_weight_version).toBe(1);
  });

  it("returns >= 1 on any single consumed token (floor via ceil)", () => {
    const r = computeUvtWeighted({ ...zero, output_tokens: 1 });
    expect(r.uvt_cost).toBeGreaterThanOrEqual(1);
  });

  it("opus is exactly 5× sonnet for identical usage (model multiplier)", () => {
    const usage = { ...zero, input_tokens: 1000, output_tokens: 500 };
    const sonnet = computeUvtWeighted({ ...usage, model_id: "claude-sonnet-4" });
    const opus = computeUvtWeighted({ ...usage, model_id: "claude-opus-4" });
    // Sonnet mult 1.0 vs Opus 5.0 → opus should be 5× sonnet
    // (subject to ceil rounding; equal base so both are whole before *5)
    expect(opus.uvt_cost).toBe(sonnet.uvt_cost * 5);
  });

  it("haiku is 0.25× sonnet for identical usage", () => {
    const usage = { ...zero, input_tokens: 1000, output_tokens: 500 };
    const sonnet = computeUvtWeighted({ ...usage, model_id: "claude-sonnet-4" });
    const haiku = computeUvtWeighted({ ...usage, model_id: "claude-haiku-4" });
    // 0.25 × sonnet; use ceil tolerance
    expect(haiku.uvt_cost).toBe(Math.ceil(sonnet.uvt_cost * 0.25));
  });

  it("breakdown components sum to pre_multiplier_subtotal (within ±1 rounding)", () => {
    const r = computeUvtWeighted({
      input_tokens: 123,
      output_tokens: 45,
      thinking_tokens: 67,
      cached_input_tokens: 8,
      sub_agent_count: 2,
      tool_calls: 3,
      model_id: "claude-sonnet-4",
    });
    const sum =
      r.breakdown.input_component +
      r.breakdown.output_component +
      r.breakdown.thinking_component +
      r.breakdown.cached_component +
      r.breakdown.subagent_component +
      r.breakdown.tool_component;
    expect(Math.abs(sum - r.breakdown.pre_multiplier_subtotal)).toBeLessThanOrEqual(
      1e-9,
    );
  });

  it("applies weights per spec v1 constants", () => {
    // Single token in each bucket: component == weight × 1
    const r = computeUvtWeighted({
      input_tokens: 1,
      output_tokens: 1,
      thinking_tokens: 1,
      cached_input_tokens: 1,
      sub_agent_count: 1,
      tool_calls: 1,
      model_id: "claude-sonnet-4",
    });
    expect(r.breakdown.input_component).toBe(UVT_WEIGHTS_V1.w_in);
    expect(r.breakdown.output_component).toBe(UVT_WEIGHTS_V1.w_out);
    expect(r.breakdown.thinking_component).toBe(UVT_WEIGHTS_V1.w_think);
    expect(r.breakdown.cached_component).toBe(UVT_WEIGHTS_V1.w_cached_in);
    expect(r.breakdown.subagent_component).toBe(UVT_WEIGHTS_V1.w_subagent_fixed);
    expect(r.breakdown.tool_component).toBe(UVT_WEIGHTS_V1.w_tool);
  });

  it("model_multiplier in breakdown matches MODEL_MULTIPLIERS_V1 for each model", () => {
    for (const [mid, mult] of Object.entries(MODEL_MULTIPLIERS_V1)) {
      const r = computeUvtWeighted({ ...zero, output_tokens: 10, model_id: mid });
      expect(r.breakdown.model_multiplier).toBe(mult);
    }
  });

  it("returns integer uvt_cost (ceil applied)", () => {
    const r = computeUvtWeighted({
      ...zero,
      input_tokens: 1,
      output_tokens: 0,
      model_id: "claude-haiku-4",
    });
    // 1 × 0.25 = 0.25 → ceil → 1
    expect(r.uvt_cost).toBe(1);
    expect(Number.isInteger(r.uvt_cost)).toBe(true);
  });

  it("throws UnknownModelError for unknown model_id", () => {
    expect(() =>
      computeUvtWeighted({ ...zero, output_tokens: 1, model_id: "gpt-100" }),
    ).toThrow(UnknownModelError);
  });

  it("is pure — no Date/Math.random/IO observable between calls", () => {
    const usage = { ...zero, input_tokens: 1000, output_tokens: 500 };
    const a = computeUvtWeighted(usage);
    const b = computeUvtWeighted(usage);
    expect(a).toEqual(b);
  });
});
