import { performance } from "node:perf_hooks";
import { computeUvtWeighted, computeUvtSimple } from "@/lib/uvt/compute";
import { UVT_WEIGHTS_V1 } from "@/lib/uvt/weights.v1";
import {
  DEFAULT_MODEL_BY_TIER_AND_TASK,
  PLAN_CAPS,
  UVT_FORMULA_ENFORCEMENT,
} from "./constants";
import {
  RouterGateError,
  OpusBudgetExceededError,
  OutputTokensExceedCapError,
  ConcurrencyCapExceededError,
  InsufficientUvtBalanceError,
} from "./errors";
import { recordDecisionAsync, recordGateAsync } from "./auditLog";
import type { RoutingContext, RoutingDecision } from "./types";

function throwGate(
  err: RouterGateError,
  ctx: RoutingContext,
  t0: number,
): never {
  const latencyMs = Math.round(performance.now() - t0);
  recordGateAsync(ctx, err, latencyMs);
  throw err;
}

export function pick(ctx: RoutingContext): RoutingDecision {
  const t0 = performance.now();
  const plan = PLAN_CAPS[ctx.tier];
  const model = DEFAULT_MODEL_BY_TIER_AND_TASK[ctx.tier][ctx.taskKind];

  if (model === "claude-opus-4" && ctx.opusPctMtd >= plan.opus_pct_cap) {
    throwGate(
      new OpusBudgetExceededError({
        message: `Opus MTD usage ${(ctx.opusPctMtd * 100).toFixed(1)}% ≥ plan cap ${(plan.opus_pct_cap * 100).toFixed(1)}%.`,
        gateCapKey: "opus_pct_cap",
        planCapValue: plan.opus_pct_cap,
        observedValue: ctx.opusPctMtd,
      }),
      ctx,
      t0,
    );
  }

  if (ctx.estimatedOutputTokens > plan.output_cap) {
    throwGate(
      new OutputTokensExceedCapError({
        message: `Requested ${ctx.estimatedOutputTokens} output tokens > plan cap ${plan.output_cap}.`,
        gateCapKey: "output_cap",
        planCapValue: plan.output_cap,
        observedValue: ctx.estimatedOutputTokens,
      }),
      ctx,
      t0,
    );
  }

  if (ctx.activeConcurrentTasks >= plan.concurrency_cap) {
    throwGate(
      new ConcurrencyCapExceededError({
        message: `Active ${ctx.activeConcurrentTasks} ≥ plan concurrency cap ${plan.concurrency_cap}.`,
        gateCapKey: "concurrency_cap",
        planCapValue: plan.concurrency_cap,
        observedValue: ctx.activeConcurrentTasks,
      }),
      ctx,
      t0,
    );
  }

  const usage = {
    input_tokens: ctx.estimatedInputTokens,
    output_tokens: ctx.estimatedOutputTokens,
    thinking_tokens: 0,
    cached_input_tokens: 0,
    sub_agent_count: 0,
    tool_calls: 0,
    model_id: model,
  };
  const predictedWeighted = computeUvtWeighted(usage);
  const predictedSimple = computeUvtSimple(usage);

  const enforced =
    UVT_FORMULA_ENFORCEMENT === "simple"
      ? predictedSimple
      : predictedWeighted.uvt_cost;

  if (enforced > ctx.uvtBalance) {
    throwGate(
      new InsufficientUvtBalanceError({
        message: `Predicted ${enforced} UVT > balance ${ctx.uvtBalance}.`,
        gateCapKey: "uvt_balance",
        planCapValue: ctx.uvtBalance,
        observedValue: enforced,
      }),
      ctx,
      t0,
    );
  }

  const decision: RoutingDecision = {
    chosen_model: model,
    reason_code: "default_by_tier_and_task",
    predicted_uvt_cost: predictedWeighted.uvt_cost,
    predicted_uvt_cost_simple: predictedSimple,
    decision_schema_version: 1,
    uvt_weight_version: UVT_WEIGHTS_V1.version,
    latency_ms: Math.round(performance.now() - t0),
  };

  recordDecisionAsync(ctx, decision);
  return decision;
}
