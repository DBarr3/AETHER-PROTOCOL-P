import { UVT_WEIGHTS_V1, MODEL_MULTIPLIERS_V1 } from "./weights.v1";
import { UnknownModelError } from "./errors";

export interface UvtUsage {
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  cached_input_tokens: number;
  sub_agent_count: number;
  tool_calls: number;
  model_id: string;
}

export interface UvtResult {
  uvt_cost: number;
  uvt_weight_version: number;
  breakdown: {
    input_component: number;
    output_component: number;
    thinking_component: number;
    cached_component: number;
    subagent_component: number;
    tool_component: number;
    pre_multiplier_subtotal: number;
    model_multiplier: number;
  };
}

export function computeUvtSimple(usage: UvtUsage): number {
  const uncached = Math.max(0, usage.input_tokens - usage.cached_input_tokens);
  return uncached + usage.output_tokens;
}

export function computeUvtWeighted(usage: UvtUsage): UvtResult {
  const mult = MODEL_MULTIPLIERS_V1[usage.model_id];
  if (mult === undefined) {
    throw new UnknownModelError(usage.model_id);
  }

  const w = UVT_WEIGHTS_V1;
  const input_component = usage.input_tokens * w.w_in;
  const output_component = usage.output_tokens * w.w_out;
  const thinking_component = usage.thinking_tokens * w.w_think;
  const cached_component = usage.cached_input_tokens * w.w_cached_in;
  const subagent_component = usage.sub_agent_count * w.w_subagent_fixed;
  const tool_component = usage.tool_calls * w.w_tool;

  const pre_multiplier_subtotal =
    input_component +
    output_component +
    thinking_component +
    cached_component +
    subagent_component +
    tool_component;

  const uvt_cost = Math.ceil(pre_multiplier_subtotal * mult);

  return {
    uvt_cost,
    uvt_weight_version: w.version,
    breakdown: {
      input_component,
      output_component,
      thinking_component,
      cached_component,
      subagent_component,
      tool_component,
      pre_multiplier_subtotal,
      model_multiplier: mult,
    },
  };
}
