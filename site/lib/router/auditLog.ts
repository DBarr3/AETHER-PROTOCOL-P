import { trace } from "@opentelemetry/api";
import type { RoutingContext, RoutingDecision } from "./types";
import type { RouterGateError } from "./errors";

export interface RoutingDecisionRow {
  user_id: string;
  request_id: string;
  trace_id: string;
  task_kind: string;
  tier: string;
  chosen_model: string | null;
  reason_code: string;
  gate_error_type: string | null;
  gate_cap_key: string | null;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  predicted_uvt_cost: number | null;
  predicted_uvt_cost_simple: number | null;
  opus_pct_mtd_snapshot: number;
  active_concurrent_tasks: number;
  uvt_balance_snapshot: number;
  decision_schema_version: number;
  uvt_weight_version: number;
  latency_ms: number;
}

export type AuditWriter = (row: RoutingDecisionRow) => Promise<void>;

const noopWriter: AuditWriter = async () => {};

let _writer: AuditWriter = noopWriter;
let _errorHandler: (err: unknown) => void = (err) => {
  // Emit OTel event — never log body (may contain SQL/user data)
  const span = trace.getActiveSpan();
  const name = err instanceof Error ? err.name : "unknown";
  span?.addEvent("router.audit_log_failure", { "error.type": name });
};

export function setAuditWriter(writer: AuditWriter): void {
  _writer = writer;
}

export function resetAuditWriter(): void {
  _writer = noopWriter;
}

export function setAuditErrorHandler(h: (err: unknown) => void): void {
  _errorHandler = h;
}

function fireAndForget(row: RoutingDecisionRow): void {
  Promise.resolve()
    .then(() => _writer(row))
    .catch((err) => {
      try {
        _errorHandler(err);
      } catch {
        // handler errors are intentionally swallowed — audit must never crash caller
      }
    });
}

export function recordDecisionAsync(
  ctx: RoutingContext,
  d: RoutingDecision,
): void {
  fireAndForget({
    user_id: ctx.userId,
    request_id: ctx.requestId,
    trace_id: ctx.traceId,
    task_kind: ctx.taskKind,
    tier: ctx.tier,
    chosen_model: d.chosen_model,
    reason_code: d.reason_code,
    gate_error_type: null,
    gate_cap_key: null,
    estimated_input_tokens: ctx.estimatedInputTokens,
    estimated_output_tokens: ctx.estimatedOutputTokens,
    predicted_uvt_cost: d.predicted_uvt_cost,
    predicted_uvt_cost_simple: d.predicted_uvt_cost_simple,
    opus_pct_mtd_snapshot: ctx.opusPctMtd,
    active_concurrent_tasks: ctx.activeConcurrentTasks,
    uvt_balance_snapshot: ctx.uvtBalance,
    decision_schema_version: d.decision_schema_version,
    uvt_weight_version: d.uvt_weight_version,
    latency_ms: d.latency_ms,
  });
}

export function recordGateAsync(
  ctx: RoutingContext,
  err: RouterGateError,
  latencyMs: number,
): void {
  fireAndForget({
    user_id: ctx.userId,
    request_id: ctx.requestId,
    trace_id: ctx.traceId,
    task_kind: ctx.taskKind,
    tier: ctx.tier,
    chosen_model: null,
    reason_code: "gate_rejected",
    gate_error_type: err.gateType,
    gate_cap_key: err.gateCapKey,
    estimated_input_tokens: ctx.estimatedInputTokens,
    estimated_output_tokens: ctx.estimatedOutputTokens,
    predicted_uvt_cost: null,
    predicted_uvt_cost_simple: null,
    opus_pct_mtd_snapshot: ctx.opusPctMtd,
    active_concurrent_tasks: ctx.activeConcurrentTasks,
    uvt_balance_snapshot: ctx.uvtBalance,
    decision_schema_version: 1,
    uvt_weight_version: 1,
    latency_ms: latencyMs,
  });
}

// Production wiring — called once at app boot from the API route.
// Kept as a factory so tests don't accidentally hit Supabase.
export function makeSupabaseAuditWriter(
  supabase: { from: (t: string) => { insert: (row: unknown) => Promise<{ error: unknown }> } },
): AuditWriter {
  return async (row: RoutingDecisionRow) => {
    const { error } = await supabase.from("routing_decisions").insert(row);
    if (error) {
      throw error instanceof Error ? error : new Error(String(error));
    }
  };
}
